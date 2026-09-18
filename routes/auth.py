from datetime import datetime, timezone
from flask import Blueprint, flash, redirect, render_template, request, session
from flask_login import current_user, login_required, login_user, logout_user
from extensions import db
from models import User

bp = Blueprint("auth", __name__)
ADMIN_PORTAL = "/control"


def _login(target):
    if current_user.is_authenticated and session.get("portal") == target:
        return redirect(ADMIN_PORTAL if target == "admin" else "/merchant/on")
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()
        if user and user.is_active and user.check_password(password):
            if target == "admin" and not (user.role and user.role.name == "OWNER"):
                flash("Control-centre access is reserved for the master administrator.", "error")
            elif target == "pos" and not user.has_permission("sales.create"):
                flash("This account is not enabled for merchant sales.", "error")
            else:
                if target == "pos" and not user.store_id:
                    from models import Store
                    fallback_store = (Store.query.filter_by(business_id=user.business_id, is_active=True)
                                      .order_by(Store.created_at).first())
                    if fallback_store:
                        user.store_id = fallback_store.id
                        db.session.flush()
                    else:
                        flash("No active mart is configured yet. Ask the administrator to add a mart.", "error")
                        return render_template("auth/login.html", target=target,
                                               pwa_manifest="/merchant/manifest.webmanifest")
                login_user(user, remember=False, fresh=True)
                session["portal"] = target
                user.last_login_at = datetime.now(timezone.utc)
                db.session.commit()
                return redirect(ADMIN_PORTAL if target == "admin" else "/merchant/on")
        else:
            flash("Invalid username or password.", "error")
    return render_template("auth/login.html", target=target,
                           pwa_manifest="/merchant/manifest.webmanifest" if target == "pos" else None)


@bp.route("/merchant", methods=["GET", "POST"])
def pos_login():
    if current_user.is_authenticated and session.get("portal") == "pos" and current_user.has_permission("sales.create"):
        return redirect("/merchant/on")
    return _login("pos")


@bp.route(ADMIN_PORTAL, methods=["GET", "POST"])
def hidden_admin_portal():
    if current_user.is_authenticated and session.get("portal") == "admin":
        from routes.admin import _dashboard
        return _dashboard()
    return _login("admin")


@bp.post("/logout")
@login_required
def logout():
    # Keep staff/admin users inside their own portal boundary after sign-out.
    # The next visit therefore lands on the correct authentication screen
    # instead of sending a merchant to the public storefront.
    portal = session.get("portal")
    logout_user()
    session.clear()
    return redirect("/control" if portal == "admin" else "/merchant" if portal == "pos" else "/")
