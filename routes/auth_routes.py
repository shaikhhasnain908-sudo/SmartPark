from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from database import db
from models import User, Vehicle, ActivityLog
from services.auth_service import get_current_user

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def user_login():
    if session.get('user_id'):
        user = get_current_user()
        if user and user.role == 'admin':
            return redirect(url_for('admin.dashboard'))
        return redirect(url_for('user.dashboard'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        user = User.query.filter_by(email=email).first()
        if not user or not user.check_password(password):
            flash('Invalid email or password.', 'danger')
            return render_template('login.html', email=email)

        if not user.is_active:
            flash('Your account has been suspended by an administrator.', 'danger')
            return render_template('login.html', email=email)

        # Set session
        session['user_id'] = user.id
        session['user_name'] = user.full_name
        session['role'] = user.role

        # Log Activity
        log = ActivityLog(
            user_id=user.id,
            user_type=user.role,
            action='LOGIN',
            description=f"User {user.full_name} logged in.",
            ip_address=request.remote_addr
        )
        db.session.add(log)
        db.session.commit()

        flash(f'Welcome back, {user.full_name}!', 'success')
        
        if user.role == 'admin':
            return redirect(url_for('admin.dashboard'))
        return redirect(url_for('user.dashboard'))

    return render_template('login.html')


@auth_bp.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if session.get('user_id'):
        user = get_current_user()
        if user and user.role == 'admin':
            return redirect(url_for('admin.dashboard'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        user = User.query.filter_by(email=email).first()
        if not user or user.role != 'admin' or not user.check_password(password):
            flash('Unauthorized access attempt. Invalid administrator credentials.', 'danger')
            return render_template('admin/login.html', email=email)

        if not user.is_active:
            flash('Admin account is suspended.', 'danger')
            return render_template('admin/login.html', email=email)

        session['user_id'] = user.id
        session['user_name'] = user.full_name
        session['role'] = user.role

        log = ActivityLog(
            user_id=user.id,
            user_type='admin',
            action='ADMIN_LOGIN',
            description=f"Administrator {user.full_name} logged into Admin Console.",
            ip_address=request.remote_addr
        )
        db.session.add(log)
        db.session.commit()

        flash(f'Admin authentication successful. Welcome, {user.full_name}.', 'success')
        return redirect(url_for('admin.dashboard'))

    return render_template('admin/login.html')


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if session.get('user_id'):
        return redirect(url_for('user.dashboard'))

    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        email = request.form.get('email', '').strip().lower()
        phone = request.form.get('phone', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        vehicle_number = request.form.get('vehicle_number', '').strip().upper()
        vehicle_type = request.form.get('vehicle_type', 'Car')

        if password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return render_template('register.html', full_name=full_name, email=email, phone=phone, vehicle_number=vehicle_number)

        existing = User.query.filter_by(email=email).first()
        if existing:
            flash('An account with this email address already exists.', 'warning')
            return render_template('register.html', full_name=full_name, phone=phone, vehicle_number=vehicle_number)

        new_user = User(
            full_name=full_name,
            email=email,
            phone=phone,
            role='user',
            is_active=True
        )
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.flush()

        if vehicle_number:
            vehicle = Vehicle(
                user_id=new_user.id,
                vehicle_number=vehicle_number,
                vehicle_type=vehicle_type,
                model='Primary Vehicle',
                nickname='My Vehicle'
            )
            db.session.add(vehicle)

        log = ActivityLog(
            user_id=new_user.id,
            user_type='user',
            action='USER_REGISTER',
            description=f"New user registered: {full_name} ({email})",
            ip_address=request.remote_addr
        )
        db.session.add(log)
        db.session.commit()

        session['user_id'] = new_user.id
        session['user_name'] = new_user.full_name
        session['role'] = new_user.role

        flash('Account created successfully! Welcome to SmartPark.', 'success')
        return redirect(url_for('user.dashboard'))

    return render_template('register.html')


@auth_bp.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.user_login'))
