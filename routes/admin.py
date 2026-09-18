from decimal import Decimal, InvalidOperation
from datetime import timedelta
import secrets
import json
import base64
import csv
import io
from io import BytesIO
from PIL import Image, ImageOps
from pathlib import Path
from functools import wraps
from flask import Blueprint, flash, redirect, render_template, request, url_for, Response, current_app, session, send_file, jsonify
from flask_login import current_user, login_required
from sqlalchemy import or_, case
from extensions import db
from models import (Product, StoreProduct, PricingRule, PriceHistory, InventoryTransaction, User,
                    AuditLog, Sale, SaleItem, Order, Store, Business, Category, SystemError,
                    Payment, Expense, Role, PaymentIntegration, SystemSetting, Permission, Customer, ProductAlias, ProductImage, OrderItem,
                    Supplier, PurchaseOrder, PurchaseOrderItem, PaymentGatewayEvent, LoyaltyAccount, LoyaltyTransaction, Shift, CashDrawerTransaction, now)
from services.audit import audit
from services.crypto import encrypt, decrypt
from services.backup_restore import export_database_json, create_sqlite_snapshot, restore_database_json, restore_sqlite_snapshot

bp = Blueprint("admin", __name__)
ADMIN_BASE = "/control"


def admin_required(permission=None):
    def decorator(fn):
        @wraps(fn)
        @login_required
        def wrapped(*args, **kwargs):
            if session.get("portal") != "admin" or not current_user.is_authenticated or not current_user.role or current_user.role.name != "OWNER":
                return "Forbidden", 403
            if permission and not current_user.has_permission(permission):
                return "Forbidden", 403
            return fn(*args, **kwargs)
        return wrapped
    return decorator



def _uploaded_product_image(file_storage, product_name="Product"):
    """Return a compact square WebP data URL so uploaded photos travel with backups."""
    if not file_storage or not getattr(file_storage, "filename", ""):
        return None
    if not (getattr(file_storage, "mimetype", "") or "").lower().startswith("image/"):
        raise ValueError("Choose a valid image file.")
    raw = file_storage.read()
    if not raw:
        raise ValueError("The image file is empty.")
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError("Product images must be 8 MB or smaller.")
    try:
        source = Image.open(BytesIO(raw))
        source = ImageOps.exif_transpose(source).convert("RGBA")
        source.thumbnail((760, 760), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (800, 800), "white")
        x = (800 - source.width) // 2
        y = (800 - source.height) // 2
        canvas.paste(source, (x, y), source)
        out = BytesIO()
        canvas.save(out, format="WEBP", quality=82, method=6, optimize=True)
        encoded = base64.b64encode(out.getvalue()).decode("ascii")
        return f"data:image/webp;base64,{encoded}"
    except Exception as exc:
        raise ValueError("The uploaded file is not a readable image.") from exc


def _set_product_image(product, data_url, source_type="ADMIN_UPLOAD"):
    if not data_url:
        return
    product.image_url = data_url
    # Keep uploaded data URLs only on Product so portable backups do not store
    # the same image twice. Remote image URLs may still be recorded as metadata.
    if not str(data_url).startswith("data:image/"):
        ProductImage.query.filter_by(product_id=product.id, is_primary=True).update({"is_primary": False})
        db.session.add(ProductImage(
            product_id=product.id, image_url=data_url, thumbnail_url=data_url,
            alt_text=product.name, source_type=source_type,
            license_info="Uploaded/verified by Denmart administrator.", sort_order=0, is_primary=True,
        ))


def _dashboard():
    business_id = current_user.business_id
    today = db.func.date(Sale.created_at) == db.func.current_date()
    today_order = db.func.date(Order.created_at) == db.func.current_date()
    today_expense = db.func.date(Expense.incurred_at) == db.func.current_date()
    today_inventory = db.func.date(InventoryTransaction.created_at) == db.func.current_date()

    pos_sales_today = db.session.query(
        db.func.coalesce(db.func.sum(Sale.total), 0)
    ).filter(
        Sale.business_id == business_id, Sale.payment_status == "PAID", today
    ).scalar() or 0
    online_sales_today = db.session.query(
        db.func.coalesce(db.func.sum(Order.total), 0)
    ).filter(
        Order.business_id == business_id, Order.payment_status == "PAID", today_order
    ).scalar() or 0
    today_sales = Decimal(str(pos_sales_today)) + Decimal(str(online_sales_today))

    sales_total = db.session.query(
        db.func.coalesce(db.func.sum(Sale.total), 0)
    ).filter_by(business_id=business_id, payment_status="PAID").scalar() or 0

    expenses_total = db.session.query(
        db.func.coalesce(db.func.sum(Expense.amount), 0)
    ).filter_by(business_id=business_id).scalar() or 0
    expenses_today = db.session.query(
        db.func.coalesce(db.func.sum(Expense.amount), 0)
    ).filter(Expense.business_id == business_id, today_expense).scalar() or 0

    # Use the cost captured on the inventory movement itself. This keeps profit
    # accurate after an admin changes a product's live cost price later.
    cogs_today_raw = db.session.query(
        db.func.coalesce(
            db.func.sum((-InventoryTransaction.quantity) * InventoryTransaction.unit_cost), 0
        )
    ).join(Store, Store.id == InventoryTransaction.store_id).filter(
        Store.business_id == business_id,
        InventoryTransaction.transaction_type == "SALE",
        InventoryTransaction.quantity < 0,
        today_inventory,
    ).scalar() or 0
    cogs_today = Decimal(str(cogs_today_raw))
    gross_profit_today = today_sales - cogs_today
    net_result_today = gross_profit_today - Decimal(str(expenses_today))

    cost_total_raw = db.session.query(
        db.func.coalesce(
            db.func.sum((-InventoryTransaction.quantity) * InventoryTransaction.unit_cost), 0
        )
    ).join(Store, Store.id == InventoryTransaction.store_id).filter(
        Store.business_id == business_id,
        InventoryTransaction.transaction_type == "SALE",
        InventoryTransaction.quantity < 0,
    ).scalar() or 0
    cost_total = Decimal(str(cost_total_raw))
    gross_profit = Decimal(str(sales_total)) - cost_total
    net_result = gross_profit - Decimal(str(expenses_total))

    pos_items_today = db.session.query(
        db.func.coalesce(db.func.sum(SaleItem.quantity), 0)
    ).join(Sale, Sale.id == SaleItem.sale_id).filter(
        Sale.business_id == business_id, Sale.payment_status == "PAID", today
    ).scalar() or 0
    online_items_today = db.session.query(
        db.func.coalesce(db.func.sum(OrderItem.quantity), 0)
    ).join(Order, Order.id == OrderItem.order_id).filter(
        Order.business_id == business_id, Order.payment_status == "PAID", today_order
    ).scalar() or 0
    items_today = Decimal(str(pos_items_today)) + Decimal(str(online_items_today))

    cash_today = db.session.query(
        db.func.coalesce(db.func.sum(CashDrawerTransaction.amount), 0)
    ).join(Shift, Shift.id == CashDrawerTransaction.shift_id).filter(
        Shift.store_id.in_(db.session.query(Store.id).filter(Store.business_id == business_id)),
        CashDrawerTransaction.transaction_type == "SALE_CASH",
        db.func.date(CashDrawerTransaction.created_at) == db.func.current_date(),
    ).scalar() or 0
    card_today = db.session.query(
        db.func.coalesce(db.func.sum(Payment.amount), 0)
    ).filter(
        Payment.business_id == business_id, Payment.status == "PAID",
        Payment.method == "CARD", db.func.date(Payment.created_at) == db.func.current_date()
    ).scalar() or 0
    mpesa_today = db.session.query(
        db.func.coalesce(db.func.sum(Payment.amount), 0)
    ).filter(
        Payment.business_id == business_id, Payment.status == "PAID",
        Payment.method.in_(["MPESA", "MPESA_TILL", "MPESA_GATEWAY", "MPESA_SMS"]),
        db.func.date(Payment.created_at) == db.func.current_date()
    ).scalar() or 0

    orders = Order.query.filter_by(business_id=business_id).count()
    pending_orders = Order.query.filter_by(
        business_id=business_id, fulfillment_status="PENDING"
    ).count()
    pending_payment_approvals = Order.query.filter_by(
        business_id=business_id, payment_status="PENDING_APPROVAL"
    ).count()
    low_stock = (StoreProduct.query.filter(StoreProduct.stock_quantity <= StoreProduct.reorder_level)
                 .join(Product).join(Store).filter(Store.business_id == business_id).count())
    products_online = (StoreProduct.query.join(Store).filter(
        Store.business_id == business_id,
        StoreProduct.is_available.is_(True),
        StoreProduct.available_online.is_(True)
    ).count())

    low_stock_items = (StoreProduct.query.join(Product).join(Store).filter(
        Store.business_id == business_id,
        StoreProduct.stock_quantity <= StoreProduct.reorder_level,
        StoreProduct.is_available.is_(True),
    ).order_by(
        (StoreProduct.stock_quantity - StoreProduct.reorder_level).asc(),
        Product.name.asc()
    ).limit(12).all())

    image_missing = Product.query.filter(
        (Product.image_url.is_(None)) | (Product.image_url == "")
    ).count()

    cashier_rows = db.session.query(
        User.name,
        Store.name,
        db.func.count(Sale.id),
        db.func.coalesce(db.func.sum(Sale.total), 0),
    ).join(Sale, Sale.cashier_id == User.id).join(Store, Store.id == Sale.store_id).filter(
        User.business_id == business_id,
        Sale.business_id == business_id,
        Sale.payment_status == "PAID",
        today,
    ).group_by(User.id, User.name, Store.name).order_by(
        db.func.sum(Sale.total).desc()
    ).limit(12).all()
    cashier_stats = [
        {"name": name, "store": store_name, "transactions": int(count), "sales": Decimal(str(total))}
        for name, store_name, count, total in cashier_rows
    ]

    stores = Store.query.filter_by(business_id=business_id).order_by(Store.name).all()
    recent = Sale.query.filter_by(business_id=business_id).order_by(Sale.created_at.desc()).limit(10).all()

    gateway_q = PaymentGatewayEvent.query.filter_by(business_id=business_id)
    gateway_today = db.func.date(PaymentGatewayEvent.received_at) == db.func.current_date()
    gateway_received_count = gateway_q.filter(
        PaymentGatewayEvent.status.in_(["MATCHED", "UNMATCHED"]), gateway_today
    ).count()
    gateway_received_total = gateway_q.with_entities(
        db.func.coalesce(db.func.sum(PaymentGatewayEvent.amount), 0)
    ).filter(PaymentGatewayEvent.status.in_(["MATCHED", "UNMATCHED"]), gateway_today).scalar() or 0
    gateway_matched_count = gateway_q.filter(
        PaymentGatewayEvent.status == "MATCHED", gateway_today
    ).count()
    gateway_matched_total = gateway_q.with_entities(
        db.func.coalesce(db.func.sum(PaymentGatewayEvent.amount), 0)
    ).filter(PaymentGatewayEvent.status == "MATCHED", gateway_today).scalar() or 0
    gateway_unmatched_count = gateway_q.filter(
        PaymentGatewayEvent.status == "UNMATCHED", gateway_today
    ).count()
    gateway_latest = gateway_q.order_by(PaymentGatewayEvent.received_at.desc()).first()

    loyalty_members = LoyaltyAccount.query.filter_by(business_id=business_id).count()
    loyalty_points = db.session.query(
        db.func.coalesce(db.func.sum(LoyaltyAccount.points_balance), 0)
    ).filter_by(business_id=business_id).scalar() or 0

    customers_count = Customer.query.filter_by(business_id=business_id, is_active=True).count()
    staff_count = User.query.filter_by(business_id=business_id, is_active=True).count()
    supplier_count = Supplier.query.filter_by(business_id=business_id, is_active=True).count()
    open_shift_count = Shift.query.join(Store, Store.id == Shift.store_id).filter(
        Store.business_id == business_id, Shift.status == "OPEN"
    ).count()
    unresolved_errors = SystemError.query.filter_by(business_id=business_id, resolved=False).count()
    reserved_units = db.session.query(
        db.func.coalesce(db.func.sum(StoreProduct.reserved_quantity), 0)
    ).join(Store, Store.id == StoreProduct.store_id).filter(Store.business_id == business_id).scalar() or 0
    inventory_cost_value = db.session.query(
        db.func.coalesce(db.func.sum(StoreProduct.stock_quantity * StoreProduct.cost_price), 0)
    ).join(Store, Store.id == StoreProduct.store_id).filter(Store.business_id == business_id).scalar() or 0
    inventory_retail_value = db.session.query(
        db.func.coalesce(db.func.sum(StoreProduct.stock_quantity * StoreProduct.selling_price), 0)
    ).join(Store, Store.id == StoreProduct.store_id).filter(Store.business_id == business_id).scalar() or 0

    purchase_open = PurchaseOrder.query.filter(
        PurchaseOrder.business_id == business_id, PurchaseOrder.status.in_(["DRAFT", "ORDERED", "PARTIALLY_RECEIVED"])
    ).count()

    return render_template(
        "admin/dashboard.html",
        sales_total=sales_total, today_sales=today_sales,
        pos_sales_today=pos_sales_today, online_sales_today=online_sales_today,
        expenses_total=expenses_total, expenses_today=expenses_today,
        cost_total=cost_total, cogs_today=cogs_today,
        gross_profit=gross_profit, gross_profit_today=gross_profit_today,
        net_result=net_result, net_result_today=net_result_today,
        today_items=items_today, cash_today=cash_today, card_today=card_today,
        mpesa_today=mpesa_today, orders=orders, pending_orders=pending_orders,
        pending_payment_approvals=pending_payment_approvals, low_stock=low_stock,
        low_stock_items=low_stock_items, products_online=products_online,
        image_missing=image_missing, cashier_stats=cashier_stats,
        stores=stores, recent=recent,
        gateway_received_count=gateway_received_count,
        gateway_received_total=gateway_received_total,
        gateway_matched_count=gateway_matched_count,
        gateway_matched_total=gateway_matched_total,
        gateway_unmatched_count=gateway_unmatched_count,
        gateway_latest=gateway_latest,
        loyalty_members=loyalty_members,
        loyalty_points=loyalty_points,
        customers_count=customers_count, staff_count=staff_count, supplier_count=supplier_count,
        open_shift_count=open_shift_count, unresolved_errors=unresolved_errors, reserved_units=reserved_units,
        inventory_cost_value=inventory_cost_value, inventory_retail_value=inventory_retail_value, purchase_open=purchase_open,
    )


