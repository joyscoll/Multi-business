from decimal import Decimal, InvalidOperation
import json
from functools import wraps
from flask import Blueprint, flash, redirect, render_template, request, url_for, Response
from flask_login import current_user, login_required
from extensions import db
from models import (Product, StoreProduct, PricingRule, PriceHistory, InventoryTransaction, User,
                    AuditLog, Sale, SaleItem, Order, Store, Business, Category, SystemError,
                    Payment, Expense, Role, PaymentIntegration, SystemSetting, Permission)
from services.audit import audit
from services.export import export_business
from services.crypto import encrypt

bp = Blueprint("admin", __name__)
ADMIN_BASE = "/control"


def admin_required(permission=None):
    def decorator(fn):
        @wraps(fn)
        @login_required
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated or not current_user.role or current_user.role.name != "OWNER":
                return "Forbidden", 403
            if permission and not current_user.has_permission(permission):
                return "Forbidden", 403
            return fn(*args, **kwargs)
        return wrapped
    return decorator


def _dashboard():
    sales_total = db.session.query(db.func.coalesce(db.func.sum(Sale.total), 0)).filter_by(business_id=current_user.business_id, payment_status="PAID").scalar() or 0
    today_sales = db.session.query(db.func.coalesce(db.func.sum(Sale.total), 0)).filter(
        Sale.business_id == current_user.business_id, Sale.payment_status == "PAID",
        db.func.date(Sale.created_at) == db.func.current_date()
    ).scalar() or 0
    expenses_total = db.session.query(db.func.coalesce(db.func.sum(Expense.amount), 0)).filter_by(business_id=current_user.business_id).scalar() or 0
    cost_total = (db.session.query(db.func.coalesce(db.func.sum(SaleItem.line_total - (StoreProduct.cost_price * SaleItem.quantity)), 0))
                  .join(Sale, Sale.id == SaleItem.sale_id)
                  .join(StoreProduct, (StoreProduct.product_id == SaleItem.product_id) & (StoreProduct.store_id == Sale.store_id))
                  .filter(Sale.business_id == current_user.business_id, Sale.payment_status == "PAID").scalar() or 0)
    gross_profit = Decimal(str(sales_total)) - Decimal(str(cost_total))
    net_result = gross_profit - Decimal(str(expenses_total))
    orders = Order.query.filter_by(business_id=current_user.business_id).count()
    low_stock = (StoreProduct.query.filter(StoreProduct.stock_quantity <= StoreProduct.reorder_level)
                 .join(Product).join(Store).filter(Store.business_id == current_user.business_id).count())
    products_online = (StoreProduct.query.join(Store).filter(
        Store.business_id == current_user.business_id, StoreProduct.is_available.is_(True), StoreProduct.available_online.is_(True)
    ).count())
    stores = Store.query.filter_by(business_id=current_user.business_id).order_by(Store.name).all()
    recent = Sale.query.filter_by(business_id=current_user.business_id).order_by(Sale.created_at.desc()).limit(10).all()
    return render_template("admin/dashboard.html", sales_total=sales_total, today_sales=today_sales,
                           expenses_total=expenses_total, cost_total=cost_total, gross_profit=gross_profit,
                           net_result=net_result, orders=orders, low_stock=low_stock,
                           products_online=products_online, stores=stores, recent=recent)


@bp.get(f"{ADMIN_BASE}/products")
@admin_required("products.view")
def products():
    q = request.args.get("q", "").strip()
    query = StoreProduct.query.join(Product).join(Store).filter(Store.business_id == current_user.business_id)
    if q:
        like = f"%{q}%"
        query = query.filter((Product.name.ilike(like)) | (Product.brand.ilike(like)) | (Product.barcode.ilike(like)) | (Product.sku.ilike(like)))
    items = query.order_by(Product.name).limit(3000).all()
    return render_template("admin/products.html", items=items,
                           stores=Store.query.filter_by(business_id=current_user.business_id).order_by(Store.name).all(), q=q)


@bp.post(f"{ADMIN_BASE}/products/<store_product_id>/availability")
@admin_required("products.edit")
def toggle_product_availability(store_product_id):
    item = db.session.get(StoreProduct, store_product_id)
    if not item or item.store.business_id != current_user.business_id:
        return "Not found", 404
    item.available_online = request.form.get("online") == "1"
    item.available_pos = request.form.get("pos") == "1"
    item.is_available = request.form.get("enabled") == "1"
    db.session.commit()
    audit("PRODUCT_VISIBILITY_CHANGED", "StoreProduct", item.id,
          new_values={"online": item.available_online, "pos": item.available_pos, "enabled": item.is_available})
    flash("Product availability updated.", "success")
    return redirect(url_for("admin.products"))


