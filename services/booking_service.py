import uuid
from datetime import datetime, timedelta
from database import db
from models import Booking, ParkingLocation, ParkingSlot, Vehicle, User, Invoice, ActivityLog
from services.invoice_service import generate_pdf_invoice
from services.socket_service import broadcast_new_booking, broadcast_booking_cancelled

def generate_booking_reference():
    return f"SP-{str(uuid.uuid4().hex[:8]).upper()}"

def generate_invoice_number():
    return f"INV-SP-{str(uuid.uuid4().hex[:8]).upper()}"

def create_booking(user_id, vehicle_id, location_id, slot_id, start_time_str, duration_hours):
    """
    Concurrency-safe booking creation service.
    Single source of truth for all bookings.
    """
    try:
        duration = float(duration_hours)
        if duration <= 0:
            return False, "Duration must be greater than 0 hours.", None
            
        start_time = datetime.strptime(start_time_str, "%Y-%m-%dT%H:%M")
        end_time = start_time + timedelta(hours=duration)
    except Exception as e:
        return False, f"Invalid date or time format: {str(e)}", None

    # Fetch and lock target slot for update (prevent race conditions)
    slot = ParkingSlot.query.with_for_update().get(slot_id)
    if not slot or slot.location_id != int(location_id):
        return False, "Selected parking slot does not exist or location mismatch.", None

    if slot.status in ['OCCUPIED', 'MAINTENANCE']:
        return False, f"Slot {slot.slot_number} is currently unavailable ({slot.status}).", None

    # Check for overlapping active bookings on the exact same slot
    overlapping_booking = Booking.query.filter(
        Booking.slot_id == slot_id,
        Booking.status.in_(['CONFIRMED', 'ACTIVE', 'RESERVED']),
        Booking.start_time < end_time,
        Booking.end_time > start_time
    ).first()

    if overlapping_booking:
        return False, f"Sorry, slot {slot.slot_number} was just booked by another user for this time slot.", None

    # Verify Location
    location = ParkingLocation.query.get(location_id)
    if not location or location.status != 'OPEN':
        return False, "Parking location is currently closed or under maintenance.", None

    if location.available_slots <= 0:
        return False, "Sorry, this parking location has no available slots left.", None

    # Verify Vehicle
    vehicle = Vehicle.query.filter_by(id=vehicle_id, user_id=user_id).first()
    if not vehicle:
        return False, "Selected vehicle was not found in your account.", None

    user = User.query.get(user_id)

    # Compute Total Amount
    subtotal = location.hourly_rate * duration
    tax = round(subtotal * 0.0, 2) # Configurable tax
    total_amount = subtotal + tax

    booking_ref = generate_booking_reference()

    # Create Booking Record
    booking = Booking(
        booking_reference=booking_ref,
        user_id=user_id,
        vehicle_id=vehicle_id,
        location_id=location_id,
        slot_id=slot_id,
        start_time=start_time,
        end_time=end_time,
        duration_hours=duration,
        hourly_rate=location.hourly_rate,
        total_amount=total_amount,
        status='CONFIRMED'
    )
    db.session.add(booking)
    db.session.flush() # Get booking.id

    # Reserve Slot and Update Location counts
    slot.status = 'RESERVED'
    slot.current_vehicle_number = vehicle.vehicle_number
    slot.current_booking_id = booking.id
    
    location.available_slots = max(0, location.available_slots - 1)

    # Generate Invoice
    invoice_num = generate_invoice_number()
    invoice = Invoice(
        invoice_number=invoice_num,
        booking_id=booking.id,
        user_id=user_id,
        subtotal=subtotal,
        tax=tax,
        total_amount=total_amount,
        payment_status='PENDING',
        invoice_status='GENERATED'
    )
    db.session.add(invoice)
    db.session.flush()

    # Create PDF file
    generate_pdf_invoice(booking, invoice)

    # Log Activity
    log = ActivityLog(
        user_id=user_id,
        user_type='user',
        action='BOOKING_CREATED',
        description=f"User {user.full_name} booked Slot {slot.slot_number} at {location.name} for ₹{total_amount}",
        related_id=booking.id
    )
    db.session.add(log)
    
    db.session.commit()

    # Real-time WebSocket Broadcast
    broadcast_new_booking({
        'id': booking.id,
        'booking_reference': booking.booking_reference,
        'user_name': user.full_name,
        'vehicle_number': vehicle.vehicle_number,
        'location_id': location.id,
        'location_name': location.name,
        'slot_id': slot.id,
        'slot_number': slot.slot_number,
        'start_time': start_time.strftime('%b %d, %Y %I:%M %p'),
        'end_time': end_time.strftime('%b %d, %Y %I:%M %p'),
        'amount': total_amount
    })

    return True, "Booking confirmed successfully!", booking


def cancel_booking(booking_id, cancelled_by='user', reason=None, user_id=None):
    """
    Single source of truth for cancelling a booking (used by User and Admin).
    """
    booking = Booking.query.get(booking_id)
    if not booking:
        return False, "Booking record not found."

    if booking.status in ['CANCELLED', 'COMPLETED', 'EXPIRED']:
        return False, f"Booking is already {booking.status.lower()}."

    # If user-initiated, verify authorization & cancellation rules
    if cancelled_by == 'user':
        if booking.user_id != user_id:
            return False, "Unauthorized action."
        
        # User cancellation rule check: e.g. at least 30 mins prior to start_time
        if datetime.utcnow() > (booking.start_time - timedelta(minutes=5)):
            return False, "Cancellation window has expired for this booking."

    # Update Booking Status
    booking.status = 'CANCELLED'
    booking.cancelled_at = datetime.utcnow()
    booking.cancelled_by = cancelled_by
    booking.cancellation_reason = reason or ("Cancelled by Admin" if cancelled_by == 'admin' else "Cancelled by User")

    # Free up slot and update available count
    slot = ParkingSlot.query.get(booking.slot_id)
    if slot:
        slot.status = 'FREE'
        slot.current_vehicle_number = None
        slot.current_booking_id = None

    location = ParkingLocation.query.get(booking.location_id)
    if location:
        location.available_slots = min(location.total_slots, location.available_slots + 1)

    # Cancel invoice
    if booking.invoice:
        booking.invoice.invoice_status = 'CANCELLED'

    # Audit log
    log = ActivityLog(
        user_id=user_id or booking.user_id,
        user_type=cancelled_by,
        action='BOOKING_CANCELLED',
        description=f"Booking #{booking.booking_reference} cancelled by {cancelled_by}. Reason: {booking.cancellation_reason}",
        related_id=booking.id
    )
    db.session.add(log)
    
    db.session.commit()

    # Socket broadcast
    broadcast_booking_cancelled({
        'booking_id': booking.id,
        'booking_reference': booking.booking_reference,
        'location_id': booking.location_id,
        'slot_id': booking.slot_id,
        'cancelled_by': cancelled_by,
        'reason': booking.cancellation_reason
    })

    return True, "Booking cancelled successfully."