ORDER_FULFILLMENT_STATES = [
    "PENDING", "PACKING", "READY_FOR_DISPATCH", "OUT_FOR_DELIVERY", "DELIVERED", "CANCELLED"
]


def _release_order_reservation(order):
    for line in OrderItem.query.filter_by(order_id=order.id).all():
        sp = StoreProduct.query.filter_by(store_id=order.store_id, product_id=line.product_id).first()
        if sp:
            sp.reserved_quantity = max(Decimal("0"), Decimal(sp.reserved_quantity or 0) - Decimal(line.quantity))


def _settle_order_payment(order, payment):
    from services.payments.settlement import settle_order_payment
    return settle_order_payment(order, payment, actor_id=current_user.id if current_user.is_authenticated else None)



def _gateway_setting(business_id, key):
    return SystemSetting.query.filter_by(business_id=business_id, key=key).first()


def _gateway_secret_for(business_id):
    setting = _gateway_setting(business_id, "payment_gateway_secret")
    if not setting or not setting.value:
        setting = setting or SystemSetting(business_id=business_id, key="payment_gateway_secret")
        if not setting.value:
            setting.value = secrets.token_urlsafe(32)
        db.session.add(setting)
        db.session.commit()
    return setting.value


def _gateway_url_for(business_id):
    return url_for("api.payment_gateway_sms", _external=True) + "?key=" + _gateway_secret_for(business_id)


@bp.get(f"{ADMIN_BASE}/payment-gateway")
@admin_required("payments.view")
def payment_gateway():
    business_id = current_user.business_id
    stores = Store.query.filter_by(business_id=business_id).order_by(Store.name).all()
    secret = _gateway_secret_for(business_id)
    url = url_for("api.payment_gateway_sms", _external=True) + "?key=" + secret

    sim1 = _gateway_setting(business_id, "payment_gateway_sim_0_store_id")
    sim2 = _gateway_setting(business_id, "payment_gateway_sim_1_store_id")
    routes = {
        0: sim1.value if sim1 else "",
        1: sim2.value if sim2 else "",
    }
    today = db.func.date(PaymentGatewayEvent.received_at) == db.func.current_date()
    events = (PaymentGatewayEvent.query.filter_by(business_id=business_id)
              .order_by(PaymentGatewayEvent.received_at.desc()).limit(40).all())
    received_total = db.session.query(db.func.coalesce(db.func.sum(PaymentGatewayEvent.amount), 0)).filter(
        PaymentGatewayEvent.business_id == business_id, PaymentGatewayEvent.status.in_(["MATCHED", "UNMATCHED"]), today
    ).scalar() or 0
    received_count = PaymentGatewayEvent.query.filter(
        PaymentGatewayEvent.business_id == business_id, PaymentGatewayEvent.status.in_(["MATCHED", "UNMATCHED"]), today
    ).count()
    matched_total = db.session.query(db.func.coalesce(db.func.sum(PaymentGatewayEvent.amount), 0)).filter(
        PaymentGatewayEvent.business_id == business_id, PaymentGatewayEvent.status == "MATCHED", today
    ).scalar() or 0
    matched_count = PaymentGatewayEvent.query.filter(
        PaymentGatewayEvent.business_id == business_id, PaymentGatewayEvent.status == "MATCHED", today
    ).count()
    unmatched_total = db.session.query(db.func.coalesce(db.func.sum(PaymentGatewayEvent.amount), 0)).filter(
        PaymentGatewayEvent.business_id == business_id, PaymentGatewayEvent.status == "UNMATCHED", today
    ).scalar() or 0
    unmatched_count = PaymentGatewayEvent.query.filter(
        PaymentGatewayEvent.business_id == business_id, PaymentGatewayEvent.status == "UNMATCHED", today
    ).count()
    return render_template(
        "admin/payment_gateway.html",
        stores=stores, routes=routes, gateway_url=url,
        events=events, received_total=received_total, received_count=received_count,
        matched_total=matched_total, matched_count=matched_count,
        unmatched_total=unmatched_total, unmatched_count=unmatched_count,
    )


@bp.post(f"{ADMIN_BASE}/payment-gateway/routing")
@admin_required("payments.view")
def save_gateway_routing():
    business_id = current_user.business_id
    stores = {s.id: s for s in Store.query.filter_by(business_id=business_id).all()}
    for slot in (0, 1):
        raw = (request.form.get(f"sim_{slot}_store_id") or "").strip()
        setting = _gateway_setting(business_id, f"payment_gateway_sim_{slot}_store_id")
        if raw and raw not in stores:
            flash(f"SIM {slot + 1} mart selection is invalid.", "error")
            return redirect(url_for("admin.payment_gateway"))
        if raw:
            if not setting:
                setting = SystemSetting(business_id=business_id, key=f"payment_gateway_sim_{slot}_store_id")
                db.session.add(setting)
            setting.value = raw
        elif setting:
            db.session.delete(setting)
    db.session.commit()
    flash("Payment gateway SIM routing saved.", "success")
    return redirect(url_for("admin.payment_gateway"))


@bp.post(f"{ADMIN_BASE}/payment-gateway/rotate")
@admin_required("payments.view")
def rotate_gateway_key():
    business_id = current_user.business_id
    setting = _gateway_setting(business_id, "payment_gateway_secret")
    if not setting:
        setting = SystemSetting(business_id=business_id, key="payment_gateway_secret")
        db.session.add(setting)
    setting.value = secrets.token_urlsafe(32)
    db.session.commit()
    audit("PAYMENT_GATEWAY_KEY_ROTATED", "Business", business_id)
    flash("Gateway link rotated. Update the Android gateway with the new link.", "success")
    return redirect(url_for("admin.payment_gateway"))


@bp.get(f"{ADMIN_BASE}/api/payment-gateway/monitor")
@admin_required("payments.view")
def payment_gateway_monitor():
    # Keep this endpoint deliberately defensive: the dashboard must continue
    # working even when a legacy gateway row has incomplete optional fields.
    business_id = current_user.business_id
    from datetime import datetime, timezone
    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    q = PaymentGatewayEvent.query.filter_by(business_id=business_id)
    events = q.order_by(PaymentGatewayEvent.received_at.desc()).limit(30).all()
    received_q = q.filter(PaymentGatewayEvent.status.in_(["MATCHED", "UNMATCHED"]), PaymentGatewayEvent.received_at >= start)
    matched_q = q.filter(PaymentGatewayEvent.status == "MATCHED", PaymentGatewayEvent.received_at >= start)
    unmatched_q = q.filter(PaymentGatewayEvent.status == "UNMATCHED", PaymentGatewayEvent.received_at >= start)
    stores = Store.query.filter_by(business_id=business_id).order_by(Store.name).all()

    def money(v):
        return str(v if v is not None else 0)

    store_totals = []
    for store in stores:
        scoped = received_q.filter(PaymentGatewayEvent.store_id == store.id)
        total = scoped.with_entities(db.func.coalesce(db.func.sum(PaymentGatewayEvent.amount), 0)).scalar() or 0
        store_totals.append({"id": store.id, "name": store.name, "total": money(total), "count": scoped.count()})

    payload_events = []
    for e in events:
        try:
            received_at = e.received_at.isoformat() if e.received_at else None
        except Exception:
            received_at = None
        try:
            sim = int(e.sim_slot or 0) + 1
        except Exception:
            sim = 1
        store_name = "Unassigned"
        try:
            if e.store and e.store.business_id == business_id:
                store_name = e.store.name
        except Exception:
            pass
        payload_events.append({
            "id": e.id, "time": received_at, "sim": sim, "store": store_name,
            "amount": money(e.amount), "customer": e.customer or "M-PESA customer",
            "transaction": e.transaction_id or "—", "status": e.status or "UNMATCHED",
        })

    return jsonify(
        ok=True,
        received_total=money(received_q.with_entities(db.func.coalesce(db.func.sum(PaymentGatewayEvent.amount), 0)).scalar()),
        received_count=received_q.count(),
        matched_total=money(matched_q.with_entities(db.func.coalesce(db.func.sum(PaymentGatewayEvent.amount), 0)).scalar()),
        matched_count=matched_q.count(),
        unmatched_total=money(unmatched_q.with_entities(db.func.coalesce(db.func.sum(PaymentGatewayEvent.amount), 0)).scalar()),
        unmatched_count=unmatched_q.count(),
        last_received=(events[0].received_at.isoformat() if events and events[0].received_at else None),
        stores=store_totals,
        events=payload_events,
    )


