import os
import base64
from flask import Blueprint, jsonify, request, send_file, session
from models import ParkingLocation, ParkingSlot, Booking, Invoice, ActivityLog, Vehicle, Camera
from services.cv_service import process_anpr_frame, process_anpr_plate_logic, calculate_parking_fee_for_plate
from services.auth_service import get_current_user
from config import Config

api_bp = Blueprint('api', __name__, url_prefix='/api')

@api_bp.route('/locations', methods=['GET'])
def get_locations():
    locations = ParkingLocation.query.all()
    return jsonify({
        'success': True,
        'data': [loc.to_dict() for loc in locations]
    })


@api_bp.route('/locations/<int:location_id>', methods=['GET'])
def get_location_details(location_id):
    loc = db.session.get(ParkingLocation, location_id) if hasattr(db.session, 'get') else ParkingLocation.query.get(location_id)
    if not loc:
        return jsonify({'success': False, 'message': 'Location not found'}), 404
        
    slots = ParkingSlot.query.filter_by(location_id=location_id).order_by(ParkingSlot.slot_number).all()
    return jsonify({
        'success': True,
        'data': {
            'location': loc.to_dict(),
            'slots': [s.to_dict() for s in slots]
        }
    })


@api_bp.route('/locations/<int:location_id>/slots', methods=['GET'])
def get_slots(location_id):
    slots = ParkingSlot.query.filter_by(location_id=location_id).order_by(ParkingSlot.slot_number).all()
    return jsonify({
        'success': True,
        'data': [s.to_dict() for s in slots]
    })


@api_bp.route('/cv/frame', methods=['POST'])
def process_frame():
    data = request.get_json() or {}
    location_id = data.get('location_id', 1)
    base64_frame = data.get('frame')
    camera_type = data.get('camera_type', 'ENTRY')
    manual_plate = data.get('manual_plate')

    if not base64_frame and not manual_plate:
        return jsonify({'success': False, 'message': 'No video frame or manual license plate provided'}), 400

    success, message, result = process_anpr_frame(location_id, base64_frame, camera_type, manual_plate)
    return jsonify({
        'success': success,
        'message': message,
        'data': result
    })


@api_bp.route('/cv/upload-scan', methods=['POST'])
def upload_scan_image():
    """
    Accepts uploaded license plate image file (multipart/form-data) or base64 frame.
    Runs ANPR OCR detection, calculates fee, and processes gate entry/exit.
    """
    location_id = request.form.get('location_id', 1, type=int)
    camera_type = request.form.get('camera_type', 'ENTRY')
    manual_plate = request.form.get('manual_plate', '')

    base64_frame = None

    if 'file' in request.files:
        file = request.files['file']
        if file and file.filename != '':
            img_bytes = file.read()
            base64_frame = base64.b64encode(img_bytes).decode('utf-8')

    if not base64_frame and not manual_plate:
        # Check json body fallback
        data = request.get_json(silent=True) or {}
        base64_frame = data.get('frame')
        manual_plate = data.get('manual_plate', '')
        location_id = data.get('location_id', location_id)
        camera_type = data.get('camera_type', camera_type)

    success, message, result = process_anpr_frame(location_id, base64_frame, camera_type, manual_plate)
    return jsonify({
        'success': success,
        'message': message,
        'data': result
    })


@api_bp.route('/cv/simulate-anpr', methods=['POST'])
def simulate_anpr():
    data = request.get_json() or {}
    location_id = data.get('location_id', 1)
    plate_number = data.get('plate_number', 'GJ09AB1234')
    camera_type = data.get('camera_type', 'ENTRY')

    success, message, result = process_anpr_plate_logic(location_id, plate_number, 0.95, camera_type)
    return jsonify({
        'success': success,
        'message': message,
        'data': result
    })


@api_bp.route('/cv/calculate-fee', methods=['POST'])
def calculate_fee():
    data = request.get_json() or {}
    location_id = data.get('location_id', 1)
    plate_number = data.get('plate_number', '').strip()
    duration_hours = data.get('duration_hours', 1.0)

    if not plate_number:
        return jsonify({'success': False, 'message': 'License plate number is required'}), 400

    success, message, result = calculate_parking_fee_for_plate(location_id, plate_number, duration_hours)
    return jsonify({
        'success': success,
        'message': message,
        'data': result
    })


@api_bp.route('/invoices/<int:invoice_id>/pdf', methods=['GET'])
def download_invoice_pdf(invoice_id):
    invoice = Invoice.query.get_or_404(invoice_id)
    
    # Path verification
    if invoice.pdf_path:
        filename = os.path.basename(invoice.pdf_path)
        full_path = os.path.join(Config.INVOICE_FOLDER, filename)
        if os.path.exists(full_path):
            return send_file(
                full_path,
                as_attachment=True,
                download_name=f"Invoice_{invoice.invoice_number}.pdf",
                mimetype='application/pdf'
            )
            
    # Regenerate if missing
    from services.invoice_service import generate_pdf_invoice
    booking = Booking.query.get(invoice.booking_id)
    if booking:
        pdf_path = generate_pdf_invoice(booking, invoice)
        return send_file(
            pdf_path,
            as_attachment=True,
            download_name=f"Invoice_{invoice.invoice_number}.pdf",
            mimetype='application/pdf'
        )

    return jsonify({'success': False, 'message': 'Invoice PDF file not found'}), 404


@api_bp.route('/admin/activity', methods=['GET'])
def get_activity_feed():
    activities = ActivityLog.query.order_by(ActivityLog.timestamp.desc()).limit(20).all()
    return jsonify({
        'success': True,
        'data': [a.to_dict() for a in activities]
    })
