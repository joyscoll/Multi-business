from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from extensions import db
from models import User

bp = Blueprint("auth", __name__)

@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("pos.dashboard"))
    if request.method == "POST":
        identity = request.form.get("identity", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter((User.email == identity) | (User.username == identity)).first()
        if user and user.is_active and user.check_password(password):
            login_user(user, remember=True)
            return redirect(request.args.get("next") or url_for("pos.dashboard"))
        flash("Invalid login details.", "error")
    return render_template("auth/login.html")

@bp.post("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