@bp.get(f"{ADMIN_BASE}/daily-report")
@admin_required("reports.view")
def daily_report():
    business_id = current_user.business_id
    today_sale = db.func.date(Sale.created_at) == db.func.current_date()
    today_order = db.func.date(Order.created_at) == db.func.current_date()
    today_expense = db.func.date(Expense.incurred_at) == db.func.current_date()
    today_inventory = db.func.date(InventoryTransaction.created_at) == db.func.current_date()

    pos_sales = db.session.query(db.func.coalesce(db.func.sum(Sale.total), 0)).filter(
        Sale.business_id == business_id, Sale.payment_status == "PAID", today_sale
    ).scalar() or 0
    online_sales = db.session.query(db.func.coalesce(db.func.sum(Order.total), 0)).filter(
        Order.business_id == business_id, Order.payment_status == "PAID", today_order
    ).scalar() or 0
    cash = db.session.query(db.func.coalesce(db.func.sum(CashDrawerTransaction.amount), 0)).join(
        Shift, Shift.id == CashDrawerTransaction.shift_id
    ).join(Store, Store.id == Shift.store_id).filter(
        Store.business_id == business_id,
        CashDrawerTransaction.transaction_type == "SALE_CASH",
        db.func.date(CashDrawerTransaction.created_at) == db.func.current_date(),
    ).scalar() or 0
    mpesa = db.session.query(db.func.coalesce(db.func.sum(Payment.amount), 0)).filter(
        Payment.business_id == business_id, Payment.status == "PAID",
        Payment.method.in_(["MPESA", "MPESA_TILL", "MPESA_GATEWAY", "MPESA_SMS"]),
        db.func.date(Payment.created_at) == db.func.current_date(),
    ).scalar() or 0
    card = db.session.query(db.func.coalesce(db.func.sum(Payment.amount), 0)).filter(
        Payment.business_id == business_id, Payment.status == "PAID", Payment.method == "CARD",
        db.func.date(Payment.created_at) == db.func.current_date(),
    ).scalar() or 0
    expenses = db.session.query(db.func.coalesce(db.func.sum(Expense.amount), 0)).filter(
        Expense.business_id == business_id, today_expense
    ).scalar() or 0
    cogs = db.session.query(db.func.coalesce(
        db.func.sum((-InventoryTransaction.quantity) * InventoryTransaction.unit_cost), 0
    )).join(Store, Store.id == InventoryTransaction.store_id).filter(
        Store.business_id == business_id, InventoryTransaction.transaction_type == "SALE",
        InventoryTransaction.quantity < 0, today_inventory
    ).scalar() or 0
    items = db.session.query(db.func.coalesce(db.func.sum(SaleItem.quantity), 0)).join(Sale, Sale.id == SaleItem.sale_id).filter(
        Sale.business_id == business_id, Sale.payment_status == "PAID", today_sale
    ).scalar() or 0
    online_items = db.session.query(db.func.coalesce(db.func.sum(OrderItem.quantity), 0)).join(Order, Order.id == OrderItem.order_id).filter(
        Order.business_id == business_id, Order.payment_status == "PAID", today_order
    ).scalar() or 0
    total_sales = Decimal(str(pos_sales)) + Decimal(str(online_sales))
    gross_profit = total_sales - Decimal(str(cogs))
    net = gross_profit - Decimal(str(expenses))
    return render_template("admin/daily_report.html",
                           business_name=current_user.business.name if current_user.business else "Denmart",
                           pos_sales=pos_sales, online_sales=online_sales, total_sales=total_sales,
                           cash=cash, mpesa=mpesa, card=card, expenses=expenses, cogs=cogs,
                           gross_profit=gross_profit, net_result=net,
                           items=Decimal(str(items)) + Decimal(str(online_items)), report_date=now())


@bp.get(f"{ADMIN_BASE}/orders")
@admin_required("sales.view")
def orders():
    status_filter = request.args.get("status", "").strip().upper()
    payment_filter = request.args.get("payment", "").strip().upper()
    query = Order.query.filter_by(business_id=current_user.business_id)
    if status_filter in ORDER_FULFILLMENT_STATES:
        query = query.filter_by(fulfillment_status=status_filter)
    if payment_filter in {"UNPAID", "PENDING_APPROVAL", "PARTIALLY_PAID", "PAID", "FAILED"}:
        query = query.filter_by(payment_status=payment_filter)
    rows = query.order_by(Order.created_at.desc()).limit(250).all()
    order_ids = [o.id for o in rows]
    payments = []
    if order_ids:
        payments = (Payment.query.filter(Payment.order_id.in_(order_ids))
                    .order_by(Payment.created_at.desc()).all())
    latest_payment = {}
    for payment in payments:
        latest_payment.setdefault(payment.order_id, payment)
    customer_ids = [o.customer_id for o in rows if o.customer_id]
    customers = {c.id: c for c in Customer.query.filter(Customer.id.in_(customer_ids)).all()} if customer_ids else {}
    return render_template("admin/orders.html", orders=rows, customers=customers,
                           latest_payment=latest_payment, states=ORDER_FULFILLMENT_STATES,
                           status_filter=status_filter, payment_filter=payment_filter)


@bp.post(f"{ADMIN_BASE}/orders/<order_id>/payment/approve")
@admin_required("payments.view")
def approve_order_payment(order_id):
    order = db.session.get(Order, order_id)
    payment = (Payment.query.filter_by(order_id=order_id, method="MPESA_TILL")
               .order_by(Payment.created_at.desc()).first())
    if not order or order.business_id != current_user.business_id or not payment:
        flash("Order or pending Till payment was not found.", "error")
        return redirect(url_for("admin.orders"))
    if payment.status != "PENDING_APPROVAL":
        flash("That payment is no longer awaiting approval.", "error")
        return redirect(url_for("admin.orders"))
    if not _settle_order_payment(order, payment):
        db.session.rollback()
        flash("Payment could not be approved. Check the transaction reference and reserved stock.", "error")
        return redirect(url_for("admin.orders"))
    db.session.commit()
    audit("ORDER_PAYMENT_APPROVED", "Order", order.id, new_values={"payment_id": payment.id, "reference": payment.provider_transaction_id})
    flash(f"{order.order_number} payment approved.", "success")
    return redirect(url_for("admin.orders"))


@bp.post(f"{ADMIN_BASE}/orders/<order_id>/payment/reject")
@admin_required("payments.view")
def reject_order_payment(order_id):
    order = db.session.get(Order, order_id)
    payment = (Payment.query.filter_by(order_id=order_id, method="MPESA_TILL")
               .order_by(Payment.created_at.desc()).first())
    if not order or order.business_id != current_user.business_id or not payment:
        flash("Order or pending Till payment was not found.", "error")
        return redirect(url_for("admin.orders"))
    if payment.status != "PENDING_APPROVAL":
        flash("That payment is no longer awaiting approval.", "error")
        return redirect(url_for("admin.orders"))
    reason = request.form.get("reason", "Payment reference could not be verified.").strip()[:500]
    payment.status = "FAILED"
    payment.failure_message = reason or "Payment reference could not be verified."
    order.payment_status = "FAILED"
    order.status = "PAYMENT_FAILED"
    _release_order_reservation(order)
    db.session.commit()
    audit("ORDER_PAYMENT_REJECTED", "Order", order.id, new_values={"payment_id": payment.id, "reason": payment.failure_message})
    flash(f"{order.order_number} payment rejected; stock reservation released.", "success")
    return redirect(url_for("admin.orders"))


@bp.post(f"{ADMIN_BASE}/orders/<order_id>/fulfillment")
@admin_required("sales.view")
def update_order_fulfillment(order_id):
    order = db.session.get(Order, order_id)
    new_state = request.form.get("fulfillment_status", "").strip().upper()
    if not order or order.business_id != current_user.business_id or new_state not in ORDER_FULFILLMENT_STATES:
        flash("Invalid order status update.", "error")
        return redirect(url_for("admin.orders"))
    if new_state == "CANCELLED" and order.payment_status == "PAID":
        flash("Paid orders cannot be cancelled here because refunds are not part of this workflow.", "error")
        return redirect(url_for("admin.orders"))
    if new_state not in {"PENDING", "CANCELLED"} and order.payment_status != "PAID":
        flash("Only paid orders can be packed or delivered.", "error")
        return redirect(url_for("admin.orders"))
    old = order.fulfillment_status
    order.fulfillment_status = new_state
    if new_state == "CANCELLED":
        if order.payment_status != "PAID":
            _release_order_reservation(order)
        order.status = "CANCELLED"
    elif new_state == "DELIVERED":
        order.status = "COMPLETED"
    elif order.payment_status == "PAID":
        order.status = "CONFIRMED"
    db.session.commit()
    audit("ORDER_FULFILLMENT_UPDATED", "Order", order.id, new_values={"from": old, "to": new_state})
    flash(f"{order.order_number} marked {new_state.replace('_', ' ').title()}.", "success")
    return redirect(url_for("admin.orders"))


@bp.get(f"{ADMIN_BASE}/products")
@admin_required("products.view")
def products():
    q = request.args.get("q", "").strip()
    store_id = request.args.get("store_id", "").strip()
    category_id = request.args.get("category_id", "").strip()
    query = StoreProduct.query.join(Product).join(Store).filter(Store.business_id == current_user.business_id)
    if store_id:
        query = query.filter(StoreProduct.store_id == store_id)
    if category_id:
        query = query.filter(Product.category_id == category_id)
    if q:
        like = f"%{q}%"
        query = query.filter((Product.name.ilike(like)) | (Product.brand.ilike(like)) | (Product.barcode.ilike(like)) | (Product.sku.ilike(like)))
    items = query.order_by(Product.name).limit(5000).all()
    return render_template(
        "admin/products.html", items=items,
        stores=Store.query.filter_by(business_id=current_user.business_id).order_by(Store.name).all(),
        categories=Category.query.filter_by(business_id=current_user.business_id).order_by(Category.sort_order, Category.name).all(),
        q=q, store_id=store_id, category_id=category_id,
    )


@bp.post(f"{ADMIN_BASE}/products/resolve-images")
@admin_required("products.edit")
def resolve_product_images():
    from services.product_images import resolve_product_image
    try:
        limit = max(1, min(int(request.form.get("limit", "80") or "80"), 120))
    except ValueError:
        limit = 80
    products = Product.query.filter(
        Product.status == "ACTIVE",
        (Product.image_url.is_(None)) | (Product.image_url == "")
    ).order_by(Product.name).limit(limit).all()
    matched = 0
    for product in products:
        try:
            image = resolve_product_image(product)
        except Exception:
            image = None
        if image:
            product.image_url = image
            ProductImage.query.filter_by(product_id=product.id, is_primary=True).update({"is_primary": False})
            db.session.add(ProductImage(
                product_id=product.id, image_url=image, thumbnail_url=image,
                alt_text=product.name, source_type="OPEN_FOOD_FACTS_MATCH",
                license_info="External product image; verify supplier/rights before commercial campaigns.",
                sort_order=0, is_primary=True,
            ))
            matched += 1
    db.session.commit()
    checked = len(products)
    remaining = checked - matched
    flash(f"Photo resolver checked {checked} products: {matched} verified matches; {remaining} still need an exact image/upload.", "success" if remaining == 0 else "error")
    return redirect(url_for("admin.products"))