@bp.post(f"{ADMIN_BASE}/products/<store_product_id>/price")
@admin_required("products.edit")
def update_price(store_product_id):
    item = db.session.get(StoreProduct, store_product_id)
    if not item or item.store.business_id != current_user.business_id:
        return "Not found", 404
    try:
        new_price = Decimal(request.form.get("selling_price", "0"))
    except InvalidOperation:
        flash("Invalid price.", "error"); return redirect(url_for("admin.products"))
    if new_price <= 0:
        flash("Price must be greater than zero.", "error"); return redirect(url_for("admin.products"))
    old = Decimal(str(item.selling_price))
    item.selling_price = new_price
    db.session.add(PriceHistory(store_product_id=item.id, old_price=old, new_price=new_price,
                                reason="Admin adjustment", changed_by=current_user.id))
    db.session.commit()
    audit("PRODUCT_PRICE_CHANGED", "StoreProduct", item.id, old_values={"price": str(old)}, new_values={"price": str(new_price)})
    flash("Price updated.", "success")
    return redirect(url_for("admin.products"))


@bp.post(f"{ADMIN_BASE}/products/create")
@admin_required("products.create")
def create_product():
    flash("The master catalogue is preloaded. Manage availability and prices here; add only through a controlled import later.", "error")
    return redirect(url_for("admin.products"))


@bp.get(f"{ADMIN_BASE}/pricing")
@admin_required("reports.view")
def pricing():
    rules = PricingRule.query.filter_by(business_id=current_user.business_id).order_by(PricingRule.priority).all()
    return render_template("admin/pricing.html", rules=rules)


@bp.get(f"{ADMIN_BASE}/stores")
@bp.post(f"{ADMIN_BASE}/stores")
@admin_required("products.edit")
def stores():
    business = db.session.get(Business, current_user.business_id)
    if request.method == "POST":
        name = request.form.get("name", "").strip(); code = request.form.get("code", "").strip().upper()
        if not name or not code:
            flash("Mart name and code are required.", "error")
        elif Store.query.filter_by(business_id=business.id, code=code).first():
            flash("That mart code already exists.", "error")
        else:
            db.session.add(Store(business_id=business.id, name=name, code=code,
                                 phone=request.form.get("phone", "").strip() or None,
                                 address=request.form.get("address", "").strip() or None, is_active=True))
            db.session.commit(); flash("Mart created.", "success")
    return render_template("admin/stores.html", stores=Store.query.filter_by(business_id=business.id).order_by(Store.name).all())


@bp.route(f"{ADMIN_BASE}/users", methods=["GET", "POST"])
@admin_required("users.manage")
def users():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        role_id = request.form.get("role_id", "").strip()
        store_id = request.form.get("store_id", "").strip() or None
        role = db.session.get(Role, role_id)
        if not name or not username or len(password) < 8 or not role:
            flash("Name, username, an 8+ character password and a valid role are required.", "error")
        elif User.query.filter(db.func.lower(User.username) == username.lower()).first():
            flash("That username is already in use.", "error")
        elif store_id and not Store.query.filter_by(id=store_id, business_id=current_user.business_id).first():
            flash("Select a valid mart.", "error")
        else:
            user = User(business_id=current_user.business_id, store_id=store_id, name=name,
                        username=username, role_id=role.id, is_active=True)
            user.set_password(password)
            db.session.add(user); db.session.commit()
            audit("USER_CREATED", "User", user.id, new_values={"username": username, "role": role.name, "store_id": store_id})
            flash(f"{name} can now sign in to the assigned system.", "success")
            return redirect(url_for("admin.users"))
    return render_template("admin/users.html", users=User.query.filter_by(business_id=current_user.business_id).order_by(User.name).all(),
                           roles=Role.query.order_by(Role.name).all(), stores=Store.query.filter_by(business_id=current_user.business_id).order_by(Store.name).all())


@bp.post(f"{ADMIN_BASE}/users/<user_id>/toggle")
@admin_required("users.manage")
def toggle_user(user_id):
    user = db.session.get(User, user_id)
    if not user or user.business_id != current_user.business_id:
        return "Not found", 404
    if user.id == current_user.id:
        flash("The master administrator cannot disable their own account.", "error")
        return redirect(url_for("admin.users"))
    user.is_active = not user.is_active
    db.session.commit()
    audit("USER_STATUS_CHANGED", "User", user.id, new_values={"active": user.is_active})
    flash(f"{user.name} is now {'active' if user.is_active else 'disabled'}.", "success")
    return redirect(url_for("admin.users"))


