from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from database import db
from models import User, Vehicle, ParkingLocation, ParkingSlot, Booking, Invoice, Camera, ANPRLog, ActivityLog, Blacklist
from services.auth_service import admin_required, get_current_user
from services.booking_service import cancel_booking
from config import Config

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

@admin_bp.route('/dashboard')
@admin_required
def dashboard():
    admin_user = get_current_user()

    total_users = User.query.filter_by(role='user').count()
    total_locations = ParkingLocation.query.count()
    
    slots = ParkingSlot.query.all()
    total_slots = len(slots)
    available_slots = sum(1 for s in slots if s.status == 'FREE')
    occupied_slots = sum(1 for s in slots if s.status == 'OCCUPIED')
    reserved_slots = sum(1 for s in slots if s.status == 'RESERVED')

    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_bookings = Booking.query.filter(Booking.created_at >= today_start).count()
    active_bookings = Booking.query.filter(Booking.status.in_(['CONFIRMED', 'ACTIVE', 'RESERVED'])).count()
    cancelled_bookings = Booking.query.filter_by(status='CANCELLED').count()

    today_revenue = db.session.query(db.func.sum(Invoice.total_amount))\
        .filter(Invoice.created_at >= today_start, Invoice.invoice_status != 'CANCELLED').scalar() or 0.0

    recent_bookings = Booking.query.order_by(Booking.created_at.desc()).limit(8).all()
    recent_activities = ActivityLog.query.order_by(ActivityLog.timestamp.desc()).limit(10).all()
    anpr_logs = ANPRLog.query.order_by(ANPRLog.timestamp.desc()).limit(5).all()

    locations = ParkingLocation.query.all()
    cameras = Camera.query.all()

    return render_template(
        'admin/dashboard.html',
        admin=admin_user,
        total_users=total_users,
        total_locations=total_locations,
        total_slots=total_slots,
        available_slots=available_slots,
        occupied_slots=occupied_slots,
        reserved_slots=reserved_slots,
        today_bookings=today_bookings,
        active_bookings=active_bookings,
        cancelled_bookings=cancelled_bookings,
        today_revenue=today_revenue,
        recent_bookings=recent_bookings,
        recent_activities=recent_activities,
        anpr_logs=anpr_logs,
        locations=locations,
        cameras=cameras,
        google_maps_key=Config.GOOGLE_MAPS_API_KEY
    )