@bp.post(f"{ADMIN_BASE}/products/create")
@admin_required("products.create")
def create_product():
    name = request.form.get("name", "").strip()
    brand = request.form.get("brand", "").strip() or None
    category_id = request.form.get("category_id", "").strip() or None
    unit = request.form.get("unit", "unit").strip() or "unit"
    pack_size = request.form.get("pack_size", "").strip() or unit
    sku = request.form.get("sku", "").strip() or None
    barcode = request.form.get("barcode", "").strip() or None
    description = request.form.get("description", "").strip() or None
    image_url = request.form.get("image_url", "").strip() or None
    try:
        uploaded_image = _uploaded_product_image(request.files.get("product_image"), name or "Product")
        if uploaded_image:
            image_url = uploaded_image
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin.products"))
    store_id = request.form.get("store_id", "").strip() or None
    try:
        price = Decimal(request.form.get("selling_price", "0"))
        cost = Decimal(request.form.get("cost_price", "0"))
        stock = Decimal(request.form.get("stock_quantity", "0"))
    except InvalidOperation:
        flash("Enter valid cost, price and stock values.", "error")
        return redirect(url_for("admin.products"))
    if not name:
        flash("Product name is required.", "error")
        return redirect(url_for("admin.products"))
    if price <= 0 or cost < 0 or stock < 0:
        flash("Use a positive selling price and non-negative cost/stock.", "error")
        return redirect(url_for("admin.products"))
    if category_id and not Category.query.filter_by(id=category_id, business_id=current_user.business_id).first():
        flash("Select a valid category.", "error"); return redirect(url_for("admin.products"))
    if store_id and not Store.query.filter_by(id=store_id, business_id=current_user.business_id).first():
        flash("Select a valid mart.", "error"); return redirect(url_for("admin.products"))
    if sku and Product.query.filter_by(sku=sku).first():
        flash("That SKU is already in use.", "error"); return redirect(url_for("admin.products"))
    if barcode and Product.query.filter_by(barcode=barcode).first():
        flash("That barcode is already in use.", "error"); return redirect(url_for("admin.products"))
    from seed import slugify
    base_slug = slugify(name) or "product"
    slug = base_slug; n = 2
    while Product.query.filter_by(slug=slug).first():
        slug = f"{base_slug}-{n}"; n += 1
    product = Product(name=name, slug=slug, brand=brand, category_id=category_id, unit=unit, pack_size=pack_size,
                      sku=sku, barcode=barcode, description=description, image_url=image_url, status="ACTIVE",
                      search_keywords=" ".join(x for x in [name.lower(), brand.lower() if brand else ""] if x))
    db.session.add(product); db.session.flush()
    if image_url and image_url.startswith("data:image/"):
        _set_product_image(product, image_url)
    stores = [db.session.get(Store, store_id)] if store_id else Store.query.filter_by(business_id=current_user.business_id, is_active=True).all()
    if not stores:
        db.session.rollback(); flash("Create an active mart before adding stock.", "error"); return redirect(url_for("admin.products"))
    for store in stores:
        db.session.add(StoreProduct(store_id=store.id, product_id=product.id, cost_price=cost, selling_price=price,
                                     minimum_price=price, maximum_price=price * Decimal("1.30"), stock_quantity=stock,
                                     reorder_level=5, is_available=True, available_online=True, available_pos=True))
    db.session.add(ProductAlias(product_id=product.id, alias=name, alias_type="SEARCH"))
    db.session.commit()
    audit("PRODUCT_CREATED", "Product", product.id, new_values={"name": name, "sku": sku, "barcode": barcode, "stores": len(stores)})
    flash(f"{name} added to {len(stores)} mart(s).", "success")
    return redirect(url_for("admin.product_edit", product_id=product.id, store_id=stores[0].id))


@bp.post(f"{ADMIN_BASE}/products/import")
@admin_required("products.create")
def import_products():
    upload = request.files.get("catalogue_file")
    store_id = request.form.get("store_id", "").strip() or None
    if not upload or not upload.filename.lower().endswith(".csv"):
        flash("Choose a CSV catalogue file.", "error"); return redirect(url_for("admin.products"))
    if store_id and not Store.query.filter_by(id=store_id, business_id=current_user.business_id).first():
        flash("Select a valid mart.", "error"); return redirect(url_for("admin.products"))
    text = upload.read().decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    required = {"name", "selling_price"}
    if not required.issubset({(h or "").strip().lower() for h in (reader.fieldnames or [])}):
        flash("CSV needs at least name,selling_price columns.", "error"); return redirect(url_for("admin.products"))
    from seed import slugify
    stores = [db.session.get(Store, store_id)] if store_id else Store.query.filter_by(business_id=current_user.business_id, is_active=True).all()
    created = updated = 0
    errors = []
    for line_no, raw in enumerate(reader, start=2):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        name = row.get("name", "")
        if not name: continue
        try:
            price = Decimal(row.get("selling_price", "0")); cost = Decimal(row.get("cost_price", "0") or "0"); stock = Decimal(row.get("stock_quantity", "0") or "0")
            if price <= 0 or cost < 0 or stock < 0: raise InvalidOperation
        except InvalidOperation:
            errors.append(f"Line {line_no}: invalid numeric values"); continue
        category = None
        category_name = row.get("category", "")
        if category_name:
            slug = slugify(category_name)
            category = Category.query.filter_by(business_id=current_user.business_id, slug=slug).first()
            if not category:
                category = Category(business_id=current_user.business_id, name=category_name, slug=slug, is_active=True); db.session.add(category); db.session.flush()
        sku = row.get("sku") or None; barcode = row.get("barcode") or None
        product = None
        if sku: product = Product.query.filter_by(sku=sku).first()
        if not product and barcode: product = Product.query.filter_by(barcode=barcode).first()
        if not product: product = Product.query.filter_by(slug=slugify(name)).first()
        if product:
            product.name = name; product.brand = row.get("brand") or product.brand; product.category_id = category.id if category else product.category_id
            product.unit = row.get("unit") or product.unit; product.pack_size = row.get("pack_size") or product.pack_size
            product.description = row.get("description") or product.description; product.image_url = row.get("image_url") or product.image_url
            if sku: product.sku = sku
            if barcode: product.barcode = barcode
            updated += 1
        else:
            base = slugify(name) or "product"; slug = base; n = 2
            while Product.query.filter_by(slug=slug).first(): slug = f"{base}-{n}"; n += 1
            product = Product(name=name, slug=slug, brand=row.get("brand") or None, category_id=category.id if category else None,
                              unit=row.get("unit") or "unit", pack_size=row.get("pack_size") or row.get("unit") or "unit",
                              sku=sku, barcode=barcode, description=row.get("description") or None, image_url=row.get("image_url") or None,
                              search_keywords=f"{name.lower()} {(row.get('brand') or '').lower()} {(category_name or '').lower()}".strip())
            db.session.add(product); db.session.flush(); db.session.add(ProductAlias(product_id=product.id, alias=name, alias_type="SEARCH")); created += 1
        for store in stores:
            sp = StoreProduct.query.filter_by(store_id=store.id, product_id=product.id).first()
            if not sp:
                sp = StoreProduct(store_id=store.id, product_id=product.id); db.session.add(sp)
            sp.cost_price = cost; sp.selling_price = price; sp.minimum_price = price; sp.maximum_price = price * Decimal("1.30")
            sp.stock_quantity = stock; sp.is_available = row.get("enabled", "1").lower() not in {"0", "no", "false"}
            sp.available_online = row.get("online", "1").lower() not in {"0", "no", "false"}; sp.available_pos = row.get("pos", "1").lower() not in {"0", "no", "false"}
    db.session.commit()
    audit("PRODUCT_CSV_IMPORTED", "Business", current_user.business_id, new_values={"created": created, "updated": updated, "errors": len(errors)})
    msg = f"Catalogue import complete: {created} added, {updated} updated."
    if errors: msg += f" {len(errors)} row(s) skipped."
    flash(msg, "success" if not errors else "error")
    return redirect(url_for("admin.products"))


@bp.get(f"{ADMIN_BASE}/products/export.csv")
@admin_required("backup.create")
def export_products_csv():
    rows = (StoreProduct.query.join(Product).join(Store).filter(Store.business_id == current_user.business_id)
            .order_by(Product.name, Store.name).limit(10000).all())
    out = io.StringIO(); writer = csv.writer(out)
    writer.writerow(["name","brand","sku","barcode","category","unit","pack_size","description","image_url","mart","mart_code","cost_price","selling_price","stock_quantity","online","pos","enabled"])
    for sp in rows:
        p = sp.product; cat = db.session.get(Category, p.category_id) if p.category_id else None
        writer.writerow([p.name,p.brand or "",p.sku or "",p.barcode or "",cat.name if cat else "",p.unit or "",p.pack_size or "",p.description or "",p.image_url or "",sp.store.name,sp.store.code,sp.cost_price,sp.selling_price,sp.stock_quantity,int(sp.available_online),int(sp.available_pos),int(sp.is_available)])
    audit("CATALOGUE_CSV_EXPORTED", "Business", current_user.business_id, new_values={"rows": len(rows)})
    return Response(out.getvalue(), mimetype="text/csv", headers={"Content-Disposition":"attachment; filename=denmart-catalogue.csv"})


@bp.get(f"{ADMIN_BASE}/products/<product_id>/edit")
@admin_required("products.edit")
def product_edit(product_id):
    product = db.session.get(Product, product_id)
    if not product:
        return "Not found", 404
    owns_store = Store.query.filter_by(business_id=current_user.business_id).filter(Store.id.in_([sp.store_id for sp in StoreProduct.query.filter_by(product_id=product.id).all()])).first() if StoreProduct.query.filter_by(product_id=product.id).count() else None
    if not Category.query.filter_by(id=product.category_id, business_id=current_user.business_id).first() if product.category_id else False:
        pass
    stores = Store.query.filter_by(business_id=current_user.business_id).order_by(Store.name).all()
    store_id = request.args.get("store_id", "").strip()
    selected_store = next((s for s in stores if s.id == store_id), None) or (owns_store if owns_store and owns_store.business_id == current_user.business_id else (stores[0] if stores else None))
    if product.category_id and not Category.query.filter_by(id=product.category_id, business_id=current_user.business_id).first():
        return "Forbidden", 403
    for sp in StoreProduct.query.filter_by(product_id=product.id).all():
        if sp.store.business_id == current_user.business_id:
            continue
        return "Forbidden", 403
    return render_template("admin/product_edit.html", product=product, stores=stores, categories=Category.query.filter_by(business_id=current_user.business_id).order_by(Category.sort_order, Category.name).all(),
                           selected_store=selected_store, store_product=(StoreProduct.query.filter_by(product_id=product.id, store_id=selected_store.id).first() if selected_store else None))


