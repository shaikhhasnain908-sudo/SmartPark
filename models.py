from datetime import datetime
from database import db
from werkzeug.security import generate_password_hash, check_password_hash

class User(db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    phone = db.Column(db.String(20), nullable=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='user') # 'user' or 'admin'
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    vehicles = db.relationship('Vehicle', backref='owner', lazy=True, cascade="all, delete-orphan")
    bookings = db.relationship('Booking', backref='user', lazy=True)
    invoices = db.relationship('Invoice', backref='user', lazy=True)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
        
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
        
    def to_dict(self):
        return {
            'id': self.id,
            'full_name': self.full_name,
            'email': self.email,
            'phone': self.phone,
            'role': self.role,
            'is_active': self.is_active,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S')
        }


class Vehicle(db.Model):
    __tablename__ = 'vehicles'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    vehicle_number = db.Column(db.String(30), nullable=False, index=True)
    vehicle_type = db.Column(db.String(30), default='Car') # Car, Bike, SUV, Electric
    model = db.Column(db.String(50), nullable=True)
    nickname = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    bookings = db.relationship('Booking', backref='vehicle', lazy=True)
    
    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'vehicle_number': self.vehicle_number.upper(),
            'vehicle_type': self.vehicle_type,
            'model': self.model or '',
            'nickname': self.nickname or ''
        }


class ParkingLocation(db.Model):
    __tablename__ = 'parking_locations'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    address = db.Column(db.String(255), nullable=False)
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    description = db.Column(db.Text, nullable=True)
    total_slots = db.Column(db.Integer, default=20)
    available_slots = db.Column(db.Integer, default=20)
    hourly_rate = db.Column(db.Float, default=20.0)
    opening_time = db.Column(db.String(10), default='00:00')
    closing_time = db.Column(db.String(10), default='23:59')
    status = db.Column(db.String(20), default='OPEN') # OPEN, CLOSED, MAINTENANCE
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    slots = db.relationship('ParkingSlot', backref='location', lazy=True, cascade="all, delete-orphan")
    bookings = db.relationship('Booking', backref='location', lazy=True)
    cameras = db.relationship('Camera', backref='location', lazy=True)
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'address': self.address,
            'latitude': self.latitude,
            'longitude': self.longitude,
            'description': self.description,
            'total_slots': self.total_slots,
            'available_slots': self.available_slots,
            'occupied_slots': self.total_slots - self.available_slots,
            'hourly_rate': self.hourly_rate,
            'opening_time': self.opening_time,
            'closing_time': self.closing_time,
            'status': self.status
        }


class ParkingSlot(db.Model):
    __tablename__ = 'parking_slots'
    
    id = db.Column(db.Integer, primary_key=True)
    location_id = db.Column(db.Integer, db.ForeignKey('parking_locations.id'), nullable=False)
    slot_number = db.Column(db.String(20), nullable=False) # e.g. A-01
    zone = db.Column(db.String(30), default='Zone A')
    status = db.Column(db.String(20), default='FREE') # FREE, RESERVED, OCCUPIED, MAINTENANCE
    roi_coords = db.Column(db.Text, nullable=True) # JSON coordinates for camera slot bounding box
    current_vehicle_number = db.Column(db.String(30), nullable=True)
    current_booking_id = db.Column(db.Integer, nullable=True)
    
    def to_dict(self):
        return {
            'id': self.id,
            'location_id': self.location_id,
            'slot_number': self.slot_number,
            'zone': self.zone,
            'status': self.status,
            'current_vehicle_number': self.current_vehicle_number or '',
            'current_booking_id': self.current_booking_id
        }


class Booking(db.Model):
    __tablename__ = 'bookings'
    
    id = db.Column(db.Integer, primary_key=True)
    booking_reference = db.Column(db.String(30), unique=True, nullable=False, index=True) # SP-XXXXXX
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicles.id'), nullable=False)
    location_id = db.Column(db.Integer, db.ForeignKey('parking_locations.id'), nullable=False)
    slot_id = db.Column(db.Integer, db.ForeignKey('parking_slots.id'), nullable=False)
    
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=False)
    duration_hours = db.Column(db.Float, nullable=False, default=1.0)
    hourly_rate = db.Column(db.Float, nullable=False, default=20.0)
    total_amount = db.Column(db.Float, nullable=False, default=20.0)
    
    status = db.Column(db.String(20), default='CONFIRMED') # PENDING, CONFIRMED, ACTIVE, COMPLETED, CANCELLED, EXPIRED
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    cancelled_at = db.Column(db.DateTime, nullable=True)
    cancelled_by = db.Column(db.String(50), nullable=True) # 'user' or 'admin'
    cancellation_reason = db.Column(db.Text, nullable=True)
    
    slot = db.relationship('ParkingSlot', backref='bookings', lazy=True)
    invoice = db.relationship('Invoice', backref='booking', uselist=False, lazy=True)
    
    def to_dict(self):
        return {
            'id': self.id,
            'booking_reference': self.booking_reference,
            'user_id': self.user_id,
            'user_name': self.user.full_name if self.user else 'N/A',
            'user_email': self.user.email if self.user else 'N/A',
            'vehicle_number': self.vehicle.vehicle_number if self.vehicle else 'N/A',
            'location_id': self.location_id,
            'location_name': self.location.name if self.location else 'N/A',
            'slot_number': self.slot.slot_number if self.slot else 'N/A',
            'start_time': self.start_time.strftime('%Y-%m-%d %H:%M'),
            'end_time': self.end_time.strftime('%Y-%m-%d %H:%M'),
            'duration_hours': self.duration_hours,
            'total_amount': self.total_amount,
            'status': self.status,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'cancelled_at': self.cancelled_at.strftime('%Y-%m-%d %H:%M:%S') if self.cancelled_at else None,
            'cancelled_by': self.cancelled_by,
            'cancellation_reason': self.cancellation_reason
        }


