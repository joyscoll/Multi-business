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
from flask import Blueprint, flash, redirect, render_template, request, url_for, Response, current_app, session, send_file
from flask_login import current_user, login_required
from extensions import db
from models import (Product, StoreProduct, PricingRule, PriceHistory, InventoryTransaction, User,
                    AuditLog, Sale, SaleItem, Order, Store, Business, Category, SystemError,
                    Payment, Expense, Role, PaymentIntegration, SystemSetting, Permission, Customer, ProductAlias, ProductImage,
                     PaymentGatewayEvent, LoyaltyAccount, LoyaltyTransaction, Shift, CashDrawerTransaction, now)
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
    business_id = current_user.business_id
    today = db.func.date(PaymentGatewayEvent.received_at) == db.func.current_date()
    q = PaymentGatewayEvent.query.filter_by(business_id=business_id)
    events = q.order_by(PaymentGatewayEvent.received_at.desc()).limit(30).all()
    received_q = q.filter(PaymentGatewayEvent.status.in_(["MATCHED", "UNMATCHED"]), today)
    matched_q = q.filter(PaymentGatewayEvent.status == "MATCHED", today)
    unmatched_q = q.filter(PaymentGatewayEvent.status == "UNMATCHED", today)
    stores = Store.query.filter_by(business_id=business_id).order_by(Store.name).all()

    store_totals = []
    for store in stores:
        total = q.filter(
            PaymentGatewayEvent.store_id == store.id,
            PaymentGatewayEvent.status.in_(["MATCHED", "UNMATCHED"]),
            today,
        ).with_entities(db.func.coalesce(db.func.sum(PaymentGatewayEvent.amount), 0)).scalar() or 0
        count = q.filter(
            PaymentGatewayEvent.store_id == store.id,
            PaymentGatewayEvent.status.in_(["MATCHED", "UNMATCHED"]),
            today,
        ).count()
        store_totals.append({"id": store.id, "name": store.name, "total": str(total), "count": count})

    def money(v):
        return str(v or 0)

    return jsonify(
        ok=True,
        received_total=money(received_q.with_entities(db.func.coalesce(db.func.sum(PaymentGatewayEvent.amount), 0)).scalar()),
        received_count=received_q.count(),
        matched_total=money(matched_q.with_entities(db.func.coalesce(db.func.sum(PaymentGatewayEvent.amount), 0)).scalar()),
        matched_count=matched_q.count(),
        unmatched_total=money(unmatched_q.with_entities(db.func.coalesce(db.func.sum(PaymentGatewayEvent.amount), 0)).scalar()),
        unmatched_count=unmatched_q.count(),
        last_received=(events[0].received_at.isoformat() if events else None),
        stores=store_totals,
        events=[
            {
                "id": e.id, "time": e.received_at.isoformat() if e.received_at else None,
                "sim": e.sim_slot + 1, "store": e.store.name if getattr(e, "store", None) else "Unassigned",
                "amount": money(e.amount), "customer": e.customer or "M-PESA customer",
                "transaction": e.transaction_id or "—", "status": e.status,
            } for e in events
        ],
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


@bp.post(f"{ADMIN_BASE}/stores/<store_id>/edit")
@admin_required("products.edit")
def edit_store(store_id):
    store = db.session.get(Store, store_id)
    if not store or store.business_id != current_user.business_id:
        return "Not found", 404
    code = request.form.get("code", "").strip().upper()
    duplicate = Store.query.filter(Store.business_id == current_user.business_id, Store.code == code, Store.id != store.id).first()
    if not request.form.get("name", "").strip() or not code or duplicate:
        flash("Mart name/code is required and the code must be unique.", "error")
        return redirect(url_for("admin.stores"))
    old = {"name": store.name, "code": store.code, "phone": store.phone, "address": store.address, "active": store.is_active}
    store.name = request.form.get("name").strip(); store.code = code; store.phone = request.form.get("phone", "").strip() or None; store.address = request.form.get("address", "").strip() or None
    store.latitude = float(request.form.get("latitude")) if request.form.get("latitude", "").strip() else None
    store.longitude = float(request.form.get("longitude")) if request.form.get("longitude", "").strip() else None
    store.is_active = request.form.get("active") == "1"
    db.session.commit(); audit("STORE_UPDATED", "Store", store.id, old_values=old, new_values={"name":store.name,"code":store.code,"active":store.is_active})
    flash(f"{store.name} updated.", "success")
    return redirect(url_for("admin.stores"))


@bp.post(f"{ADMIN_BASE}/stores/<store_id>/delete")
@admin_required("products.delete")
def delete_store(store_id):
    store = db.session.get(Store, store_id)
    if not store or store.business_id != current_user.business_id:
        return "Not found", 404
    if store.id == current_user.store_id:
        flash("You cannot delete the mart currently assigned to your account.", "error")
        return redirect(url_for("admin.stores"))
    refs = Sale.query.filter_by(store_id=store.id).count() + Order.query.filter_by(store_id=store.id).count() + InventoryTransaction.query.filter_by(store_id=store.id).count()
    if refs:
        store.is_active = False; db.session.commit(); audit("STORE_ARCHIVED", "Store", store.id, new_values={"references":refs})
        flash(f"{store.name} was deactivated because it has transaction history.", "success")
    else:
        db.session.delete(store); db.session.commit(); audit("STORE_DELETED", "Store", store_id)
        flash("Mart deleted.", "success")
    return redirect(url_for("admin.stores"))


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
    latest = AuditLog.query.filter_by(business_id=current_user.business_id, action="DATABASE_BACKUP_CREATED").order_by(AuditLog.created_at.desc()).limit(25).all()
    return render_template("admin/backups.html", latest=latest)


@bp.get(f"{ADMIN_BASE}/export.json")
@admin_required("backup.create")
def export_json():
    payload = export_database_json()
    audit("DATABASE_BACKUP_CREATED", "Business", current_user.business_id, new_values={"format": "json"})
    return Response(json.dumps(payload, default=str), mimetype="application/json",
                    headers={"Content-Disposition": "attachment; filename=denmart-backup.json"})


@bp.get(f"{ADMIN_BASE}/export.sqlite")
@admin_required("backup.create")
def export_sqlite():
    from tempfile import NamedTemporaryFile
    with NamedTemporaryFile(suffix=".sqlite", delete=False) as fh:
        path = fh.name
    try:
        create_sqlite_snapshot(path)
        data = Path(path).read_bytes()
    finally:
        Path(path).unlink(missing_ok=True)
    audit("DATABASE_BACKUP_CREATED", "Business", current_user.business_id, new_values={"format": "sqlite"})
    return send_file(
        BytesIO(data),
        mimetype="application/x-sqlite3",
        as_attachment=True,
        download_name="denmart-backup.sqlite",
        max_age=0,
    )


@bp.post(f"{ADMIN_BASE}/restore/json")
@admin_required("backup.restore")
def restore_json():
    upload = request.files.get("backup_file")
    if request.form.get("confirm") != "RESTORE" or not upload or not upload.filename.lower().endswith(".json"):
        flash("Choose a Denmart JSON backup file.", "error")
        return redirect(url_for("admin.backups"))
    try:
        payload = json.loads(upload.read().decode("utf-8"))
        restore_database_json(payload)
        from flask_login import logout_user
        logout_user()
        session.clear()
        flash("JSON backup restored. Sign in again to continue.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(f"JSON restore failed: {exc}", "error")
    return redirect(url_for("admin.backups"))


@bp.post(f"{ADMIN_BASE}/restore/sqlite")
@admin_required("backup.restore")
def restore_sqlite():
    upload = request.files.get("backup_file")
    if request.form.get("confirm") != "RESTORE" or not upload or not upload.filename.lower().endswith((".sqlite", ".db")):
        flash("Choose a Denmart SQLite backup file.", "error")
        return redirect(url_for("admin.backups"))
    from tempfile import NamedTemporaryFile
    with NamedTemporaryFile(suffix=".sqlite", delete=False) as fh:
        path = fh.name
        upload.save(path)
    try:
        restore_sqlite_snapshot(path)
        from flask_login import logout_user
        logout_user()
        session.clear()
        flash("SQLite backup restored. Sign in again to continue.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(f"SQLite restore failed: {exc}", "error")
    finally:
        Path(path).unlink(missing_ok=True)
    return redirect(url_for("admin.backups"))


@bp.post(f"{ADMIN_BASE}/settings/test-daraja")
@admin_required("reports.view")
def test_daraja():
    business = db.session.get(Business, current_user.business_id)
    integration = PaymentIntegration.query.filter_by(business_id=business.id, provider="SAFARICOM").first()
    if not integration:
        flash("Save the Daraja credentials first.", "error")
        return redirect(url_for("admin.settings"))
    try:
        from services.payments.daraja import DarajaProvider
        provider = DarajaProvider(decrypt(integration.consumer_key_encrypted) or "", decrypt(integration.consumer_secret_encrypted) or "",
                                   decrypt(integration.shortcode_encrypted) or "", decrypt(integration.passkey_encrypted) or "",
                                   integration.environment or "sandbox", integration.callback_url or "")
        provider.access_token()
        integration.last_tested_at = now()
        db.session.commit()
        flash("Daraja credentials accepted by the selected environment.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(f"Daraja connection test failed: {exc}", "error")
    return redirect(url_for("admin.settings"))


@bp.get(f"{ADMIN_BASE}/audit")
@admin_required("reports.view")
def audit_page():
    logs = AuditLog.query.filter_by(business_id=current_user.business_id).order_by(AuditLog.created_at.desc()).limit(500).all()
    return render_template("admin/audit.html", logs=logs)


@bp.post(f"{ADMIN_BASE}/settings/till")
@admin_required("reports.view")
def save_till():
    business = db.session.get(Business, current_user.business_id)
    till_number = request.form.get("till_number", "").strip()
    setting = SystemSetting.query.filter_by(business_id=business.id, key="mpesa_till_number").first()
    if till_number:
        if not till_number.isdigit() or not (5 <= len(till_number) <= 10):
            flash("Enter a valid M-PESA Till number.", "error")
            return redirect(url_for("admin.settings"))
        if not setting:
            setting = SystemSetting(business_id=business.id, key="mpesa_till_number", value=till_number)
            db.session.add(setting)
        else:
            setting.value = till_number
        db.session.commit()
        flash("M-PESA Till number saved.", "success")
    else:
        if setting:
            db.session.delete(setting)
            db.session.commit()
        flash("M-PESA Till number cleared.", "success")
    return redirect(url_for("admin.settings"))


@bp.get(f"{ADMIN_BASE}/settings")
@bp.post(f"{ADMIN_BASE}/settings")
@admin_required("reports.view")
def settings():
    business = db.session.get(Business, current_user.business_id)
    integration = PaymentIntegration.query.filter_by(business_id=business.id, provider="SAFARICOM").first()
    if request.method == "POST":
        business.name = request.form.get("business_name", business.name).strip() or business.name
        footer = request.form.get("footer_text", "All rights reserved · Denmart Merchants").strip()
        logo_file = request.files.get("business_logo")
        if logo_file and logo_file.filename:
            raw_logo = logo_file.read(2 * 1024 * 1024 + 1)
            try:
                if len(raw_logo) > 2 * 1024 * 1024:
                    raise ValueError("Logo is larger than 2 MB.")
                image = Image.open(BytesIO(raw_logo))
                if image.format not in {"PNG", "JPEG", "WEBP", "GIF"}:
                    raise ValueError("Use a PNG, JPG, WEBP or GIF logo.")
                image = image.convert("RGBA")
                image.thumbnail((768, 768), Image.Resampling.LANCZOS)
                out = BytesIO()
                image.save(out, format="PNG", optimize=True)
                encoded = base64.b64encode(out.getvalue()).decode("ascii")
                if len(encoded) > 1_500_000:
                    raise ValueError("Logo is still too large after optimization; use a smaller image.")
                business.logo_url = f"data:image/png;base64,{encoded}"
                flash("Business logo updated. The same logo will be used for the PWA app icon.", "success")
            except Exception as exc:
                flash(str(exc), "error")
        if request.form.get("remove_logo") == "1":
            business.logo_url = None
            flash("Business logo removed; the default Denmart app icon will be used.", "success")
        setting = SystemSetting.query.filter_by(business_id=business.id, key="footer_text").first()
        if not setting:
            setting = SystemSetting(business_id=business.id, key="footer_text", value=footer); db.session.add(setting)
        else: setting.value = footer
        def save_setting(key, value):
            setting = SystemSetting.query.filter_by(business_id=business.id, key=key).first()
            if not setting:
                db.session.add(SystemSetting(business_id=business.id, key=key, value=str(value)))
            else:
                setting.value = str(value)
        if any(k in request.form for k in ("delivery_enabled", "bike_base_fee", "bike_per_km")):
            try:
                bike_base = Decimal(request.form.get("bike_base_fee", "100"))
                bike_km = Decimal(request.form.get("bike_per_km", "20"))
                if bike_base < 0 or bike_km < 0: raise InvalidOperation
                save_setting("delivery_bike_base_fee", bike_base)
                save_setting("delivery_bike_per_km", bike_km)
                save_setting("delivery_enabled", "1" if request.form.get("delivery_enabled") == "1" else "0")
            except InvalidOperation:
                flash("Delivery fees must be valid non-negative amounts.", "error")
        if "loyalty_points_per_100" in request.form:
            try:
                points_rate = max(0, int(request.form.get("loyalty_points_per_100", "1")))
                save_setting("loyalty_points_per_100", points_rate)
            except (TypeError, ValueError):
                flash("Loyalty points rate must be a whole number.", "error")
        if request.form.get("save_mpesa"):
            if not integration:
                integration = PaymentIntegration(business_id=business.id, provider="SAFARICOM")
                db.session.add(integration)
            integration.environment = request.form.get("environment", "sandbox")
            integration.callback_url = request.form.get("callback_url", "").strip() or url_for("api.mpesa_callback", _external=True)
            requested_active = request.form.get("mpesa_active") == "1"
            required = [request.form.get("consumer_key", "").strip() or decrypt(integration.consumer_key_encrypted or ""),
                        request.form.get("consumer_secret", "").strip() or decrypt(integration.consumer_secret_encrypted or ""),
                        request.form.get("shortcode", "").strip() or decrypt(integration.shortcode_encrypted or ""),
                        request.form.get("passkey", "").strip() or decrypt(integration.passkey_encrypted or "")]
            transaction_type = request.form.get("transaction_type", "CustomerPayBillOnline")
            integration.is_active = requested_active and all(required) and integration.callback_url.startswith("https://")
            extra = {"transaction_type": transaction_type}
            for field, form_name in [("consumer_key_encrypted","consumer_key"),("consumer_secret_encrypted","consumer_secret"),("shortcode_encrypted","shortcode"),("passkey_encrypted","passkey")]:
                value = request.form.get(form_name, "").strip()
                if value: setattr(integration, field, encrypt(value))
            integration.other_credentials_encrypted = encrypt(json.dumps(extra))
        db.session.commit()
        if request.form.get("save_mpesa") and request.form.get("mpesa_active") == "1" and not integration.is_active:
            flash("M-PESA was saved but remains inactive until all credentials and a public HTTPS callback URL are present.", "error")
        else:
            flash("Settings saved.", "success")
    setting = SystemSetting.query.filter_by(business_id=business.id, key="footer_text").first()
    callback = integration.callback_url if integration and integration.callback_url else url_for("api.mpesa_callback", _external=True)
    transaction_type = "CustomerPayBillOnline"
    till_number = ""
    if integration and integration.other_credentials_encrypted:
        try:
            extra = json.loads(decrypt(integration.other_credentials_encrypted) or "{}")
            transaction_type = extra.get("transaction_type", transaction_type)
        except Exception:
            pass
    till_setting = SystemSetting.query.filter_by(business_id=business.id, key="mpesa_till_number").first()
    till_number = str(till_setting.value or "").strip() if till_setting else ""
    bike_base_setting = SystemSetting.query.filter_by(business_id=business.id, key="delivery_bike_base_fee").first()
    bike_km_setting = SystemSetting.query.filter_by(business_id=business.id, key="delivery_bike_per_km").first()
    delivery_setting = SystemSetting.query.filter_by(business_id=business.id, key="delivery_enabled").first()
    loyalty_setting = SystemSetting.query.filter_by(business_id=business.id, key="loyalty_points_per_100").first()
    return render_template("admin/settings.html", business=business, integration=integration,
                           footer_text=setting.value if setting else "All rights reserved · Denmart Merchants",
                           callback_url=callback, transaction_type=transaction_type, till_number=till_number,
                           bike_base_fee=bike_base_setting.value if bike_base_setting else "100",
                           bike_per_km=bike_km_setting.value if bike_km_setting else "20",
                           delivery_enabled=(delivery_setting.value if delivery_setting else "1") == "1",
                           loyalty_points_per_100=loyalty_setting.value if loyalty_setting else "1")
