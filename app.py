import os
from flask import Flask, render_template
from config import Config
from database import db, init_db
from services.socket_service import socketio, init_socketio
from services.seed_service import seed_database

# Import Blueprints
from routes.auth_routes import auth_bp
from routes.user_routes import user_bp
from routes.admin_routes import admin_bp
from routes.api_routes import api_bp

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Ensure upload directories exist
    os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(Config.INVOICE_FOLDER, exist_ok=True)
    os.makedirs(Config.SNAPSHOT_FOLDER, exist_ok=True)

    # Initialize Database & WebSockets
    init_db(app)
    init_socketio(app)

    # Register Blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(user_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(api_bp)

    # Context Processors & Error Handlers
    @app.errorhandler(404)
    def page_not_found(e):
        return render_template('base.html', content="<div class='container' style='padding-top:60px; text-align:center;'><h2>404 - Page Not Found</h2><p style='color:var(--text-muted);'>The requested page does not exist or has been moved.</p><a href='/' class='btn btn-primary' style='margin-top:16px;'>Return Home</a></div>"), 404

    @app.errorhandler(500)
    def internal_server_error(e):
        return render_template('base.html', content="<div class='container' style='padding-top:60px; text-align:center;'><h2>500 - Internal Server Error</h2><p style='color:var(--text-muted);'>An unexpected error occurred. Please try again later.</p><a href='/' class='btn btn-primary' style='margin-top:16px;'>Return Home</a></div>"), 500

    # Seed Database on startup
    with app.app_context():
        try:
            seed_database()
        except Exception as err:
            print(f"[App Startup Warning] Database seed error: {err}")

    return app

app = create_app()

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    print(f"============================================================")
    print(f" SMARTPARK Platform Server Starting on http://127.0.0.1:{port}")
    print(f" User Login: http://127.0.0.1:{port}/login")
    print(f" Admin Login: http://127.0.0.1:{port}/admin/login")
    print(f" Find Parking: http://127.0.0.1:{port}/find-parking")
    print(f"============================================================")
    socketio.run(app, host='0.0.0.0', port=port, debug=True, allow_unsafe_werkzeug=True)