@bp.post(f"{ADMIN_BASE}/products/<product_id>/edit")
@admin_required("products.edit")
def save_product(product_id):
    product = db.session.get(Product, product_id)
    if not product:
        return "Not found", 404
    if product.category_id and not Category.query.filter_by(id=product.category_id, business_id=current_user.business_id).first():
        return "Forbidden", 403
    old = {"name": product.name, "brand": product.brand, "sku": product.sku, "barcode": product.barcode, "status": product.status, "image_url": product.image_url}
    product.name = request.form.get("name", product.name).strip() or product.name
    product.brand = request.form.get("brand", "").strip() or None
    product.category_id = request.form.get("category_id", "").strip() or None
    product.unit = request.form.get("unit", "unit").strip() or "unit"
    product.pack_size = request.form.get("pack_size", "").strip() or product.unit
    product.sku = request.form.get("sku", "").strip() or None
    product.barcode = request.form.get("barcode", "").strip() or None
    product.description = request.form.get("description", "").strip() or None
    submitted_image_url = request.form.get("image_url", "").strip()
    try:
        uploaded_image = _uploaded_product_image(request.files.get("product_image"), product.name)
    except ValueError as exc:
        db.session.rollback(); flash(str(exc), "error")
        return redirect(url_for("admin.product_edit", product_id=product.id, store_id=request.form.get("store_id", "").strip()))
    if uploaded_image:
        _set_product_image(product, uploaded_image)
    elif submitted_image_url:
        _set_product_image(product, submitted_image_url, source_type="ADMIN_URL")
    elif request.form.get("remove_image") == "1":
        product.image_url = None
        ProductImage.query.filter_by(product_id=product.id).delete(synchronize_session=False)
    product.status = "ACTIVE" if request.form.get("status") == "ACTIVE" else "ARCHIVED"
    product.search_keywords = " ".join(x for x in [product.name.lower(), (product.brand or "").lower(), (product.description or "").lower()] if x)
    sp_store_id = request.form.get("store_id", "").strip()
    sp = StoreProduct.query.filter_by(product_id=product.id, store_id=sp_store_id).first()
    if sp and sp.store.business_id == current_user.business_id:
        try:
            sp.cost_price = Decimal(request.form.get("cost_price", str(sp.cost_price)))
            sp.selling_price = Decimal(request.form.get("selling_price", str(sp.selling_price)))
            sp.minimum_price = Decimal(request.form.get("minimum_price", str(sp.minimum_price or sp.selling_price)))
            maxv = request.form.get("maximum_price", "").strip(); sp.maximum_price = Decimal(maxv) if maxv else None
            sp.stock_quantity = Decimal(request.form.get("stock_quantity", str(sp.stock_quantity)))
            sp.reorder_level = Decimal(request.form.get("reorder_level", str(sp.reorder_level or 0)))
        except InvalidOperation:
            db.session.rollback(); flash("Check the numeric mart values.", "error"); return redirect(url_for("admin.product_edit", product_id=product.id, store_id=sp_store_id))
        sp.is_available = request.form.get("enabled") == "1" and product.status == "ACTIVE"
        sp.available_online = request.form.get("online") == "1" and sp.is_available
        sp.available_pos = request.form.get("pos") == "1" and sp.is_available
    alias = ProductAlias.query.filter_by(product_id=product.id, alias=product.name).first()
    if not alias: db.session.add(ProductAlias(product_id=product.id, alias=product.name, alias_type="SEARCH"))
    db.session.commit()
    audit("PRODUCT_UPDATED", "Product", product.id, old_values=old, new_values={"name": product.name, "brand": product.brand, "sku": product.sku, "barcode": product.barcode, "status": product.status, "image_url": product.image_url})
    flash("Product updated.", "success")
    return redirect(url_for("admin.product_edit", product_id=product.id, store_id=sp_store_id))


@bp.post(f"{ADMIN_BASE}/products/<product_id>/delete")
@admin_required("products.delete")
def delete_product(product_id):
    product = db.session.get(Product, product_id)
    if not product:
        flash("Product not found.", "error"); return redirect(url_for("admin.products"))
    references = (SaleItem.query.filter_by(product_id=product.id).count() + OrderItem.query.filter_by(product_id=product.id).count() + InventoryTransaction.query.filter_by(product_id=product.id).count())
    old_name = product.name
    if references:
        product.status = "ARCHIVED"
        StoreProduct.query.filter_by(product_id=product.id).update({"is_available": False, "available_online": False, "available_pos": False})
        db.session.commit()
        audit("PRODUCT_ARCHIVED", "Product", product.id, new_values={"reason":"historical references", "references": references})
        flash(f"{old_name} was archived because it has transaction history.", "success")
    else:
        StoreProduct.query.filter_by(product_id=product.id).delete(synchronize_session=False)
        ProductAlias.query.filter_by(product_id=product.id).delete(synchronize_session=False)
        ProductImage.query.filter_by(product_id=product.id).delete(synchronize_session=False)
        db.session.delete(product); db.session.commit()
        audit("PRODUCT_DELETED", "Product", product_id, new_values={"name": old_name})
        flash(f"{old_name} deleted.", "success")
    return redirect(url_for("admin.products"))


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



@bp.get(f"{ADMIN_BASE}/inventory")
@bp.post(f"{ADMIN_BASE}/inventory/adjust")
@admin_required("inventory.view")
def inventory():
    business_id = current_user.business_id
    stores = Store.query.filter_by(business_id=business_id).order_by(Store.name).all()
    store_id = (request.args.get("store_id") or request.form.get("store_id") or "").strip()
    selected_store = db.session.get(Store, store_id) if store_id else None
    if selected_store and selected_store.business_id != business_id:
        selected_store = None
        store_id = ""
    if request.method == "POST":
        if not current_user.has_permission("inventory.adjust") and current_user.role.name != "OWNER":
            return "Forbidden", 403
        product_id = request.form.get("product_id", "").strip()
        try:
            delta = Decimal(request.form.get("quantity_delta", "0"))
            unit_cost = Decimal(request.form.get("unit_cost", "0") or "0")
        except InvalidOperation:
            flash("Quantity and cost must be valid numbers.", "error")
            return redirect(url_for("admin.inventory", store_id=store_id))
        if not selected_store or not product_id or delta == 0 or unit_cost < 0:
            flash("Choose a mart, product and a non-zero quantity change.", "error")
            return redirect(url_for("admin.inventory", store_id=store_id))
        product = db.session.get(Product, product_id)
        if not product:
            flash("Product not found.", "error")
            return redirect(url_for("admin.inventory", store_id=store_id))
        sp = StoreProduct.query.filter_by(store_id=selected_store.id, product_id=product.id).with_for_update().first()
        if not sp:
            sp = StoreProduct(store_id=selected_store.id, product_id=product.id, cost_price=unit_cost, selling_price=Decimal("0"), stock_quantity=0, reserved_quantity=0)
            db.session.add(sp); db.session.flush()
        current_stock = Decimal(sp.stock_quantity or 0)
        reserved = Decimal(sp.reserved_quantity or 0)
        new_stock = current_stock + delta
        if new_stock < 0 or new_stock < reserved:
            flash(f"Stock cannot fall below reserved quantity ({reserved}).", "error")
            return redirect(url_for("admin.inventory", store_id=store_id))
        old = {"stock": str(current_stock), "cost": str(sp.cost_price or 0)}
        sp.stock_quantity = new_stock
        if unit_cost > 0:
            sp.cost_price = unit_cost
        txn_type = "ADJUSTMENT_IN" if delta > 0 else "ADJUSTMENT_OUT"
        db.session.add(InventoryTransaction(
            store_id=selected_store.id, product_id=product.id, transaction_type=txn_type,
            quantity=delta, unit_cost=sp.cost_price, reference_type="ADMIN_ADJUSTMENT",
            reference_id=sp.id, notes=request.form.get("notes", "").strip()[:500] or None, created_by=current_user.id,
        ))
        db.session.commit()
        audit("INVENTORY_ADJUSTED", "StoreProduct", sp.id, old_values=old, new_values={"stock": str(sp.stock_quantity), "cost": str(sp.cost_price), "delta": str(delta)})
        flash(f"{product.name}: stock is now {sp.stock_quantity} at {selected_store.name}.", "success")
        return redirect(url_for("admin.inventory", store_id=selected_store.id))

    q = (request.args.get("q") or "").strip()
    low = request.args.get("low") == "1"
    query = StoreProduct.query.join(Store).join(Product).filter(Store.business_id == business_id)
    if selected_store:
        query = query.filter(StoreProduct.store_id == selected_store.id)
    if q:
        needle = f"%{q}%"
        query = query.filter(or_(Product.name.ilike(needle), Product.barcode.ilike(needle), Product.sku.ilike(needle)))
    if low:
        query = query.filter(StoreProduct.stock_quantity <= StoreProduct.reorder_level)
    rows = query.order_by((StoreProduct.stock_quantity - StoreProduct.reorder_level).asc(), Product.name.asc()).limit(400).all()
    total_cost = sum((Decimal(r.stock_quantity or 0) * Decimal(r.cost_price or 0) for r in rows), Decimal("0"))
    total_retail = sum((Decimal(r.stock_quantity or 0) * Decimal(r.selling_price or 0) for r in rows), Decimal("0"))
    low_count = sum(1 for r in rows if Decimal(r.stock_quantity or 0) <= Decimal(r.reorder_level or 0))
    return render_template("admin/inventory.html", rows=rows, stores=stores, store_id=store_id, selected_store=selected_store,
                           q=q, low=low, total_cost=total_cost, total_retail=total_retail, low_count=low_count)


@bp.route(f"{ADMIN_BASE}/categories", methods=["GET", "POST"])
@admin_required("products.edit")
def categories():
    business_id = current_user.business_id
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Category name is required.", "error")
        elif Category.query.filter_by(business_id=business_id, name=name).first():
            flash("That category already exists.", "error")
        else:
            slug = re_slug = "-".join(name.lower().split())[:140]
            if Category.query.filter_by(business_id=business_id, slug=slug).first():
                slug = f"{slug}-{secrets.token_hex(2)}"
            db.session.add(Category(business_id=business_id, name=name, slug=slug, description=request.form.get("description", "").strip() or None, sort_order=int(request.form.get("sort_order", 0) or 0), is_active=True))
            db.session.commit(); audit("CATEGORY_CREATED", "Category", None, new_values={"name": name}); flash("Category created.", "success")
    cats = Category.query.filter_by(business_id=business_id).order_by(Category.sort_order, Category.name).all()
    usage = {c.id: Product.query.filter_by(category_id=c.id).count() for c in cats}
    return render_template("admin/categories.html", categories=cats, usage=usage)


@bp.post(f"{ADMIN_BASE}/categories/<category_id>/toggle")
@admin_required("products.edit")
def toggle_category(category_id):
    category = db.session.get(Category, category_id)
    if not category or category.business_id != current_user.business_id:
        return "Not found", 404
    category.is_active = not category.is_active
    db.session.commit(); audit("CATEGORY_STATUS_CHANGED", "Category", category.id, new_values={"active": category.is_active})
    flash(f"{category.name} is now {'active' if category.is_active else 'hidden'}.", "success")
    return redirect(url_for("admin.categories"))


@bp.route(f"{ADMIN_BASE}/suppliers", methods=["GET", "POST"])
@admin_required("inventory.view")
def suppliers():
    business_id = current_user.business_id
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Supplier name is required.", "error")
        else:
            supplier = Supplier(business_id=business_id, name=name, phone=request.form.get("phone", "").strip() or None,
                                email=request.form.get("email", "").strip() or None, address=request.form.get("address", "").strip() or None,
                                tax_identifier=request.form.get("tax_identifier", "").strip() or None, is_active=True)
            db.session.add(supplier); db.session.commit(); audit("SUPPLIER_CREATED", "Supplier", supplier.id, new_values={"name": name}); flash("Supplier added.", "success")
            return redirect(url_for("admin.suppliers"))
    rows = Supplier.query.filter_by(business_id=business_id).order_by(Supplier.is_active.desc(), Supplier.name.asc()).all()
    return render_template("admin/suppliers.html", suppliers=rows)


@bp.post(f"{ADMIN_BASE}/suppliers/<supplier_id>/toggle")
@admin_required("inventory.view")
def toggle_supplier(supplier_id):
    supplier = db.session.get(Supplier, supplier_id)
    if not supplier or supplier.business_id != current_user.business_id:
        return "Not found", 404
    supplier.is_active = not supplier.is_active
    db.session.commit(); audit("SUPPLIER_STATUS_CHANGED", "Supplier", supplier.id, new_values={"active": supplier.is_active})
    return redirect(url_for("admin.suppliers"))


