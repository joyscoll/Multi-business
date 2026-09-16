from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from extensions import db
from models import User

bp = Blueprint("auth", __name__)


def _login(target):
    if current_user.is_authenticated:
        if target == "admin":
            return redirect("/fr%2")
        return redirect("/otcOmc")
    if request.method == "POST":
        identity = request.form.get("identity", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter((User.email == identity) | (User.username == identity)).first()
        if user and user.is_active and user.check_password(password):
            if target == "pos" and not user.has_permission("sales.create"):
                flash("This account is not assigned to a till.", "error")
            elif target == "admin" and not (user.role and user.role.name == "OWNER" or user.has_permission("reports.view")):
                flash("This account does not have control-centre access.", "error")
            else:
                login_user(user, remember=True)
                user.last_login_at = __import__('datetime').datetime.now(__import__('datetime').timezone.utc)
                db.session.commit()
                return redirect(request.args.get("next") or ("/fr%2" if target == "admin" else "/otcOmc"))
        else:
            flash("Invalid login details.", "error")
    return render_template("auth/login.html", target=target)


@bp.route("/otcOmc/login", methods=["GET", "POST"])
def pos_login():
    return _login("pos")


@bp.route("/fr%2/login", methods=["GET", "POST"])
def admin_login():
    return _login("admin")


@bp.route("/login", methods=["GET", "POST"])
def generic_login():
    # Compatibility only: do not advertise this route. It chooses the protected
    # area based on an explicit next parameter and otherwise returns to the shop.
    if request.method == "POST":
        return _login("admin" if request.args.get("area") == "admin" else "pos")
    return redirect("/")


@bp.post("/logout")
@login_required
def logout():
    logout_user()
    return redirect("/")
