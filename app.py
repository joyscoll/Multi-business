import os
from datetime import datetime, timezone
from flask import Flask, jsonify, redirect, url_for, request, render_template
from flask_login import current_user
from config import Config
from extensions import db, migrate, login_manager, csrf
from models import User, Business, SystemError


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

    @app.post("/pulse_receiver")
    def pulse_receiver():
        return ("", 204)

    @app.post("/pulse_receiver")
    def pulse_receiver():
        # Quiet compatibility endpoint for an external health pulse. It never
        # returns internal state or accepts operational commands.
        return ("", 204)

    @app.errorhandler(404)
    def not_found(_):
        return render_template("errors/not_found.html"), 404

    @app.errorhandler(Exception)
    def handle_unexpected_error(exc):
        # Never leak SQL/POS/provider details to public browsers. Record enough
        # evidence for the protected admin System Errors screen instead.
        try:
            business_id = None
            if current_user.is_authenticated:
                business_id = current_user.business_id
            else:
                business_id = db.session.query(Business.id).order_by(Business.created_at).first()
                business_id = business_id[0] if business_id else None
            err = SystemError(
                business_id=business_id,
                level="ERROR",
                code=exc.__class__.__name__,
                message=str(exc)[:1000] or "Unexpected application error",
                path=request.path[:500],
                method=request.method[:20],
                user_id=current_user.id if current_user.is_authenticated else None,
                ip_address=request.headers.get("X-Forwarded-For", request.remote_addr),
                user_agent=request.user_agent.string[:1000],
            )
            db.session.add(err)
            db.session.commit()
        except Exception:
            db.session.rollback()
        return render_template("errors/server_error.html"), 500

    @app.get("/api")
    def api_root():
        return jsonify(error="not_found"), 404

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=app.config["FLASK_ENV"] != "production")
