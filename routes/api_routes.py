import os
from flask import Blueprint, jsonify, request, send_file, session
from models import ParkingLocation, ParkingSlot, Booking, Invoice, ActivityLog, Vehicle, Camera
from services.cv_service import process_anpr_frame, process_anpr_plate_logic
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
    loc = ParkingLocation.query.get(location_id)
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

    if not base64_frame:
        return jsonify({'success': False, 'message': 'No frame provided'}), 400

    success, message, result = process_anpr_frame(location_id, base64_frame, camera_type)
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