@admin_bp.route('/locations', methods=['GET', 'POST'])
@admin_required
def locations():
    if request.method == 'POST':
        action = request.form.get('action', 'add')
        
        if action == 'add':
            name = request.form.get('name', '').strip()
            address = request.form.get('address', '').strip()
            lat = float(request.form.get('latitude', 21.1702))
            lng = float(request.form.get('longitude', 72.8311))
            total_slots = int(request.form.get('total_slots', 10))
            rate = float(request.form.get('hourly_rate', 20.0))

            loc = ParkingLocation(
                name=name,
                address=address,
                latitude=lat,
                longitude=lng,
                total_slots=total_slots,
                available_slots=total_slots,
                hourly_rate=rate,
                status='OPEN'
            )
            db.session.add(loc)
            db.session.flush()

            # Auto-generate slots
            for i in range(1, total_slots + 1):
                zone = "Zone A" if i <= (total_slots // 2) else "Zone B"
                slot_num = f"{'A' if zone=='Zone A' else 'B'}-{i:02d}"
                slot = ParkingSlot(location_id=loc.id, slot_number=slot_num, zone=zone, status='FREE')
                db.session.add(slot)

            db.session.commit()
            flash(f"Parking location '{name}' created with {total_slots} slots!", "success")
            
        elif action == 'toggle_status':
            loc_id = request.form.get('location_id')
            loc = ParkingLocation.query.get(loc_id)
            if loc:
                loc.status = 'CLOSED' if loc.status == 'OPEN' else 'OPEN'
                db.session.commit()
                flash(f"Location '{loc.name}' status updated to {loc.status}.", "info")

        return redirect(url_for('admin.locations'))

    locations = ParkingLocation.query.order_by(ParkingLocation.id.desc()).all()
    return render_template('admin/locations.html', locations=locations, google_maps_key=Config.GOOGLE_MAPS_API_KEY)


@admin_bp.route('/bookings')
@admin_required
def bookings():
    status_filter = request.args.get('status', 'ALL')
    query = Booking.query.order_by(Booking.created_at.desc())

    if status_filter != 'ALL':
        query = query.filter_by(status=status_filter)

    all_bookings = query.all()
    return render_template('admin/bookings.html', bookings=all_bookings, current_filter=status_filter)


@admin_bp.route('/bookings/<int:booking_id>/cancel', methods=['POST'])
@admin_required
def admin_cancel_booking(booking_id):
    reason = request.form.get('cancellation_reason', 'Cancelled by administrator')
    admin_user = get_current_user()

    success, message = cancel_booking(
        booking_id=booking_id,
        cancelled_by='admin',
        reason=reason,
        user_id=admin_user.id
    )

    if success:
        flash(f"Booking #{booking_id} cancelled by Admin. User notified via WebSocket.", "success")
    else:
        flash(message, "danger")

    return redirect(url_for('admin.bookings'))


@admin_bp.route('/computer-vision')
@admin_required
def computer_vision():
    locations = ParkingLocation.query.all()
    cameras = Camera.query.all()
    recent_anpr = ANPRLog.query.order_by(ANPRLog.timestamp.desc()).limit(15).all()
    return render_template('admin/cv_monitor.html', locations=locations, cameras=cameras, recent_anpr=recent_anpr)


@admin_bp.route('/users')
@admin_required
def users():
    users_list = User.query.order_by(User.id.desc()).all()
    return render_template('admin/users.html', users=users_list)


@admin_bp.route('/users/<int:user_id>/toggle-status', methods=['POST'])
@admin_required
def toggle_user_status(user_id):
    u = User.query.get_or_404(user_id)
    if u.role == 'admin':
        flash("Cannot suspend another administrator.", "danger")
    else:
        u.is_active = not u.is_active
        db.session.commit()
        status_text = "Activated" if u.is_active else "Suspended"
        flash(f"User {u.full_name} has been {status_text}.", "info")
    return redirect(url_for('admin.users'))


@admin_bp.route('/activity')
@admin_required
def activity():
    activities = ActivityLog.query.order_by(ActivityLog.timestamp.desc()).limit(100).all()
    return render_template('admin/activity.html', activities=activities)


@admin_bp.route('/reports')
@admin_required
def reports():
    total_revenue = db.session.query(db.func.sum(Invoice.total_amount)).filter(Invoice.invoice_status != 'CANCELLED').scalar() or 0.0
    total_completed = Booking.query.filter_by(status='COMPLETED').count()
    total_cancelled = Booking.query.filter_by(status='CANCELLED').count()
    locations = ParkingLocation.query.all()
    return render_template('admin/reports.html', total_revenue=total_revenue, total_completed=total_completed, total_cancelled=total_cancelled, locations=locations)


@admin_bp.route('/settings', methods=['GET', 'POST'])
@admin_required
def settings():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add_blacklist':
            veh_num = request.form.get('vehicle_number', '').strip().upper()
            reason = request.form.get('reason', '').strip()
            if veh_num:
                existing = Blacklist.query.filter_by(vehicle_number=veh_num).first()
                if not existing:
                    bl = Blacklist(vehicle_number=veh_num, reason=reason, added_by='Administrator')
                    db.session.add(bl)
                    db.session.commit()
                    flash(f"Vehicle {veh_num} added to system blacklist.", "success")
                else:
                    flash(f"Vehicle {veh_num} is already blacklisted.", "warning")

        elif action == 'remove_blacklist':
            bl_id = request.form.get('blacklist_id')
            bl = Blacklist.query.get(bl_id)
            if bl:
                db.session.delete(bl)
                db.session.commit()
                flash("Vehicle removed from blacklist.", "info")

        return redirect(url_for('admin.settings'))

    blacklist_items = Blacklist.query.all()
    return render_template('admin/settings.html', blacklist_items=blacklist_items)