class Invoice(db.Model):
    __tablename__ = 'invoices'
    
    id = db.Column(db.Integer, primary_key=True)
    invoice_number = db.Column(db.String(30), unique=True, nullable=False, index=True) # INV-SP-XXXXXX
    booking_id = db.Column(db.Integer, db.ForeignKey('bookings.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    subtotal = db.Column(db.Float, nullable=False)
    tax = db.Column(db.Float, default=0.0)
    discount = db.Column(db.Float, default=0.0)
    total_amount = db.Column(db.Float, nullable=False)
    
    payment_status = db.Column(db.String(20), default='PENDING') # PENDING, PAID, FAILED, REFUNDED
    invoice_status = db.Column(db.String(20), default='GENERATED') # GENERATED, CANCELLED, REFUNDED
    pdf_path = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'invoice_number': self.invoice_number,
            'booking_id': self.booking_id,
            'user_id': self.user_id,
            'subtotal': self.subtotal,
            'tax': self.tax,
            'total_amount': self.total_amount,
            'payment_status': self.payment_status,
            'invoice_status': self.invoice_status,
            'pdf_url': f"/api/invoices/{self.id}/pdf",
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S')
        }


class Camera(db.Model):
    __tablename__ = 'cameras'
    
    id = db.Column(db.Integer, primary_key=True)
    location_id = db.Column(db.Integer, db.ForeignKey('parking_locations.id'), nullable=False)
    camera_name = db.Column(db.String(100), nullable=False)
    camera_type = db.Column(db.String(30), default='ENTRY') # ENTRY, EXIT, OVERHEAD
    stream_type = db.Column(db.String(30), default='webcam') # webcam, ip, rtsp, video_file
    stream_url = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(20), default='ONLINE') # ONLINE, OFFLINE
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'location_id': self.location_id,
            'camera_name': self.camera_name,
            'camera_type': self.camera_type,
            'stream_type': self.stream_type,
            'stream_url': self.stream_url or '',
            'status': self.status
        }


class ANPRLog(db.Model):
    __tablename__ = 'anpr_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    camera_id = db.Column(db.Integer, db.ForeignKey('cameras.id'), nullable=True)
    location_id = db.Column(db.Integer, db.ForeignKey('parking_locations.id'), nullable=False)
    detected_plate = db.Column(db.String(30), nullable=False)
    confidence = db.Column(db.Float, default=0.0)
    snapshot_path = db.Column(db.String(255), nullable=True)
    matched_booking_id = db.Column(db.Integer, db.ForeignKey('bookings.id'), nullable=True)
    action_taken = db.Column(db.String(50), default='PLATE_DETECTED') # ENTRY_GRANTED, EXIT_COMPLETED, NO_BOOKING, BLACKLISTED
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'location_id': self.location_id,
            'detected_plate': self.detected_plate,
            'confidence': round(self.confidence, 2),
            'snapshot_path': self.snapshot_path,
            'action_taken': self.action_taken,
            'timestamp': self.timestamp.strftime('%Y-%m-%d %H:%M:%S')
        }


class ActivityLog(db.Model):
    __tablename__ = 'activity_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=True)
    user_type = db.Column(db.String(20), default='system') # 'user', 'admin', 'system'
    action = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    ip_address = db.Column(db.String(45), nullable=True)
    related_id = db.Column(db.Integer, nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'user_type': self.user_type,
            'action': self.action,
            'description': self.description,
            'timestamp': self.timestamp.strftime('%H:%M:%S | %Y-%m-%d')
        }


class Blacklist(db.Model):
    __tablename__ = 'blacklist'
    
    id = db.Column(db.Integer, primary_key=True)
    vehicle_number = db.Column(db.String(30), unique=True, nullable=False)
    reason = db.Column(db.Text, nullable=False)
    added_by = db.Column(db.String(100), default='Admin')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'vehicle_number': self.vehicle_number,
            'reason': self.reason,
            'added_by': self.added_by,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S')
        }


class SystemSetting(db.Model):
    __tablename__ = 'system_settings'
    
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text, nullable=False)
    description = db.Column(db.String(255), nullable=True)
