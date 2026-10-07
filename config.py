import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'smartpark_super_secret_jwt_key_2026_prod')
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', f"sqlite:///{os.path.join(BASE_DIR, 'smartpark.db')}")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Upload directories
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
    INVOICE_FOLDER = os.path.join(UPLOAD_FOLDER, 'invoices')
    SNAPSHOT_FOLDER = os.path.join(UPLOAD_FOLDER, 'snapshots')
    
    # External APIs
    GOOGLE_MAPS_API_KEY = os.getenv('GOOGLE_MAPS_API_KEY', '')
    MAPBOX_ACCESS_TOKEN = os.getenv('MAPBOX_ACCESS_TOKEN', '')
    
    # CV settings
    YOLO_MODEL_PATH = os.getenv('YOLO_MODEL_PATH', 'yolov8n.pt')
    ANPR_CONFIDENCE_THRESHOLD = float(os.getenv('ANPR_CONFIDENCE_THRESHOLD', '0.4'))
    
    # Currency and default rate
    CURRENCY_SYMBOL = '₹'
    DEFAULT_HOURLY_RATE = 20.0
