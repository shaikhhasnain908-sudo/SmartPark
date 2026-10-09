from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text

db = SQLAlchemy()

def init_db(app):
    db.init_app(app)
    with app.app_context():
        db.create_all()
        # Safe migration for existing SQLite database
        try:
            db.session.execute(text("ALTER TABLE bookings ADD COLUMN entry_time DATETIME"))
            db.session.commit()
        except Exception:
            db.session.rollback()

        try:
            db.session.execute(text("ALTER TABLE bookings ADD COLUMN exit_time DATETIME"))
            db.session.commit()
        except Exception:
            db.session.rollback()