@bp.route(f"{ADMIN_BASE}/purchases", methods=["GET", "POST"])
@admin_required("inventory.view")
def purchases():
    business_id = current_user.business_id
    stores = Store.query.filter_by(business_id=business_id).order_by(Store.name).all()
    suppliers = Supplier.query.filter_by(business_id=business_id, is_active=True).order_by(Supplier.name).all()
    products = Product.query.filter_by(status="ACTIVE").order_by(Product.name).limit(1500).all()
    if request.method == "POST":
        store = db.session.get(Store, request.form.get("store_id", ""))
        supplier = db.session.get(Supplier, request.form.get("supplier_id", ""))
        product = db.session.get(Product, request.form.get("product_id", ""))
        try:
            qty = Decimal(request.form.get("quantity", "0")); unit_cost = Decimal(request.form.get("unit_cost", "0")); tax = Decimal(request.form.get("tax", "0") or "0")
        except InvalidOperation:
            qty = Decimal("0"); unit_cost = Decimal("0"); tax = Decimal("0")
        if not store or store.business_id != business_id or not supplier or supplier.business_id != business_id or not product or qty <= 0 or unit_cost < 0 or tax < 0:
            flash("Select valid mart, supplier, product, quantity and cost.", "error")
        else:
            subtotal = qty * unit_cost
            ref = f"PO-{now().strftime('%Y%m%d')}-{secrets.token_hex(3).upper()}"
            po = PurchaseOrder(business_id=business_id, store_id=store.id, supplier_id=supplier.id, reference_number=ref,
                               status="ORDERED", subtotal=subtotal, tax=tax, total=subtotal + tax, created_by=current_user.id)
            db.session.add(po); db.session.flush()
            db.session.add(PurchaseOrderItem(purchase_order_id=po.id, product_id=product.id, quantity=qty, unit_cost=unit_cost, tax=tax, total=subtotal + tax))
            db.session.commit(); audit("PURCHASE_ORDER_CREATED", "PurchaseOrder", po.id, new_values={"reference": ref, "total": str(po.total)})
            flash(f"Purchase order {ref} created.", "success")
            return redirect(url_for("admin.purchases"))
    rows = PurchaseOrder.query.filter_by(business_id=business_id).order_by(PurchaseOrder.created_at.desc()).limit(250).all()
    items = {}
    for po in rows:
        items[po.id] = PurchaseOrderItem.query.filter_by(purchase_order_id=po.id).all()
    stores_map = {s.id: s.name for s in stores}; suppliers_map = {s.id: s.name for s in suppliers}
    product_map = {p.id: p.name for p in products}
    return render_template("admin/purchases.html", purchases=rows, stores=stores, suppliers=suppliers, products=products, items=items,
                           stores_map=stores_map, suppliers_map=suppliers_map, product_map=product_map)


@bp.post(f"{ADMIN_BASE}/purchases/<purchase_id>/receive")
@admin_required("inventory.adjust")
def receive_purchase(purchase_id):
    po = db.session.get(PurchaseOrder, purchase_id)
    if not po or po.business_id != current_user.business_id:
        return "Not found", 404
    if po.status == "RECEIVED":
        flash("That purchase order is already received.", "error")
        return redirect(url_for("admin.purchases"))
    if po.status == "CANCELLED":
        flash("Cancelled purchase orders cannot be received.", "error")
        return redirect(url_for("admin.purchases"))
    lines = PurchaseOrderItem.query.filter_by(purchase_order_id=po.id).all()
    for line in lines:
        sp = StoreProduct.query.filter_by(store_id=po.store_id, product_id=line.product_id).first()
        if not sp:
            sp = StoreProduct(store_id=po.store_id, product_id=line.product_id, stock_quantity=0, reserved_quantity=0,
                              cost_price=line.unit_cost, selling_price=Decimal("0"), minimum_price=0,
                              is_available=False, available_online=False, available_pos=False)
            db.session.add(sp); db.session.flush()
        sp.stock_quantity = Decimal(sp.stock_quantity or 0) + Decimal(line.quantity)
        sp.cost_price = Decimal(line.unit_cost)
        db.session.add(InventoryTransaction(store_id=po.store_id, product_id=line.product_id, transaction_type="PURCHASE",
                                            quantity=Decimal(line.quantity), unit_cost=Decimal(line.unit_cost), reference_type="PURCHASE_ORDER",
                                            reference_id=po.id, created_by=current_user.id, notes=po.reference_number))
    po.status = "RECEIVED"
    db.session.commit(); audit("PURCHASE_RECEIVED", "PurchaseOrder", po.id, new_values={"status": po.status})
    flash(f"{po.reference_number} received and stock updated.", "success")
    return redirect(url_for("admin.purchases"))


@bp.get(f"{ADMIN_BASE}/customers")
@admin_required("reports.view")
def customers():
    business_id = current_user.business_id
    q = (request.args.get("q") or "").strip()
    query = Customer.query.filter_by(business_id=business_id)
    if q:
        needle = f"%{q}%"
        query = query.filter(or_(Customer.name.ilike(needle), Customer.phone.ilike(needle), Customer.email.ilike(needle)))
    rows = query.order_by(Customer.created_at.desc()).limit(500).all()
    customer_ids = [c.id for c in rows]
    if not customer_ids:
        return render_template("admin/customers.html", rows=[], q=q)
    order_stats = db.session.query(
        Order.customer_id,
        db.func.count(Order.id),
        db.func.coalesce(db.func.sum(case((Order.payment_status == "PAID", Order.total), else_=0)), 0),
    ).filter(Order.business_id == business_id, Order.customer_id.in_(customer_ids)).group_by(Order.customer_id).all()
    order_map = {cid: (int(count), Decimal(str(paid or 0))) for cid, count, paid in order_stats}
    loyalty_rows = LoyaltyAccount.query.filter(LoyaltyAccount.business_id == business_id, LoyaltyAccount.customer_id.in_(customer_ids)).all()
    loyalty_map = {a.customer_id: a for a in loyalty_rows}
    data = []
    for customer in rows:
        count, paid = order_map.get(customer.id, (0, Decimal("0")))
        account = loyalty_map.get(customer.id)
        data.append({"customer": customer, "orders": count, "paid": paid,
                     "points": account.points_balance if account else 0,
                     "lifetime_points": account.lifetime_points if account else 0})
    return render_template("admin/customers.html", rows=data, q=q)


@bp.post(f"{ADMIN_BASE}/customers/<customer_id>/loyalty")
@admin_required("reports.view")
def adjust_loyalty(customer_id):
    customer = db.session.get(Customer, customer_id)
    if not customer or customer.business_id != current_user.business_id:
        return "Not found", 404
    try:
        points = int(request.form.get("points", "0"))
    except (TypeError, ValueError):
        points = 0
    if not points or abs(points) > 100000:
        flash("Enter a non-zero adjustment of up to 100,000 points.", "error")
        return redirect(url_for("admin.customers"))
    account = LoyaltyAccount.query.filter_by(business_id=current_user.business_id, customer_id=customer.id).first()
    if not account:
        account = LoyaltyAccount(business_id=current_user.business_id, customer_id=customer.id, points_balance=0, lifetime_points=0)
        db.session.add(account); db.session.flush()
    new_balance = account.points_balance + points
    if new_balance < 0:
        flash("Loyalty balance cannot go below zero.", "error")
        return redirect(url_for("admin.customers"))
    account.points_balance = new_balance
    if points > 0:
        account.lifetime_points += points
    db.session.add(LoyaltyTransaction(business_id=current_user.business_id, customer_id=customer.id, points=points,
                                      transaction_type="ADJUSTMENT", note="Administrator loyalty adjustment"))
    db.session.commit(); audit("LOYALTY_ADJUSTED", "Customer", customer.id, new_values={"points": points, "balance": new_balance})
    flash(f"{customer.name}: loyalty balance is now {new_balance} points.", "success")
    return redirect(url_for("admin.customers"))


@bp.get(f"{ADMIN_BASE}/shifts")
@admin_required("reports.view")
def shifts():
    business_id = current_user.business_id
    rows = (Shift.query.join(Store, Store.id == Shift.store_id).join(User, User.id == Shift.cashier_id)
            .filter(Store.business_id == business_id).order_by(Shift.opened_at.desc()).limit(300).all())
    stores = {s.id: s for s in Store.query.filter_by(business_id=business_id).all()}
    users = {u.id: u for u in User.query.filter_by(business_id=business_id).all()}
    return render_template("admin/shifts.html", shifts=rows, store_map=stores, user_map=users)


# ---------------------------------------------------------------------------
# Full control-centre management routes. These were intentionally kept out of
# the public shopping/merchant blueprints so the admin remains one protected
# workspace.
# ---------------------------------------------------------------------------

@bp.route(f"{ADMIN_BASE}/users", methods=["GET", "POST"])
@admin_required("users.manage")
def users():
    business_id = current_user.business_id
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        role_id = request.form.get("role_id") or ""
        store_id = request.form.get("store_id") or None
        email = (request.form.get("email") or "").strip() or None
        phone = (request.form.get("phone") or "").strip() or None
        role = db.session.get(Role, role_id)
        store = db.session.get(Store, store_id) if store_id else None
        if not name or not username or len(password) < 8 or not role:
            flash("Name, username, a role and a password of at least 8 characters are required.", "error")
        elif role.name == "OWNER":
            flash("Use the existing master administrator account for owner access. Create staff as Manager, Cashier, Stock Controller or another staff role.", "error")
        elif User.query.filter_by(username=username).first():
            flash("That username is already in use.", "error")
        elif email and User.query.filter(User.email == email).first():
            flash("That email is already in use.", "error")
        elif store and store.business_id != business_id:
            flash("The selected mart does not belong to this business.", "error")
        else:
            user = User(
                business_id=business_id, store_id=store.id if store else None,
                name=name, username=username, email=email, phone=phone,
                role_id=role.id, is_active=True,
            )
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            audit("STAFF_CREATED", "User", user.id, new_values={"name": name, "username": username, "role": role.name, "store_id": store.id if store else None})
            flash(f"{name} can now sign in as {role.name.replace('_', ' ').title()}.", "success")
            return redirect(url_for("admin.users"))
    roles = Role.query.filter(Role.name != "OWNER").order_by(Role.name).all()
    stores = Store.query.filter_by(business_id=business_id).order_by(Store.name).all()
    rows = User.query.filter_by(business_id=business_id).order_by(User.is_active.desc(), User.name.asc()).all()
    return render_template("admin/users.html", users=rows, roles=roles, stores=stores)


@bp.post(f"{ADMIN_BASE}/users/<user_id>/toggle")
@admin_required("users.manage")
def toggle_user(user_id):
    user = db.session.get(User, user_id)
    if not user or user.business_id != current_user.business_id:
        return "Not found", 404
    if user.id == current_user.id:
        flash("You cannot disable the account you are currently using.", "error")
        return redirect(url_for("admin.users"))
    user.is_active = not user.is_active
    db.session.commit()
    audit("STAFF_STATUS_CHANGED", "User", user.id, new_values={"active": user.is_active})
    flash(f"{user.name} is now {'active' if user.is_active else 'disabled'}.", "success")
    return redirect(url_for("admin.users"))


@bp.post(f"{ADMIN_BASE}/users/<user_id>/reset-password")
@admin_required("users.manage")
def reset_user_password(user_id):
    user = db.session.get(User, user_id)
    if not user or user.business_id != current_user.business_id or user.id == current_user.id:
        return "Not found", 404
    password = request.form.get("password") or ""
    if len(password) < 8:
        flash("New password must be at least 8 characters.", "error")
    else:
        user.set_password(password)
        db.session.commit()
        audit("STAFF_PASSWORD_RESET", "User", user.id)
        flash(f"Password reset for {user.name}.", "success")
    return redirect(url_for("admin.users"))


