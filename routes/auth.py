from datetime import datetime, timezone
from flask import Blueprint, flash, redirect, render_template, request, session
from flask_login import current_user, login_required, login_user, logout_user
from extensions import db
from models import User

bp = Blueprint("auth", __name__)
ADMIN_PORTAL = "/fr%252"


def _login(target):
    if current_user.is_authenticated:
        return redirect(ADMIN_PORTAL if target == "admin" else "/mypp/on")
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()
        if user and user.is_active and user.check_password(password):
            if target == "admin" and not (user.role and user.role.name == "OWNER"):
                flash("Control-centre access is reserved for the master administrator.", "error")
            elif target == "pos" and not user.has_permission("sales.create"):
                flash("This account is not assigned to a till.", "error")
            else:
                login_user(user, remember=False, fresh=True)
                user.last_login_at = datetime.now(timezone.utc)
                db.session.commit()
                return redirect(request.args.get("next") or (ADMIN_PORTAL if target == "admin" else "/mypp/on"))
        else:
            flash("Invalid username or password.", "error")
    return render_template("auth/login.html", target=target,
                           pwa_manifest="/mypp/manifest.webmanifest" if target == "pos" else None)


@bp.route("/mypp", methods=["GET", "POST"])
def pos_login():
    if current_user.is_authenticated and current_user.has_permission("sales.create"):
        return redirect("/mypp/on")
    return _login("pos")


@bp.route("/212324/login", methods=["GET", "POST"])
def legacy_pos_login():
    return pos_login()


@bp.route(ADMIN_PORTAL, methods=["GET", "POST"])
@bp.route("/fr%2", methods=["GET", "POST"])
def hidden_admin_portal():
    if current_user.is_authenticated:
        from routes.admin import _dashboard
        return _dashboard()
    return _login("admin")


@bp.post("/logout")
@login_required
def logout():
    logout_user(); session.clear(); return redirect("/")
