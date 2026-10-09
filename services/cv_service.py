import os
import re
import cv2
import base64
import math
import uuid
import numpy as np
from datetime import datetime
from database import db
from models import ANPRLog, Booking, ParkingSlot, ParkingLocation, Vehicle, User, Blacklist, ActivityLog, Invoice
from services.invoice_service import generate_pdf_invoice
from services.booking_service import generate_invoice_number
from services.socket_service import broadcast_anpr_event

# Global EasyOCR Reader instance (initialized lazily to avoid startup delay)
_easyocr_reader = None

def get_ocr_reader():
    global _easyocr_reader
    if _easyocr_reader is None:
        try:
            import easyocr
            # Load English OCR reader on CPU
            _easyocr_reader = easyocr.Reader(['en'], gpu=False)
        except Exception as e:
            print(f"[CV Service] EasyOCR init warning: {e}")
            _easyocr_reader = False
    return _easyocr_reader

def decode_base64_image(base64_str):
    """
    Decodes a base64 encoded image string into an OpenCV BGR numpy array.
    """
    try:
        if not base64_str:
            return None
        if ',' in base64_str:
            base64_str = base64_str.split(',')[1]
        img_bytes = base64.b64decode(base64_str)
        nparr = np.frombuffer(img_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        return img
    except Exception as e:
        print(f"[CV Service] Base64 decode error: {e}")
        return None

def clean_plate_text(raw_text):
    """
    Sanitize OCR text into clean uppercase license plate string (e.g. GJ09AB1234, MH12DE5678)
    """
    if not raw_text:
        return ""
    cleaned = re.sub(r'[^A-Za-z0-9]', '', raw_text).upper()
    
    # Try Indian plate pattern match: XX 00 XX 0000 or XX 00 X 0000
    plate_match = re.search(r'[A-Z]{2}[0-9]{1,2}[A-Z]{1,3}[0-9]{4}', cleaned)
    if plate_match:
        return plate_match.group(0)
    
    # General alphanumeric license plate format (5 to 11 chars)
    gen_match = re.search(r'[A-Z0-9]{5,11}', cleaned)
    if gen_match:
        return gen_match.group(0)
        
    return cleaned

def preprocess_and_detect_plate_region(img):
    """
    OpenCV computer vision pipeline to extract candidate license plate region.
    Finds rectangular contours matching standard license plate aspect ratio (approx 1.5 to 6.5).
    """
    if img is None:
        return None, None

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # Apply CLAHE contrast enhancement for low lighting conditions
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    
    bfilter = cv2.bilateralFilter(enhanced, 11, 17, 17)
    edged = cv2.Canny(bfilter, 30, 200)

    # Find contours
    keypoints = cv2.findContours(edged.copy(), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    contours = keypoints[0] if len(keypoints) == 2 else keypoints[1]
    contours = sorted(contours, key=cv2.contourArea, reverse=True)[:15]

    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if h > 0 and w > 0:
            aspect_ratio = float(w) / float(h)
            area = cv2.contourArea(contour)
            if 1.5 <= aspect_ratio <= 6.5 and area > 400:
                cropped_plate = enhanced[max(0, y-5):min(img.shape[0], y+h+5), max(0, x-5):min(img.shape[1], x+w+5)]
                if cropped_plate.size > 0:
                    return cropped_plate, (x, y, w, h)

    return enhanced, (0, 0, img.shape[1], img.shape[0])

def perform_anpr_ocr(img):
    """
    Runs ANPR OCR on frame image using EasyOCR with multi-stage fallback.
    """
    if img is None:
        return "", 0.0, (0, 0, 0, 0)

    cropped_plate, bbox = preprocess_and_detect_plate_region(img)
    reader = get_ocr_reader()
    
    detected_text = ""
    confidence = 0.0

    if reader:
        # Stage 1: Try reading cropped candidate region
        if cropped_plate is not None and cropped_plate.size > 0:
            try:
                results = reader.readtext(cropped_plate)
                if results:
                    best = max(results, key=lambda x: x[2])
                    candidate = clean_plate_text(best[1])
                    if len(candidate) >= 4:
                        detected_text = candidate
                        confidence = float(best[2])
            except Exception as e:
                print(f"[CV Service] EasyOCR cropped read error: {e}")

        # Stage 2: Fallback to full frame OCR if cropped stage did not yield valid plate
        if not detected_text or len(detected_text) < 4:
            try:
                results = reader.readtext(img)
                if results:
                    # Filter results by length and confidence
                    valid_candidates = []
                    for res in results:
                        txt = clean_plate_text(res[1])
                        conf = float(res[2])
                        if len(txt) >= 4:
                            valid_candidates.append((txt, conf, res[0]))
                    if valid_candidates:
                        best = max(valid_candidates, key=lambda x: x[1])
                        detected_text = best[0]
                        confidence = best[1]
            except Exception as e:
                print(f"[CV Service] EasyOCR full-frame read error: {e}")

    return detected_text, confidence, bbox

def process_anpr_frame(location_id, base64_frame, camera_type='ENTRY', manual_plate=None):
    """
    Main ANPR API processing pipeline.
    Decodes frame, performs ANPR OCR, checks database, updates booking/slot, logs event.
    """
    img = decode_base64_image(base64_frame) if base64_frame else None
    bbox = (0, 0, 0, 0)
    plate_number = ""
    confidence = 0.0

    if img is not None:
        plate_number, confidence, bbox = perform_anpr_ocr(img)

    # Use manual plate if provided or fallback when OCR fails
    if manual_plate and manual_plate.strip():
        plate_number = clean_plate_text(manual_plate)
        confidence = 1.0

    if not plate_number or len(plate_number) < 4:
        return False, "Unable to read license plate from image. Please enter vehicle number manually.", None

    success, message, result = process_anpr_plate_logic(location_id, plate_number, confidence, camera_type)
    if result:
        result['bbox'] = {'x': bbox[0], 'y': bbox[1], 'w': bbox[2], 'h': bbox[3]}
    return success, message, result

def get_or_create_walkin_user_and_vehicle(plate_number):
    """
    Ensures a valid User and Vehicle exist for walk-in or manual gate entries.
    """
    plate_number = clean_plate_text(plate_number)
    vehicle = Vehicle.query.filter_by(vehicle_number=plate_number).first()
    if vehicle:
        return vehicle.owner, vehicle

    # Get system walkin user or default admin
    walkin_user = User.query.filter_by(email='walkin@smartpark.com').first()
    if not walkin_user:
        walkin_user = User(
            full_name="Walk-In Guest",
            email="walkin@smartpark.com",
            phone="+91 0000000000",
            role="user",
            is_active=True
        )
        walkin_user.set_password("walkin123")
        db.session.add(walkin_user)
        db.session.flush()

    vehicle = Vehicle(
        user_id=walkin_user.id,
        vehicle_number=plate_number,
        vehicle_type="Car",
        model="Walk-in Vehicle",
        nickname="Walk-in"
    )
    db.session.add(vehicle)
    db.session.flush()
    return walkin_user, vehicle

def process_anpr_plate_logic(location_id, plate_number, confidence=0.9, camera_type='ENTRY'):
    """
    Business logic for ANPR plate recognition event.
    Handles online bookings, walk-in/manual entries, and exit fee calculations.
    """
    plate_number = clean_plate_text(plate_number)
    if not plate_number:
        return False, "License plate number is required.", None

    location = db.session.get(ParkingLocation, location_id) if hasattr(db.session, 'get') else ParkingLocation.query.get(location_id)
    if not location:
        return False, "Invalid location ID", None

    # Check Blacklist
    blacklisted = Blacklist.query.filter_by(vehicle_number=plate_number).first()
    if blacklisted:
        action_taken = "BLACKLISTED"
        anpr_log = ANPRLog(
            location_id=location_id,
            detected_plate=plate_number,
            confidence=confidence,
            action_taken=action_taken
        )
        db.session.add(anpr_log)
        db.session.commit()
        
        broadcast_anpr_event({
            'detected_plate': plate_number,
            'location_name': location.name,
            'action_taken': action_taken,
            'reason': blacklisted.reason,
            'alert_level': 'HIGH'
        })
        return True, f"⚠️ ALERT: Blacklisted Vehicle Detected ({plate_number})!", {
            'plate': plate_number,
            'action': action_taken,
            'status': 'REJECTED'
        }

    # Find Vehicle & Booking match
    vehicle = Vehicle.query.filter_by(vehicle_number=plate_number).first()
    matched_booking = None
    
    if vehicle:
        # Search for active/confirmed booking at this location for this vehicle
        matched_booking = Booking.query.filter(
            Booking.vehicle_id == vehicle.id,
            Booking.location_id == location_id,
            Booking.status.in_(['CONFIRMED', 'ACTIVE', 'RESERVED'])
        ).order_by(Booking.start_time.asc()).first()

    now = datetime.utcnow()
    action_taken = "PROCESSED"
    message = ""
    status_code = "SUCCESS"
    total_fee = 0.0
    duration_hrs = 1.0

    if camera_type == 'ENTRY':
        if matched_booking:
            # Active or pre-booked reservation
            matched_booking.status = 'ACTIVE'
            matched_booking.start_time = now
            slot = ParkingSlot.query.get(matched_booking.slot_id)
            if slot:
                slot.status = 'OCCUPIED'
                slot.current_vehicle_number = plate_number
                slot.current_booking_id = matched_booking.id
            action_taken = "ENTRY_GRANTED"
            total_fee = matched_booking.total_amount
            message = f"✅ Access Granted! Vehicle {plate_number} entering Slot {slot.slot_number if slot else 'N/A'}"
        else:
            # Walk-in / Manual Gate Entry without prior online booking
            user, vehicle = get_or_create_walkin_user_and_vehicle(plate_number)
            slot = ParkingSlot.query.filter_by(location_id=location_id, status='FREE').first()
            if not slot:
                return False, f"❌ Parking Full! No free slots available at {location.name}.", None

            booking_ref = f"SP-WALKIN-{uuid.uuid4().hex[:6].upper()}"
            matched_booking = Booking(
                booking_reference=booking_ref,
                user_id=user.id,
                vehicle_id=vehicle.id,
                location_id=location_id,
                slot_id=slot.id,
                start_time=now,
                end_time=now, # will update on exit
                duration_hours=1.0,
                hourly_rate=location.hourly_rate,
                total_amount=location.hourly_rate,
                status='ACTIVE'
            )
            db.session.add(matched_booking)
            db.session.flush()

            slot.status = 'OCCUPIED'
            slot.current_vehicle_number = plate_number
            slot.current_booking_id = matched_booking.id
            location.available_slots = max(0, location.available_slots - 1)

            # Generate Invoice
            inv_num = generate_invoice_number()
            invoice = Invoice(
                invoice_number=inv_num,
                booking_id=matched_booking.id,
                user_id=user.id,
                subtotal=location.hourly_rate,
                tax=0.0,
                total_amount=location.hourly_rate,
                payment_status='PENDING',
                invoice_status='GENERATED'
            )
            db.session.add(invoice)
            db.session.flush()

            action_taken = "ENTRY_GRANTED"
            total_fee = location.hourly_rate
            message = f"✅ Walk-In Entry Granted! Vehicle {plate_number} assigned to Slot {slot.slot_number}. Rate: ₹{location.hourly_rate}/hr"

    else: # EXIT & FEE CALCULATION
        if matched_booking:
            start_time = matched_booking.start_time or now
            elapsed_seconds = (now - start_time).total_seconds()
            duration_hrs = max(0.5, round(elapsed_seconds / 3600.0, 2))
            billing_hours = max(1.0, math.ceil(duration_hrs))
            
            total_fee = round(billing_hours * location.hourly_rate, 2)
            
            matched_booking.end_time = now
            matched_booking.duration_hours = duration_hrs
            matched_booking.total_amount = total_fee
            matched_booking.status = 'COMPLETED'

            slot = ParkingSlot.query.get(matched_booking.slot_id)
            if slot:
                slot.status = 'FREE'
                slot.current_vehicle_number = None
                slot.current_booking_id = None

            location.available_slots = min(location.total_slots, location.available_slots + 1)

            # Update Invoice
            invoice = matched_booking.invoice
            if not invoice:
                invoice = Invoice(
                    invoice_number=generate_invoice_number(),
                    booking_id=matched_booking.id,
                    user_id=matched_booking.user_id,
                    subtotal=total_fee,
                    tax=0.0,
                    total_amount=total_fee,
                    payment_status='PAID',
                    invoice_status='GENERATED'
                )
                db.session.add(invoice)
                db.session.flush()
            else:
                invoice.subtotal = total_fee
                invoice.total_amount = total_fee
                invoice.payment_status = 'PAID'

            # Generate PDF Invoice
            try:
                generate_pdf_invoice(matched_booking, invoice)
            except Exception as pe:
                print(f"[CV Service] Invoice PDF generation notice: {pe}")

            action_taken = "EXIT_COMPLETED"
            message = f"🚗 Exit Confirmed for Vehicle {plate_number}! Stay Duration: {duration_hrs} hrs. Total Fee: ₹{total_fee}"
        else:
            # Vehicle exit with no active booking recorded: calculate baseline exit fee
            user, vehicle = get_or_create_walkin_user_and_vehicle(plate_number)
            total_fee = location.hourly_rate
            duration_hrs = 1.0
            action_taken = "EXIT_COMPLETED"
            message = f"🚗 Exit Processed for Vehicle {plate_number}. Direct Parking Fee: ₹{total_fee}"

    db.session.commit()

    # Log ANPR event
    anpr_log = ANPRLog(
        location_id=location_id,
        detected_plate=plate_number,
        confidence=confidence,
        matched_booking_id=matched_booking.id if matched_booking else None,
        action_taken=action_taken
    )
    db.session.add(anpr_log)
    
    # Activity Log
    act_log = ActivityLog(
        user_type='system',
        action=f"ANPR_{camera_type}",
        description=f"ANPR scanned {plate_number} at {location.name}. Action: {action_taken} | Fee: ₹{total_fee}",
        related_id=anpr_log.id
    )
    db.session.add(act_log)
    db.session.commit()

    # Real-time WebSocket Alert to Admin
    broadcast_anpr_event({
        'anpr_id': anpr_log.id,
        'detected_plate': plate_number,
        'location_name': location.name,
        'action_taken': action_taken,
        'total_fee': total_fee,
        'booking_ref': matched_booking.booking_reference if matched_booking else None,
        'slot_number': matched_booking.slot.slot_number if (matched_booking and matched_booking.slot) else None,
        'timestamp': datetime.utcnow().strftime('%H:%M:%S')
    })

    return True, message, {
        'anpr_id': anpr_log.id,
        'plate': plate_number,
        'confidence': confidence,
        'action': action_taken,
        'status': status_code,
        'duration_hours': duration_hrs,
        'hourly_rate': location.hourly_rate,
        'total_fee': total_fee,
        'booking_reference': matched_booking.booking_reference if matched_booking else None,
        'slot_number': matched_booking.slot.slot_number if (matched_booking and matched_booking.slot) else None,
        'invoice_id': matched_booking.invoice.id if (matched_booking and matched_booking.invoice) else None
    }

def calculate_parking_fee_for_plate(location_id, plate_number, estimated_hours=1.0):
    """
    Calculates the exact parking fee for a given license plate at a location.
    Checks active booking duration if vehicle is currently parked.
    """
    plate_number = clean_plate_text(plate_number)
    if not plate_number:
        return False, "License plate number is required.", None

    location = db.session.get(ParkingLocation, location_id) if hasattr(db.session, 'get') else ParkingLocation.query.get(location_id)
    if not location:
        return False, "Invalid location ID", None

    vehicle = Vehicle.query.filter_by(vehicle_number=plate_number).first()
    active_booking = None
    if vehicle:
        active_booking = Booking.query.filter(
            Booking.vehicle_id == vehicle.id,
            Booking.location_id == location_id,
            Booking.status == 'ACTIVE'
        ).first()

    now = datetime.utcnow()
    if active_booking:
        elapsed = (now - active_booking.start_time).total_seconds()
        duration_hrs = max(0.5, round(elapsed / 3600.0, 2))
        billing_hours = max(1.0, math.ceil(duration_hrs))
        total_fee = round(billing_hours * location.hourly_rate, 2)
        is_parked = True
        entry_time = active_booking.start_time.strftime('%Y-%m-%d %H:%M')
        slot_number = active_booking.slot.slot_number if active_booking.slot else 'N/A'
    else:
        try:
            duration_hrs = float(estimated_hours)
        except (ValueError, TypeError):
            duration_hrs = 1.0
        billing_hours = max(1.0, math.ceil(duration_hrs))
        total_fee = round(billing_hours * location.hourly_rate, 2)
        is_parked = False
        entry_time = now.strftime('%Y-%m-%d %H:%M')
        slot_number = 'N/A'

    return True, f"Fee calculated for {plate_number}: ₹{total_fee}", {
        'plate': plate_number,
        'location_name': location.name,
        'hourly_rate': location.hourly_rate,
        'duration_hours': duration_hrs,
        'billing_hours': billing_hours,
        'total_fee': total_fee,
        'is_currently_parked': is_parked,
        'entry_time': entry_time,
        'slot_number': slot_number
    }
