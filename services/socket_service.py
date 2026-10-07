from flask_socketio import SocketIO, emit

socketio = SocketIO(cors_allowed_origins="*")

def init_socketio(app):
    socketio.init_app(app)

def broadcast_new_booking(booking_data):
    """
    Emit real-time notification to Admin and Users when a booking is created
    """
    socketio.emit('new_booking_alert', {
        'type': 'NEW_BOOKING',
        'title': '🔔 New Parking Booking',
        'message': f"Slot {booking_data['slot_number']} booked by {booking_data['user_name']}",
        'data': booking_data
    })
    socketio.emit('slot_updated', {
        'location_id': booking_data['location_id'],
        'slot_id': booking_data['slot_id'],
        'status': 'RESERVED'
    })

def broadcast_booking_cancelled(cancel_data):
    """
    Emit real-time notification when a booking is cancelled by user or admin
    """
    socketio.emit('booking_cancelled_alert', {
        'type': 'BOOKING_CANCELLED',
        'title': '⚠️ Booking Cancelled',
        'message': f"Booking #{cancel_data['booking_reference']} cancelled by {cancel_data['cancelled_by']}",
        'data': cancel_data
    })
    socketio.emit('slot_updated', {
        'location_id': cancel_data['location_id'],
        'slot_id': cancel_data['slot_id'],
        'status': 'FREE'
    })

def broadcast_anpr_event(anpr_data):
    """
    Emit real-time ANPR camera detection event to admin dashboard
    """
    socketio.emit('anpr_detection_alert', {
        'type': 'ANPR_DETECTION',
        'title': f"🚗 Plate Recognized: {anpr_data['detected_plate']}",
        'message': f"Action: {anpr_data['action_taken']} at {anpr_data['location_name']}",
        'data': anpr_data
    })
