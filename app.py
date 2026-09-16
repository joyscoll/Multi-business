import os
from datetime import datetime, timezone
from flask import Flask, jsonify, redirect, url_for
from config import Config
from extensions import db, migrate, login_manager, csrf
from models import User


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    os.makedirs(os.path.join(app.root_path, "instance"), exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)

    from routes.auth import bp as auth_bp
    from routes.shop import bp as shop_bp
    from routes.pos import bp as pos_bp
    from routes.admin import bp as admin_bp
    from routes.api import bp as api_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(shop_bp)
    app.register_blueprint(pos_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(api_bp)

    # Render services sometimes start with `gunicorn app:app` and skip
    # the explicit init_db.py command. Ensure a fresh database cannot
    # crash the public storefront with "no such table" errors.
    if os.getenv("AUTO_INIT_DB", "1") != "0":
        from bootstrap import bootstrap_database
        with app.app_context():
            bootstrap_database()

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, user_id)

    @app.context_processor
    def inject_globals():
        return {"business_name": app.config["BUSINESS_NAME"], "currency": app.config["CURRENCY"], "title": None}

    @app.get("/healthz")
    def healthz():
        return {"status": "ok", "service": "real-mart", "time": datetime.now(timezone.utc).isoformat()}

    @app.errorhandler(404)
    def not_found(_):
        return jsonify(error="not_found"), 404

    @app.get("/api")
    def api_root():
        return {"service": "REAL MART API", "version": "1.0.0", "status": "ok"}

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=app.config["FLASK_ENV"] != "production")
