from functools import wraps
from flask import session, redirect, url_for, flash, request, jsonify
from models import User

def get_current_user():
    user_id = session.get('user_id')
    if not user_id:
        return None
    return User.query.get(user_id)

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = get_current_user()
        if not user:
            if request.path.startswith('/api/'):
                return jsonify({'success': False, 'message': 'Authentication required'}), 401
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('auth.user_login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = get_current_user()
        if not user or user.role != 'admin':
            if request.path.startswith('/api/'):
                return jsonify({'success': False, 'message': 'Administrator access required'}), 403
            flash('Access denied. Administrator privileges required.', 'danger')
            return redirect(url_for('auth.admin_login'))
        return f(*args, **kwargs)
    return decorated_function