@bp.get(f"{ADMIN_BASE}/expenses")
@bp.post(f"{ADMIN_BASE}/expenses")
@admin_required("reports.view")
def expenses():
    if request.method == "POST":
        try: amount = Decimal(request.form.get("amount", "0"))
        except InvalidOperation: amount = Decimal("0")
        if amount <= 0 or not request.form.get("description", "").strip():
            flash("Description and a positive amount are required.", "error")
        else:
            db.session.add(Expense(business_id=current_user.business_id, store_id=request.form.get("store_id") or None,
                                    category=request.form.get("category", "General").strip() or "General",
                                    description=request.form.get("description", "").strip(), amount=amount,
                                    created_by=current_user.id))
            db.session.commit(); flash("Expense recorded.", "success")
    rows = Expense.query.filter_by(business_id=current_user.business_id).order_by(Expense.incurred_at.desc()).limit(500).all()
    total = db.session.query(db.func.coalesce(db.func.sum(Expense.amount), 0)).filter_by(business_id=current_user.business_id).scalar() or 0
    return render_template("admin/expenses.html", rows=rows, total=total,
                           stores=Store.query.filter_by(business_id=current_user.business_id).order_by(Store.name).all())


@bp.get(f"{ADMIN_BASE}/system-errors")
@admin_required("reports.view")
def system_errors():
    errors = SystemError.query.filter_by(business_id=current_user.business_id).order_by(SystemError.created_at.desc()).limit(500).all()
    return render_template("admin/system_errors.html", errors=errors)


@bp.get(f"{ADMIN_BASE}/security")
@admin_required("reports.view")
def security():
    users = User.query.filter_by(business_id=current_user.business_id).all()
    logs = AuditLog.query.filter_by(business_id=current_user.business_id).order_by(AuditLog.created_at.desc()).limit(100).all()
    return render_template("admin/security.html", users=users, logs=logs)


@bp.get(f"{ADMIN_BASE}/backups")
@admin_required("backup.create")
def backups():
    latest = AuditLog.query.filter_by(business_id=current_user.business_id, action="BUSINESS_EXPORT").order_by(AuditLog.created_at.desc()).limit(25).all()
    return render_template("admin/backups.html", latest=latest)


@bp.get(f"{ADMIN_BASE}/export.json")
@admin_required("backup.create")
def export_json():
    payload = export_business(current_user.business_id)
    audit("BUSINESS_EXPORT", "Business", current_user.business_id, new_values={"format": "json"})
    return Response(json.dumps(payload, default=str), mimetype="application/json",
                    headers={"Content-Disposition": "attachment; filename=real-mart-business-export.json"})


@bp.get(f"{ADMIN_BASE}/audit")
@admin_required("reports.view")
def audit_page():
    logs = AuditLog.query.filter_by(business_id=current_user.business_id).order_by(AuditLog.created_at.desc()).limit(500).all()
    return render_template("admin/audit.html", logs=logs)


@bp.get(f"{ADMIN_BASE}/settings")
@bp.post(f"{ADMIN_BASE}/settings")
@admin_required("reports.view")
def settings():
    business = db.session.get(Business, current_user.business_id)
    integration = PaymentIntegration.query.filter_by(business_id=business.id, provider="SAFARICOM").first()
    if request.method == "POST":
        business.name = request.form.get("business_name", business.name).strip() or business.name
        footer = request.form.get("footer_text", "All rights reserved · Denmart Merchants").strip()
        setting = SystemSetting.query.filter_by(business_id=business.id, key="footer_text").first()
        if not setting:
            setting = SystemSetting(business_id=business.id, key="footer_text", value=footer); db.session.add(setting)
        else: setting.value = footer
        if request.form.get("save_mpesa"):
            if not integration:
                integration = PaymentIntegration(business_id=business.id, provider="SAFARICOM")
                db.session.add(integration)
            integration.environment = request.form.get("environment", "sandbox")
            integration.callback_url = request.form.get("callback_url", "").strip() or None
            integration.is_active = request.form.get("mpesa_active") == "1"
            for field, form_name in [("consumer_key_encrypted","consumer_key"),("consumer_secret_encrypted","consumer_secret"),("shortcode_encrypted","shortcode"),("passkey_encrypted","passkey")]:
                value = request.form.get(form_name, "").strip()
                if value: setattr(integration, field, encrypt(value))
        db.session.commit(); flash("Settings saved.", "success")
    setting = SystemSetting.query.filter_by(business_id=business.id, key="footer_text").first()
    callback = integration.callback_url if integration else ""
    return render_template("admin/settings.html", business=business, integration=integration,
                           footer_text=setting.value if setting else "All rights reserved · Denmart Merchants",
                           callback_url=callback)
