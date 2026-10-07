from datetime import datetime, timedelta
from database import db
from models import User, Vehicle, ParkingLocation, ParkingSlot, Camera, Blacklist, SystemSetting
from services.booking_service import create_booking

def seed_database():
    """
    Seeds initial default data if database is empty.
    Creates Admin, Users, Locations, Slots, Cameras, and Sample Bookings.
    """
    if User.query.first() is not None:
        return # Database already seeded

    print("[Seed Service] Seeding initial SmartPark data...")

    # 1. Admin Account
    admin = User(
        full_name="System Administrator",
        email="admin@smartpark.com",
        phone="+91 9876543210",
        role="admin",
        is_active=True
    )
    admin.set_password("admin123")
    db.session.add(admin)

    # 2. Demo Users
    user1 = User(
        full_name="Hasnain Shaikh",
        email="user@email.com",
        phone="+91 9123456789",
        role="user",
        is_active=True
    )
    user1.set_password("user123")
    db.session.add(user1)

    user2 = User(
        full_name="Rahul Patel",
        email="rahul@gmail.com",
        phone="+91 9988776655",
        role="user",
        is_active=True
    )
    user2.set_password("user123")
    db.session.add(user2)

    db.session.commit()

    # 3. User Vehicles
    veh1 = Vehicle(
        user_id=user1.id,
        vehicle_number="GJ09AB1234",
        vehicle_type="Car",
        model="Hyundai i20",
        nickname="My Car"
    )
    veh2 = Vehicle(
        user_id=user2.id,
        vehicle_number="MH02CD5678",
        vehicle_type="SUV",
        model="Tata Harrier",
        nickname="Office SUV"
    )
    db.session.add_all([veh1, veh2])
    db.session.commit()

    # 4. Parking Locations
    loc1 = ParkingLocation(
        name="SmartPark Central",
        address="Main Commercial Complex, Ring Road, Surat",
        latitude=21.1702,
        longitude=72.8311,
        description="Premium multi-level underground parking with 24/7 ANPR camera surveillance and EV charging.",
        total_slots=20,
        available_slots=20,
        hourly_rate=20.0,
        opening_time="00:00",
        closing_time="23:59",
        status="OPEN"
    )

    loc2 = ParkingLocation(
        name="SmartPark Tech Hub",
        address="Silicon Heights, University Road, Vesu, Surat",
        latitude=21.1458,
        longitude=72.7720,
        description="Smart corporate parking facility equipped with high-speed automated gate access.",
        total_slots=16,
        available_slots=16,
        hourly_rate=25.0,
        opening_time="06:00",
        closing_time="23:00",
        status="OPEN"
    )

    loc3 = ParkingLocation(
        name="SmartPark Airport Plaza",
        address="Dumas Road, Opposite Terminal 1, Surat",
        latitude=21.1160,
        longitude=72.7410,
        description="Long-term covered parking with direct shuttle service to departure terminal.",
        total_slots=12,
        available_slots=12,
        hourly_rate=30.0,
        opening_time="00:00",
        closing_time="23:59",
        status="OPEN"
    )

    db.session.add_all([loc1, loc2, loc3])
    db.session.commit()

    # 5. Create Parking Slots for each location
    locations = [loc1, loc2, loc3]
    for loc in locations:
        # Zone A slots
        num_zone_a = loc.total_slots // 2
        for i in range(1, num_zone_a + 1):
            slot = ParkingSlot(
                location_id=loc.id,
                slot_number=f"A-{i:02d}",
                zone="Zone A",
                status="FREE"
            )
            db.session.add(slot)
            
        # Zone B slots
        num_zone_b = loc.total_slots - num_zone_a
        for i in range(1, num_zone_b + 1):
            slot = ParkingSlot(
                location_id=loc.id,
                slot_number=f"B-{i:02d}",
                zone="Zone B",
                status="FREE"
            )
            db.session.add(slot)

    db.session.commit()

    # 6. Create Default Cameras
    cam1 = Camera(
        location_id=loc1.id,
        camera_name="Central Main Entry ANPR Cam",
        camera_type="ENTRY",
        stream_type="webcam",
        status="ONLINE"
    )
    cam2 = Camera(
        location_id=loc1.id,
        camera_name="Central Exit Gate Cam",
        camera_type="EXIT",
        stream_type="webcam",
        status="ONLINE"
    )
    db.session.add_all([cam1, cam2])

    # 7. Blacklist Entry
    bl = Blacklist(
        vehicle_number="GJ01XX9999",
        reason="Repeated non-payment violation and security risk.",
        added_by="System Administrator"
    )
    db.session.add(bl)
    db.session.commit()

    # 8. Create a sample active booking for demonstration
    sample_slot = ParkingSlot.query.filter_by(location_id=loc1.id, slot_number="A-05").first()
    if sample_slot:
        now_str = datetime.now().strftime("%Y-%m-%dT%H:%M")
        create_booking(
            user_id=user1.id,
            vehicle_id=veh1.id,
            location_id=loc1.id,
            slot_id=sample_slot.id,
            start_time_str=now_str,
            duration_hours=2.0
        )

    print("[Seed Service] Database successfully initialized and seeded!")