@bp.route(f"{ADMIN_BASE}/stores", methods=["GET", "POST"])
@admin_required("inventory.view")
def stores():
    business_id = current_user.business_id
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        code = (request.form.get("code") or "").strip().upper()
        phone = (request.form.get("phone") or "").strip() or None
        address = (request.form.get("address") or "").strip() or None
        if not name or not code:
            flash("Mart name and code are required.", "error")
        elif Store.query.filter_by(business_id=business_id, code=code).first():
            flash("That mart code is already in use.", "error")
        else:
            store = Store(business_id=business_id, name=name, code=code, phone=phone, address=address, is_active=True)
            db.session.add(store)
            db.session.commit()
            audit("MART_CREATED", "Store", store.id, new_values={"name": name, "code": code})
            flash(f"{name} created.", "success")
            return redirect(url_for("admin.stores"))
    rows = Store.query.filter_by(business_id=business_id).order_by(Store.is_active.desc(), Store.name.asc()).all()
    return render_template("admin/stores.html", stores=rows)


@bp.post(f"{ADMIN_BASE}/stores/<store_id>/edit")
@admin_required("inventory.view")
def edit_store(store_id):
    store = db.session.get(Store, store_id)
    if not store or store.business_id != current_user.business_id:
        return "Not found", 404
    name = (request.form.get("name") or "").strip()
    code = (request.form.get("code") or "").strip().upper()
    if not name or not code:
        flash("Mart name and code are required.", "error")
        return redirect(url_for("admin.stores"))
    duplicate = Store.query.filter(Store.business_id == store.business_id, Store.code == code, Store.id != store.id).first()
    if duplicate:
        flash("That mart code belongs to another mart.", "error")
        return redirect(url_for("admin.stores"))
    def _num(v):
        try:
            return float(v) if str(v or "").strip() else None
        except ValueError:
            return None
    old = {"name": store.name, "code": store.code, "phone": store.phone, "address": store.address, "active": store.is_active}
    store.name = name; store.code = code; store.phone = (request.form.get("phone") or "").strip() or None
    store.address = (request.form.get("address") or "").strip() or None
    store.latitude = _num(request.form.get("latitude")); store.longitude = _num(request.form.get("longitude"))
    store.is_active = request.form.get("active") == "1"
    db.session.commit()
    audit("MART_UPDATED", "Store", store.id, old_values=old, new_values={"name": store.name, "code": store.code, "active": store.is_active})
    flash(f"{store.name} updated.", "success")
    return redirect(url_for("admin.stores"))


@bp.post(f"{ADMIN_BASE}/stores/<store_id>/delete")
@admin_required("inventory.view")
def delete_store(store_id):
    store = db.session.get(Store, store_id)
    if not store or store.business_id != current_user.business_id:
        return "Not found", 404
    active_count = Store.query.filter_by(business_id=store.business_id, is_active=True).count()
    if store.is_active and active_count <= 1:
        flash("Keep at least one active mart. Deactivate it only after another mart is active.", "error")
        return redirect(url_for("admin.stores"))
    store.is_active = False
    db.session.commit()
    audit("MART_DEACTIVATED", "Store", store.id, new_values={"active": False})
    flash(f"{store.name} has been deactivated. Historical sales remain intact.", "success")
    return redirect(url_for("admin.stores"))


@bp.route(f"{ADMIN_BASE}/expenses", methods=["GET", "POST"])
@admin_required("reports.view")
def expenses():
    business_id = current_user.business_id
    stores = Store.query.filter_by(business_id=business_id).order_by(Store.name).all()
    if request.method == "POST":
        category = (request.form.get("category") or "General").strip() or "General"
        description = (request.form.get("description") or "").strip()
        store_id = request.form.get("store_id") or None
        try:
            amount = Decimal(request.form.get("amount", "0"))
        except InvalidOperation:
            amount = Decimal("0")
        store = db.session.get(Store, store_id) if store_id else None
        if not description or amount <= 0 or (store and store.business_id != business_id):
            flash("Enter a description, positive amount and valid mart.", "error")
        else:
            row = Expense(business_id=business_id, store_id=store.id if store else None, category=category,
                          description=description, amount=amount, created_by=current_user.id)
            db.session.add(row); db.session.commit()
            audit("EXPENSE_RECORDED", "Expense", row.id, new_values={"category": category, "amount": str(amount), "store_id": store.id if store else None})
            flash("Expense recorded.", "success")
            return redirect(url_for("admin.expenses"))
    rows = Expense.query.filter_by(business_id=business_id).order_by(Expense.incurred_at.desc()).limit(500).all()
    total = db.session.query(db.func.coalesce(db.func.sum(Expense.amount), 0)).filter_by(business_id=business_id).scalar() or 0
    return render_template("admin/expenses.html", rows=rows, stores=stores, total=total)


@bp.route(f"{ADMIN_BASE}/pricing", methods=["GET", "POST"])
@admin_required("products.edit")
def pricing():
    business_id = current_user.business_id
    stores = Store.query.filter_by(business_id=business_id).order_by(Store.name).all()
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        rule_type = (request.form.get("rule_type") or "COST_PLUS_PERCENT").strip().upper()
        store_id = request.form.get("store_id") or None
        try:
            margin = Decimal(request.form.get("margin_percent", "0") or "0")
            markup = Decimal(request.form.get("fixed_markup", "0") or "0")
            rounding = Decimal(request.form.get("rounding_rule", "1") or "1")
            min_margin = Decimal(request.form.get("min_margin_percent", "0") or "0")
            max_discount = Decimal(request.form.get("max_discount_percent", "0") or "0")
            priority = int(request.form.get("priority", "100") or "100")
        except (InvalidOperation, ValueError):
            margin = markup = min_margin = max_discount = Decimal("0"); rounding = Decimal("1"); priority = 100
        store = db.session.get(Store, store_id) if store_id else None
        if not name or rule_type not in {"COST_PLUS_PERCENT", "FIXED_MARKUP"} or (store and store.business_id != business_id):
            flash("Enter a rule name and valid mart/type.", "error")
        elif margin < 0 or markup < 0 or rounding <= 0 or min_margin < 0 or max_discount < 0:
            flash("Pricing values cannot be negative and rounding must be greater than zero.", "error")
        else:
            rule = PricingRule(business_id=business_id, store_id=store.id if store else None, name=name,
                               rule_type=rule_type, margin_percent=margin, fixed_markup=markup,
                               rounding_rule=rounding, min_margin_percent=min_margin,
                               max_discount_percent=max_discount, priority=priority, is_active=True)
            db.session.add(rule); db.session.commit()
            audit("PRICING_RULE_CREATED", "PricingRule", rule.id, new_values={"name": name, "type": rule_type})
            flash("Pricing rule created.", "success")
            return redirect(url_for("admin.pricing"))
    rows = PricingRule.query.filter_by(business_id=business_id).order_by(PricingRule.priority.asc(), PricingRule.name.asc()).all()
    store_map = {s.id: s.name for s in stores}
    return render_template("admin/pricing.html", rules=rows, stores=stores, store_map=store_map)


@bp.post(f"{ADMIN_BASE}/pricing/<rule_id>/toggle")
@admin_required("products.edit")
def toggle_pricing_rule(rule_id):
    rule = db.session.get(PricingRule, rule_id)
    if not rule or rule.business_id != current_user.business_id:
        return "Not found", 404
    rule.is_active = not rule.is_active
    db.session.commit()
    audit("PRICING_RULE_STATUS_CHANGED", "PricingRule", rule.id, new_values={"active": rule.is_active})
    flash(f"{rule.name} is now {'active' if rule.is_active else 'off'}.", "success")
    return redirect(url_for("admin.pricing"))


@bp.post(f"{ADMIN_BASE}/pricing/apply")
@admin_required("products.edit")
def apply_pricing_rules():
    from services.pricing import suggested_price
    business_id = current_user.business_id
    changed = 0
    rows = StoreProduct.query.join(Store).filter(Store.business_id == business_id).all()
    active_rules = PricingRule.query.filter_by(business_id=business_id, is_active=True).order_by(PricingRule.priority.asc()).all()
    for sp in rows:
        rule = next((r for r in active_rules if r.store_id in {None, sp.store_id}), None)
        if not rule:
            continue
        new_price = suggested_price(sp, rule)
        old_price = Decimal(str(sp.selling_price or 0))
        if new_price != old_price:
            sp.selling_price = new_price
            sp.pricing_rule_id = rule.id
            db.session.add(PriceHistory(store_product_id=sp.id, old_price=old_price, new_price=new_price,
                                        reason=f"Applied pricing rule: {rule.name}", source="RULE", changed_by=current_user.id))
            changed += 1
    db.session.commit()
    audit("PRICING_RULES_APPLIED", "Business", business_id, new_values={"changed_prices": changed})
    flash(f"Pricing engine applied to {changed} store prices.", "success")
    return redirect(url_for("admin.pricing"))


@bp.route(f"{ADMIN_BASE}/settings", methods=["GET", "POST"])
@admin_required()
def settings():
    business = current_user.business
    business_id = business.id

    def get_setting(key, default=""):
        row = SystemSetting.query.filter_by(business_id=business_id, key=key).first()
        return row.value if row else default

    if request.method == "POST":
        business.name = (request.form.get("business_name") or business.name).strip() or business.name
        footer = (request.form.get("footer_text") or "").strip()
        def put(key, value):
            row = SystemSetting.query.filter_by(business_id=business_id, key=key).first()
            if not row:
                row = SystemSetting(business_id=business_id, key=key)
                db.session.add(row)
            row.value = str(value)
        put("footer_text", footer)
        try:
            lp = max(0, int(request.form.get("loyalty_points_per_100", "1") or "1"))
        except ValueError:
            lp = 1
        put("loyalty_points_per_100", lp)
        put("delivery_enabled", request.form.get("delivery_enabled", "1") == "1")
        try: put("delivery_bike_base_fee", max(0, Decimal(request.form.get("bike_base_fee", "100") or "100")))
        except InvalidOperation: put("delivery_bike_base_fee", "100")
        try: put("delivery_bike_per_km", max(0, Decimal(request.form.get("bike_per_km", "20") or "20")))
        except InvalidOperation: put("delivery_bike_per_km", "20")

        upload = request.files.get("business_logo")
        if request.form.get("remove_logo") == "1":
            business.logo_url = None
        elif upload and upload.filename:
            try:
                business.logo_url = _uploaded_product_image(upload, business.name)
            except ValueError as exc:
                flash(str(exc), "error")
                db.session.rollback()
                return redirect(url_for("admin.settings"))

        if request.form.get("save_mpesa") == "1":
            integration = PaymentIntegration.query.filter_by(business_id=business_id, provider="DARAJA").first()
            if not integration:
                integration = PaymentIntegration(business_id=business_id, provider="DARAJA")
                db.session.add(integration)
            integration.environment = request.form.get("environment", "sandbox")
            integration.callback_url = (request.form.get("callback_url") or "").strip()
            integration.is_active = request.form.get("mpesa_active") == "1"
            for form_key, column in (("consumer_key", "consumer_key_encrypted"), ("consumer_secret", "consumer_secret_encrypted"),
                                     ("shortcode", "shortcode_encrypted"), ("passkey", "passkey_encrypted")):
                raw = (request.form.get(form_key) or "").strip()
                if raw:
                    setattr(integration, column, encrypt(raw))
            put("mpesa_transaction_type", request.form.get("transaction_type", "CustomerPayBillOnline"))
        db.session.commit()
        audit("SETTINGS_UPDATED", "Business", business_id, new_values={"business_name": business.name, "mpesa_saved": request.form.get("save_mpesa") == "1"})
        flash("Settings saved.", "success")
        return redirect(url_for("admin.settings"))

    integration = PaymentIntegration.query.filter_by(business_id=business_id, provider="DARAJA").first()
    return render_template(
        "admin/settings.html", business=business,
        integration=integration,
        till_number=get_setting("mpesa_till_number", ""),
        transaction_type=get_setting("mpesa_transaction_type", "CustomerPayBillOnline"),
        callback_url=integration.callback_url if integration else "",
        loyalty_points_per_100=get_setting("loyalty_points_per_100", "1"),
        delivery_enabled=get_setting("delivery_enabled", "1") == "1",
        bike_base_fee=get_setting("delivery_bike_base_fee", "100"),
        bike_per_km=get_setting("delivery_bike_per_km", "20"),
    )


