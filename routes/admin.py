from decimal import Decimal
from flask import Blueprint, flash, redirect, render_template, request, url_for, Response
from flask_login import current_user, login_required
from extensions import db
from models import Product, StoreProduct, PricingRule, PriceHistory, InventoryTransaction, User, AuditLog, Sale, Order, Store, Business, Category
from services.pricing import suggested_price
from services.audit import audit
from services.export import export_business
import json

bp = Blueprint("admin", __name__)


def admin_required(permission=None):
    def decorator(fn):
        from functools import wraps
        @wraps(fn)
        @login_required
        def wrapped(*args, **kwargs):
            if current_user.role and current_user.role.name == "OWNER":
                return fn(*args, **kwargs)
            if permission and not current_user.has_permission(permission):
                return "Forbidden", 403
            return fn(*args, **kwargs)
        return wrapped
    return decorator


def admin_home():
    sales_total = db.session.query(db.func.coalesce(db.func.sum(Sale.total), 0)).filter_by(business_id=current_user.business_id).scalar()
    today = db.func.date(Sale.created_at) == db.func.current_date()
    today_sales = db.session.query(db.func.coalesce(db.func.sum(Sale.total), 0)).filter(Sale.business_id == current_user.business_id, today).scalar()
    orders = Order.query.filter_by(business_id=current_user.business_id).count()
    low_stock = (StoreProduct.query.filter(StoreProduct.stock_quantity <= StoreProduct.reorder_level)
                 .join(Product).join(Store).filter(Store.business_id == current_user.business_id).count())
    stores = Store.query.filter_by(business_id=current_user.business_id).order_by(Store.name).all()
    recent = (Sale.query.filter_by(business_id=current_user.business_id).order_by(Sale.created_at.desc()).limit(10).all())
    return render_template("admin/dashboard.html", sales_total=sales_total, today_sales=today_sales, orders=orders, low_stock=low_stock, stores=stores, recent=recent)


@bp.get("/fr%2")
@admin_required("reports.view")
def dashboard_obscured():
    return admin_home()


@bp.get("/fr%252")
@admin_required("reports.view")
def dashboard_obscured_encoded():
    return admin_home()


@bp.get("/admin")
@admin_required("reports.view")
def legacy_dashboard():
    return admin_home()


@bp.get("/admin/products")
@admin_required("products.view")
def products():
    items = (StoreProduct.query.join(Product).join(Store)
             .filter(Store.business_id == current_user.business_id)
             .order_by(Product.name).limit(500).all())
    return render_template("admin/products.html", items=items, stores=Store.query.filter_by(business_id=current_user.business_id).all())


@bp.post("/admin/products/<store_product_id>/price")
@admin_required("products.edit")
def update_price(store_product_id):
    item = db.session.get(StoreProduct, store_product_id)
    if not item or item.store.business_id != current_user.business_id:
        return "Not found", 404
    old = Decimal(item.selling_price or 0)
    new = Decimal(request.form.get("selling_price", "0"))
    if new <= 0:
        flash("Price must be greater than zero.", "error")
        return redirect(url_for("admin.products"))
    item.selling_price = new
    db.session.add(PriceHistory(store_product_id=item.id, old_price=old, new_price=new, reason=request.form.get("reason") or "Manual price update", source="MANUAL", changed_by=current_user.id))
    db.session.commit()
    audit("PRICE_CHANGED", "StoreProduct", item.id, old_values={"selling_price": str(old)}, new_values={"selling_price": str(new)})
    flash("Price updated.", "success")
    return redirect(url_for("admin.products"))


@bp.get("/admin/pricing")
@admin_required("products.view")
def pricing():
    rules = PricingRule.query.filter_by(business_id=current_user.business_id).order_by(PricingRule.priority).all()
    return render_template("admin/pricing.html", rules=rules)


@bp.post("/admin/products/<store_product_id>/auto-price")
@admin_required("products.edit")
def auto_price(store_product_id):
    item = db.session.get(StoreProduct, store_product_id)
    if not item or item.store.business_id != current_user.business_id:
        return "Not found", 404
    new = suggested_price(item, item.pricing_rule)
    old = Decimal(item.selling_price or 0)
    if new > 0 and new != old:
        item.selling_price = new
        db.session.add(PriceHistory(store_product_id=item.id, old_price=old, new_price=new, reason="Automatic pricing rule", source="PRICING_ENGINE", changed_by=current_user.id))
        db.session.commit()
        audit("PRICE_CHANGED", "StoreProduct", item.id, old_values={"selling_price": str(old)}, new_values={"selling_price": str(new), "source": "PRICING_ENGINE"})
    return redirect(url_for("admin.products"))


@bp.get("/admin/stores")
@admin_required("reports.view")
def stores():
    return render_template("admin/stores.html", stores=Store.query.filter_by(business_id=current_user.business_id).order_by(Store.name).all())


@bp.get("/admin/users")
@admin_required("users.manage")
def users():
    users = User.query.filter_by(business_id=current_user.business_id).order_by(User.name).all()
    return render_template("admin/users.html", users=users, stores=Store.query.filter_by(business_id=current_user.business_id).order_by(Store.name).all())


@bp.get("/admin/audit")
@admin_required("reports.view")
def audit_logs():
    logs = AuditLog.query.filter_by(business_id=current_user.business_id).order_by(AuditLog.created_at.desc()).limit(300).all()
    return render_template("admin/audit.html", logs=logs)


@bp.get("/admin/export.json")
@admin_required("backup.create")
def export_json():
    payload = export_business(current_user.business_id)
    return Response(json.dumps(payload, default=str), mimetype="application/json", headers={"Content-Disposition": "attachment; filename=real-mart-export.json"})
