from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file
from models import User, Vehicle, ParkingLocation, ParkingSlot, Booking, Invoice
from services.auth_service import login_required, get_current_user
from services.booking_service import create_booking, cancel_booking
from config import Config
import os

user_bp = Blueprint('user', __name__)

@user_bp.route('/')
def home():
    locations = ParkingLocation.query.filter_by(status='OPEN').limit(6).all()
    return render_template('index.html', locations=locations)


@user_bp.route('/find-parking')
def find_parking():
    locations = ParkingLocation.query.filter_by(status='OPEN').all()
    locations_json = [loc.to_dict() for loc in locations]
    google_maps_key = Config.GOOGLE_MAPS_API_KEY
    mapbox_token = Config.MAPBOX_ACCESS_TOKEN
    return render_template('find_parking.html', locations=locations, locations_json=locations_json, google_maps_key=google_maps_key, mapbox_token=mapbox_token)


@user_bp.route('/dashboard')
@login_required
def dashboard():
    user = get_current_user()
    
    # Active / Upcoming Booking
    active_booking = Booking.query.filter(
        Booking.user_id == user.id,
        Booking.status.in_(['CONFIRMED', 'ACTIVE', 'RESERVED'])
    ).order_by(Booking.start_time.asc()).first()

    # Recent Bookings History
    recent_bookings = Booking.query.filter_by(user_id=user.id).order_by(Booking.created_at.desc()).limit(10).all()
    
    # User Vehicles
    vehicles = Vehicle.query.filter_by(user_id=user.id).all()

    return render_template(
        'dashboard.html',
        user=user,
        active_booking=active_booking,
        recent_bookings=recent_bookings,
        vehicles=vehicles
    )


@user_bp.route('/book/<int:location_id>', methods=['GET', 'POST'])
@login_required
def book_slot(location_id):
    user = get_current_user()
    location = ParkingLocation.query.get_or_404(location_id)
    vehicles = Vehicle.query.filter_by(user_id=user.id).all()

    if request.method == 'POST':
        slot_id = request.form.get('slot_id')
        vehicle_id = request.form.get('vehicle_id')
        start_time = request.form.get('start_time') # YYYY-MM-DDTHH:MM
        duration = request.form.get('duration', 1.0)

        if not vehicle_id:
            flash('Please select or add a vehicle before booking.', 'warning')
            return redirect(url_for('user.book_slot', location_id=location_id))

        success, message, booking = create_booking(
            user_id=user.id,
            vehicle_id=vehicle_id,
            location_id=location_id,
            slot_id=slot_id,
            start_time_str=start_time,
            duration_hours=duration
        )

        if success:
            flash(f"🎉 Booking Confirmed! Ref: #{booking.booking_reference}", 'success')
            return redirect(url_for('user.view_booking', booking_id=booking.id))
        else:
            flash(message, 'danger')
            return redirect(url_for('user.book_slot', location_id=location_id))

    # Fetch slots categorized by zone
    slots = ParkingSlot.query.filter_by(location_id=location_id).order_by(ParkingSlot.slot_number).all()
    now_str = datetime.now().strftime("%Y-%m-%dT%H:%M")

    return render_template(
        'booking.html',
        location=location,
        slots=slots,
        vehicles=vehicles,
        now_str=now_str
    )


@user_bp.route('/booking/<int:booking_id>')
@login_required
def view_booking(booking_id):
    user = get_current_user()
    booking = Booking.query.filter_by(id=booking_id, user_id=user.id).first_or_404()
    invoice = booking.invoice
    return render_template('booking_detail.html', booking=booking, invoice=invoice)


@user_bp.route('/booking/<int:booking_id>/cancel', methods=['POST'])
@login_required
def cancel_user_booking(booking_id):
    user = get_current_user()
    reason = request.form.get('cancellation_reason', 'Cancelled by user from dashboard')
    
    success, message = cancel_booking(
        booking_id=booking_id,
        cancelled_by='user',
        reason=reason,
        user_id=user.id
    )
    
    if success:
        flash("Your booking has been cancelled successfully.", "success")
    else:
        flash(message, "danger")
        
    return redirect(url_for('user.dashboard'))


@user_bp.route('/camera')
def user_camera():
    user = get_current_user()
    locations = ParkingLocation.query.filter_by(status='OPEN').all()
    return render_template('user_camera.html', user=user, locations=locations)


@user_bp.route('/my-vehicles', methods=['GET', 'POST'])
@login_required
def my_vehicles():
    user = get_current_user()
    if request.method == 'POST':
        vehicle_number = request.form.get('vehicle_number', '').strip().upper()
        vehicle_type = request.form.get('vehicle_type', 'Car')
        model = request.form.get('model', '').strip()
        nickname = request.form.get('nickname', '').strip()

        if vehicle_number:
            v = Vehicle(
                user_id=user.id,
                vehicle_number=vehicle_number,
                vehicle_type=vehicle_type,
                model=model,
                nickname=nickname
            )
            db.session.add(v)
            db.session.commit()
            flash('Vehicle added successfully!', 'success')
            
        return redirect(url_for('user.my_vehicles'))

    vehicles = Vehicle.query.filter_by(user_id=user.id).all()
    return render_template('user_vehicles.html', vehicles=vehicles)


@user_bp.route('/profile')
@login_required
def profile():
    user = get_current_user()
    return render_template('profile.html', user=user)