@bp.post(f"{ADMIN_BASE}/settings/till")
@admin_required()
def save_till():
    value = (request.form.get("till_number") or "").strip()
    if value and not value.isdigit():
        flash("Till number must contain digits only.", "error")
        return redirect(url_for("admin.settings"))
    row = SystemSetting.query.filter_by(business_id=current_user.business_id, key="mpesa_till_number").first()
    if not row:
        row = SystemSetting(business_id=current_user.business_id, key="mpesa_till_number")
        db.session.add(row)
    row.value = value
    db.session.commit()
    audit("MPESA_TILL_UPDATED", "Business", current_user.business_id, new_values={"configured": bool(value)})
    flash("M-PESA Till saved." if value else "M-PESA Till cleared.", "success")
    return redirect(url_for("admin.settings"))


@bp.post(f"{ADMIN_BASE}/settings/test-daraja")
@admin_required()
def test_daraja():
    integration = PaymentIntegration.query.filter_by(business_id=current_user.business_id, provider="DARAJA").first()
    if not integration or not integration.consumer_key_encrypted or not integration.consumer_secret_encrypted or not integration.shortcode_encrypted or not integration.passkey_encrypted:
        flash("Save complete Daraja credentials before testing the connection.", "error")
        return redirect(url_for("admin.settings"))
    try:
        provider = DarajaProvider(
            decrypt(integration.consumer_key_encrypted), decrypt(integration.consumer_secret_encrypted),
            decrypt(integration.shortcode_encrypted), decrypt(integration.passkey_encrypted),
            environment=integration.environment or "sandbox", callback_url=integration.callback_url or "",
        )
        provider.access_token()
        integration.last_tested_at = now()
        db.session.commit()
        audit("DARAJA_CONNECTION_TESTED", "PaymentIntegration", integration.id, new_values={"success": True})
        flash("Daraja credentials are valid for the selected environment.", "success")
    except Exception as exc:
        db.session.rollback()
        audit("DARAJA_CONNECTION_TESTED", "PaymentIntegration", integration.id, new_values={"success": False, "error": exc.__class__.__name__})
        flash("Daraja connection test failed. Check the credentials, environment and network connection.", "error")
    return redirect(url_for("admin.settings"))


@bp.get(f"{ADMIN_BASE}/audit")
@admin_required()
def audit_page():
    q = (request.args.get("q") or "").strip()
    query = AuditLog.query.filter_by(business_id=current_user.business_id)
    if q:
        needle = f"%{q}%"
        query = query.filter(or_(AuditLog.action.ilike(needle), AuditLog.entity_type.ilike(needle), AuditLog.entity_id.ilike(needle)))
    logs = query.order_by(AuditLog.created_at.desc()).limit(500).all()
    return render_template("admin/audit.html", logs=logs, q=q)


@bp.route(f"{ADMIN_BASE}/system-errors", methods=["GET", "POST"])
@admin_required()
def system_errors():
    business_id = current_user.business_id
    if request.method == "POST":
        error_id = request.form.get("error_id") or ""
        row = db.session.get(SystemError, error_id)
        if row and row.business_id == business_id:
            row.resolved = True
            db.session.commit()
            audit("SYSTEM_ERROR_RESOLVED", "SystemError", row.id)
            flash("System error marked resolved.", "success")
        return redirect(url_for("admin.system_errors"))
    errors = SystemError.query.filter_by(business_id=business_id).order_by(SystemError.resolved.asc(), SystemError.created_at.desc()).limit(500).all()
    return render_template("admin/system_errors.html", errors=errors)


@bp.get(f"{ADMIN_BASE}/security")
@admin_required()
def security():
    business_id = current_user.business_id
    users = User.query.filter_by(business_id=business_id).all()
    logs = AuditLog.query.filter_by(business_id=business_id).order_by(AuditLog.created_at.desc()).limit(500).all()
    return render_template("admin/security.html", users=users, logs=logs)


@bp.get(f"{ADMIN_BASE}/backups")
@admin_required("backup.create")
def backups():
    latest = AuditLog.query.filter_by(business_id=current_user.business_id).filter(
        AuditLog.action.in_(["BACKUP_JSON_EXPORTED", "BACKUP_SQLITE_EXPORTED", "BACKUP_JSON_RESTORED", "BACKUP_SQLITE_RESTORED"])
    ).order_by(AuditLog.created_at.desc()).limit(40).all()
    return render_template("admin/backups.html", latest=latest)


@bp.get(f"{ADMIN_BASE}/export.json")
@admin_required("backup.create")
def export_json():
    payload = export_database_json()
    audit("BACKUP_JSON_EXPORTED", "Business", current_user.business_id, new_values={"format": "json"})
    raw = json.dumps(payload, ensure_ascii=False, indent=2, default=str).encode("utf-8")
    return send_file(BytesIO(raw), mimetype="application/json", as_attachment=True,
                     download_name=f"real-mart-backup-{now().strftime('%Y%m%d-%H%M%S')}.json")


@bp.get(f"{ADMIN_BASE}/export.sqlite")
@admin_required("backup.create")
def export_sqlite():
    import tempfile
    tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    tmp.close()
    path = Path(tmp.name)
    try:
        create_sqlite_snapshot(path)
        audit("BACKUP_SQLITE_EXPORTED", "Business", current_user.business_id, new_values={"format": "sqlite"})
        data = path.read_bytes()
        return send_file(BytesIO(data), mimetype="application/vnd.sqlite3", as_attachment=True,
                         download_name=f"real-mart-backup-{now().strftime('%Y%m%d-%H%M%S')}.sqlite")
    finally:
        try: path.unlink(missing_ok=True)
        except Exception: pass


@bp.post(f"{ADMIN_BASE}/restore/json")
@admin_required("backup.create")
def restore_json():
    upload = request.files.get("backup_file")
    if request.form.get("confirm") != "RESTORE" or not upload:
        flash("Choose a backup and confirm RESTORE before importing.", "error")
        return redirect(url_for("admin.backups"))
    try:
        payload = json.load(upload.stream)
        restore_database_json(payload)
        session.clear()
        flash("JSON backup restored. Sign in again with the restored credentials.", "success")
        return redirect("/control")
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("JSON restore failed")
        flash(f"Restore failed: {str(exc)[:220]}", "error")
        return redirect(url_for("admin.backups"))


@bp.post(f"{ADMIN_BASE}/restore/sqlite")
@admin_required("backup.create")
def restore_sqlite():
    import tempfile
    upload = request.files.get("backup_file")
    if request.form.get("confirm") != "RESTORE" or not upload:
        flash("Choose a backup and confirm RESTORE before importing.", "error")
        return redirect(url_for("admin.backups"))
    tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    path = Path(tmp.name)
    try:
        upload.save(path)
        restore_sqlite_snapshot(path)
        session.clear()
        flash("SQLite backup restored. Sign in again with the restored credentials.", "success")
        return redirect("/control")
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("SQLite restore failed")
        flash(f"Restore failed: {str(exc)[:220]}", "error")
        return redirect(url_for("admin.backups"))
    finally:
        try: path.unlink(missing_ok=True)
        except Exception: pass


@bp.get(f"{ADMIN_BASE}/reports")
@admin_required("reports.view")
def reports():
    business_id = current_user.business_id
    try:
        days = max(7, min(90, int(request.args.get("days", "30"))))
    except (TypeError, ValueError):
        days = 30
    since = now() - timedelta(days=days)
    daily = {}
    def day_row(key):
        return daily.setdefault(key, {"pos": Decimal("0"), "online": Decimal("0"), "mpesa": Decimal("0"), "cash": Decimal("0"), "card": Decimal("0"), "items": Decimal("0")})

    sale_daily = db.session.query(
        db.func.date(Sale.created_at),
        db.func.coalesce(db.func.sum(Sale.total), 0),
        db.func.coalesce(db.func.sum(SaleItem.quantity), 0),
    ).join(SaleItem, SaleItem.sale_id == Sale.id).filter(
        Sale.business_id == business_id, Sale.payment_status == "PAID", Sale.created_at >= since
    ).group_by(db.func.date(Sale.created_at)).all()
    for key, amount, items in sale_daily:
        d = day_row(str(key)); d["pos"] += Decimal(str(amount or 0)); d["items"] += Decimal(str(items or 0))

    order_daily = db.session.query(
        db.func.date(Order.created_at),
        db.func.coalesce(db.func.sum(Order.total), 0),
        db.func.coalesce(db.func.sum(OrderItem.quantity), 0),
    ).join(OrderItem, OrderItem.order_id == Order.id).filter(
        Order.business_id == business_id, Order.payment_status == "PAID", Order.created_at >= since
    ).group_by(db.func.date(Order.created_at)).all()
    for key, amount, items in order_daily:
        d = day_row(str(key)); d["online"] += Decimal(str(amount or 0)); d["items"] += Decimal(str(items or 0))

    payment_daily = db.session.query(
        db.func.date(Payment.created_at), Payment.method, db.func.coalesce(db.func.sum(Payment.amount), 0)
    ).filter(Payment.business_id == business_id, Payment.status == "PAID", Payment.created_at >= since).group_by(
        db.func.date(Payment.created_at), Payment.method
    ).all()
    for key, method, amount in payment_daily:
        d = day_row(str(key)); method = (method or "OTHER").upper(); amount = Decimal(str(amount or 0))
        if method in {"MPESA", "MPESA_TILL", "MPESA_GATEWAY", "MPESA_SMS"}: d["mpesa"] += amount
        elif method == "CASH": d["cash"] += amount
        elif method == "CARD": d["card"] += amount

    daily_rows = [{"date": k, **v, "total": v["pos"] + v["online"]} for k, v in sorted(daily.items(), reverse=True)]

    sales_product = db.session.query(
        SaleItem.product_id, SaleItem.product_name_snapshot,
        db.func.coalesce(db.func.sum(SaleItem.quantity), 0), db.func.coalesce(db.func.sum(SaleItem.line_total), 0)
    ).join(Sale, Sale.id == SaleItem.sale_id).filter(
        Sale.business_id == business_id, Sale.payment_status == "PAID", Sale.created_at >= since
    ).group_by(SaleItem.product_id, SaleItem.product_name_snapshot).all()
    order_product = db.session.query(
        OrderItem.product_id, OrderItem.product_name_snapshot,
        db.func.coalesce(db.func.sum(OrderItem.quantity), 0), db.func.coalesce(db.func.sum(OrderItem.line_total), 0)
    ).join(Order, Order.id == OrderItem.order_id).filter(
        Order.business_id == business_id, Order.payment_status == "PAID", Order.created_at >= since
    ).group_by(OrderItem.product_id, OrderItem.product_name_snapshot).all()
    top_products_map = {}
    for product_id, name, qty, amount in sales_product + order_product:
        key = product_id or name
        entry = top_products_map.setdefault(key, {"name": name, "qty": Decimal("0"), "sales": Decimal("0")})
        entry["qty"] += Decimal(str(qty or 0)); entry["sales"] += Decimal(str(amount or 0))
    top_products = sorted(top_products_map.values(), key=lambda x: x["sales"], reverse=True)[:15]

    return render_template("admin/reports.html", days=days, daily_rows=daily_rows, top_products=top_products,
                           total_sales=sum((r["total"] for r in daily_rows), Decimal("0")),
                           total_mpesa=sum((r["mpesa"] for r in daily_rows), Decimal("0")),
                           total_items=sum((r["items"] for r in daily_rows), Decimal("0")))

