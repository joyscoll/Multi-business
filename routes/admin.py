from decimal import Decimal
from flask import Blueprint, flash, redirect, render_template, request, url_for, Response
from flask_login import current_user, login_required
from extensions import db
from models import Product, StoreProduct, PricingRule, PriceHistory, InventoryTransaction, User, AuditLog, Sale, SaleItem, Order, Store, Business, Category, SystemError, OfflineOperation, Payment, Expense, Role, PaymentIntegration, SystemSetting
from services.pricing import suggested_price
from services.audit import audit
from services.export import export_business
from services.crypto import encrypt
import json
import re

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
    sales_total = db.session.query(db.func.coalesce(db.func.sum(Sale.total), 0)).filter_by(business_id=current_user.business_id, payment_status="PAID").scalar() or 0
    today = db.func.date(Sale.created_at) == db.func.current_date()
    today_sales = db.session.query(db.func.coalesce(db.func.sum(Sale.total), 0)).filter(Sale.business_id == current_user.business_id, Sale.payment_status == "PAID", today).scalar() or 0
    expenses_total = db.session.query(db.func.coalesce(db.func.sum(Expense.amount), 0)).filter(Expense.business_id == current_user.business_id).scalar() or 0
    cost_total = (db.session.query(db.func.coalesce(db.func.sum(SaleItem.line_total - (StoreProduct.cost_price * SaleItem.quantity)), 0))
                  .join(Sale, Sale.id == SaleItem.sale_id)
                  .join(StoreProduct, (StoreProduct.product_id == SaleItem.product_id) & (StoreProduct.store_id == Sale.store_id))
                  .filter(Sale.business_id == current_user.business_id, Sale.payment_status == "PAID").scalar() or 0)
    gross_profit = Decimal(str(sales_total)) - Decimal(str(cost_total))
    net_result = gross_profit - Decimal(str(expenses_total))
    orders = Order.query.filter_by(business_id=current_user.business_id).count()
    low_stock = (StoreProduct.query.filter(StoreProduct.stock_quantity <= StoreProduct.reorder_level)
                 .join(Product).join(Store).filter(Store.business_id == current_user.business_id).count())
    products_online = (StoreProduct.query.join(Store).filter(Store.business_id == current_user.business_id, StoreProduct.is_available.is_(True), StoreProduct.available_online.is_(True)).count())
    stores = Store.query.filter_by(business_id=current_user.business_id).order_by(Store.name).all()
    recent = Sale.query.filter_by(business_id=current_user.business_id).order_by(Sale.created_at.desc()).limit(10).all()
    return render_template("admin/dashboard.html", sales_total=sales_total, today_sales=today_sales, expenses_total=expenses_total, cost_total=cost_total, gross_profit=gross_profit, net_result=net_result, orders=orders, low_stock=low_stock, products_online=products_online, stores=stores, recent=recent)


@bp.get("/admin")
@admin_required("reports.view")
def admin_root():
    return admin_home()


@bp.get("/fr%2")
@admin_required("reports.view")
def dashboard_obscured():
    return admin_home()


@bp.get("/fr%252")
@admin_required("reports.view")
def dashboard_obscured_encoded():
    return admin_home()



@bp.get("/admin/products")
@admin_required("products.view")
def products():
    items = (StoreProduct.query.join(Product).join(Store)
             .filter(Store.business_id == current_user.business_id)
             .order_by(Product.name).limit(1500).all())
    return render_template("admin/products.html", items=items, stores=Store.query.filter_by(business_id=current_user.business_id).order_by(Store.name).all())


@bp.post("/admin/products/<store_product_id>/availability")
@admin_required("products.edit")
def toggle_product_availability(store_product_id):
    item=db.session.get(StoreProduct, store_product_id)
    if not item or item.store.business_id != current_user.business_id:return "Not found",404
    item.available_online = request.form.get("online") == "1"
    item.available_pos = request.form.get("pos") == "1"
    item.is_available = request.form.get("enabled") == "1"
    db.session.commit()
    audit("PRODUCT_VISIBILITY_CHANGED","StoreProduct",item.id,new_values={"online":item.available_online,"pos":item.available_pos,"enabled":item.is_available})
    flash("Product availability updated.","success")
    return redirect(url_for("admin.products"))


@bp.post("/admin/products/create")
@admin_required("products.create")
def create_product():
    flash("The master supermarket catalogue is preloaded. Use availability controls to remove items you do not carry.", "error")
    return redirect(url_for("admin.products"))



