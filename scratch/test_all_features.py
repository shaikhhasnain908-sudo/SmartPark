import os
import sys
import unittest
from datetime import datetime, timedelta

# Add project root to sys.path
sys.path.insert(0, os.path.abspath('.'))

from app import create_app
from database import db
from models import User, Vehicle, ParkingLocation, ParkingSlot, Booking, Invoice, ANPRLog, ActivityLog, Blacklist
from services.booking_service import create_booking, cancel_booking
from services.cv_service import process_anpr_plate_logic

class SmartParkComprehensiveTest(unittest.TestCase):
    
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()

    def tearDown(self):
        self.app_context.pop()

    def test_01_public_routes(self):
        print("\n[TEST 1] Testing Public Web Routes...")
        
        res_home = self.client.get('/')
        self.assertEqual(res_home.status_code, 200, "Home page failed")
        
        res_map = self.client.get('/find-parking')
        self.assertEqual(res_map.status_code, 200, "Find parking map page failed")
        
        res_login = self.client.get('/login')
        self.assertEqual(res_login.status_code, 200, "User login page failed")

        res_register = self.client.get('/register')
        self.assertEqual(res_register.status_code, 200, "User register page failed")

        res_admin_login = self.client.get('/admin/login')
        self.assertEqual(res_admin_login.status_code, 200, "Admin login page failed")

        res_camera = self.client.get('/camera')
        self.assertEqual(res_camera.status_code, 200, "Camera scanner page failed")
        print(" -> All Public Routes Passed! (200 OK)")

    def test_02_user_authentication(self):
        print("\n[TEST 2] Testing User Authentication & Protection...")
        
        # Try accessing protected user dashboard without logging in
        res = self.client.get('/dashboard')
        self.assertEqual(res.status_code, 302, "Dashboard should redirect unauthenticated user")

        # Perform User Login
        res_login = self.client.post('/login', data={
            'email': 'user@email.com',
            'password': 'user123'
        }, follow_redirects=True)
        self.assertEqual(res_login.status_code, 200)
        self.assertIn(b'Welcome back', res_login.data, "Login welcome flash missing")
        print(" -> User Authentication & Session Login Passed!")

    def test_03_admin_authentication(self):
        print("\n[TEST 3] Testing Admin Authentication & Protection...")
        
        # User credentials must NOT access admin routes
        self.client.post('/login', data={'email': 'user@email.com', 'password': 'user123'})
        res_unauth_admin = self.client.get('/admin/dashboard')
        self.assertEqual(res_unauth_admin.status_code, 302, "Non-admin user must be redirected away from admin dashboard")

        # Perform Admin Login
        res_admin_login = self.client.post('/admin/login', data={
            'email': 'admin@smartpark.com',
            'password': 'admin123'
        }, follow_redirects=True)
        self.assertEqual(res_admin_login.status_code, 200)
        self.assertIn(b'Admin authentication successful', res_admin_login.data)
        print(" -> Admin Authentication & Authorization Passed!")

    def test_04_booking_concurrency_and_invoice(self):
        print("\n[TEST 4] Testing Slot Reservation & Invoice Generation...")
        
        user = User.query.filter_by(email='user@email.com').first()
        veh = Vehicle.query.filter_by(user_id=user.id).first()
        loc = ParkingLocation.query.first()
        slot = ParkingSlot.query.filter_by(location_id=loc.id, status='FREE').first()
        
        self.assertIsNotNone(slot, "Available slot not found for test")
        
        now_str = datetime.now().strftime("%Y-%m-%dT%H:%M")
        
        # Create Booking via service
        success, msg, booking = create_booking(
            user_id=user.id,
            vehicle_id=veh.id,
            location_id=loc.id,
            slot_id=slot.id,
            start_time_str=now_str,
            duration_hours=2.0
        )
        self.assertTrue(success, f"Booking creation failed: {msg}")
        self.assertIsNotNone(booking.invoice, "Invoice was not generated automatically")
        self.assertEqual(slot.status, 'RESERVED', "Slot status was not updated to RESERVED")
        
        # Verify Double Booking Prevention
        success2, msg2, booking2 = create_booking(
            user_id=user.id,
            vehicle_id=veh.id,
            location_id=loc.id,
            slot_id=slot.id,
            start_time_str=now_str,
            duration_hours=2.0
        )
        self.assertFalse(success2, "Double booking should be prevented!")
        print(" -> Booking Concurrency & Double-Booking Prevention Passed!")

    def test_05_anpr_gate_verification(self):
        print("\n[TEST 5] Testing ANPR Computer Vision & Gate Entrance...")
        
        loc = ParkingLocation.query.first()
        user = User.query.filter_by(email='user@email.com').first()
        veh = Vehicle.query.filter_by(user_id=user.id).first()
        
        # Simulate ANPR reading plate for entry
        success, msg, data = process_anpr_plate_logic(loc.id, veh.vehicle_number, 0.95, 'ENTRY')
        self.assertTrue(success)
        self.assertIn(data['action'], ['ENTRY_GRANTED', 'NO_BOOKING', 'PLATE_DETECTED'])
        
        # Simulate Blacklisted Plate
        bl_success, bl_msg, bl_data = process_anpr_plate_logic(loc.id, 'GJ01XX9999', 0.95, 'ENTRY')
        self.assertEqual(bl_data['action'], 'BLACKLISTED', "Blacklisted vehicle was not flagged!")
        print(" -> ANPR Gate Verification & Blacklist Filter Passed!")

    def test_06_admin_cancellation(self):
        print("\n[TEST 6] Testing Admin Booking Cancellation...")
        
        booking = Booking.query.filter(Booking.status.in_(['CONFIRMED', 'ACTIVE', 'RESERVED'])).first()
        if booking:
            admin = User.query.filter_by(role='admin').first()
            success, msg = cancel_booking(booking.id, cancelled_by='admin', reason='Test cancellation', user_id=admin.id)
            self.assertTrue(success, f"Admin cancellation failed: {msg}")
            
            reloaded_booking = Booking.query.get(booking.id)
            self.assertEqual(reloaded_booking.status, 'CANCELLED')
            reloaded_slot = ParkingSlot.query.get(booking.slot_id)
            self.assertEqual(reloaded_slot.status, 'FREE')
            print(" -> Admin Cancellation & Slot Release Passed!")

if __name__ == '__main__':
    unittest.main()
