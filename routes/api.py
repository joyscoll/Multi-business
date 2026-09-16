from decimal import Decimal
from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user, login_required
from extensions import csrf
from extensions import db
from models import Product, StoreProduct, Payment, Sale, SaleItem, Order, OrderItem, InventoryTransaction, now
from services.payments.daraja import DarajaProvider

bp = Blueprint("api", __name__, url_prefix="/api")

@bp.get("/products/search")
def product_search():
    q = request.args.get("q", "").strip()
    store_id = request.args.get("store_id")
    query = StoreProduct.query.join(Product).filter(StoreProduct.is_available.is_(True))
    if store_id:
        query = query.filter(StoreProduct.store_id == store_id)
    if q:
        like = f"%{q}%"
        query = query.filter((Product.name.ilike(like)) | (Product.barcode.ilike(like)) | (Product.sku.ilike(like)) | (Product.brand.ilike(like)) | (Product.search_keywords.ilike(like)))
    rows = query.order_by(Product.name).limit(30).all()
    return jsonify(items=[{"id": r.id, "product_id": r.product_id, "name": r.product.name, "barcode": r.product.barcode,
                           "price": str(r.selling_price), "stock": str(r.stock_quantity), "image_url": r.product.image_url} for r in rows])

@bp.get("/products/barcode/<barcode>")
def barcode(barcode):
    store_id = request.args.get("store_id") or (current_user.store_id if current_user.is_authenticated else None)
    query = StoreProduct.query.join(Product).filter(Product.barcode == barcode, StoreProduct.is_available.is_(True))
    if store_id: query = query.filter(StoreProduct.store_id == store_id)
    row = query.first()
    if not row: return jsonify(error="product_not_found"), 404
    return jsonify(id=row.id, product_id=row.product_id, name=row.product.name, barcode=row.product.barcode, price=str(row.selling_price), stock=str(row.stock_quantity))

@csrf.exempt

@bp.post("/orders")
def create_order():
    data = request.get_json(silent=True) or {}
    store_id = data.get("store_id")
    if not store_id:
        from models import Store
        store = Store.query.filter_by(is_active=True).order_by(Store.created_at).first()
        store_id = store.id if store else None
    if not store_id:
        return jsonify(error="store_unavailable"), 503
    items = data.get("items", [])
    if not items:
        return jsonify(error="cart_empty"), 400
    store_product_rows = []
    subtotal = Decimal("0")
    for raw in items:
        sp = db.session.get(StoreProduct, raw.get("store_product_id"))
        qty = Decimal(str(raw.get("quantity", 0)))
        if not sp or sp.store_id != store_id or not sp.available_online or qty <= 0:
            return jsonify(error="invalid_item"), 400
        available = Decimal(sp.stock_quantity or 0) - Decimal(sp.reserved_quantity or 0)
        if available < qty:
            return jsonify(error="insufficient_stock", product=sp.product.name), 409
        line = Decimal(sp.selling_price) * qty
        subtotal += line
        store_product_rows.append((sp, qty, line))
    from models import Business
    business = db.session.get(Business, store_product_rows[0][0].store.business_id)
    order_number = f"RM-{now().strftime('%Y%m%d')}-{Order.query.count()+1:05d}"
    order = Order(business_id=business.id, store_id=store_id, order_number=order_number, subtotal=subtotal, total=subtotal,
                  delivery_address=data.get("delivery_address"), delivery_notes=data.get("delivery_notes"))
    db.session.add(order); db.session.flush()
    for sp, qty, line in store_product_rows:
        sp.reserved_quantity = Decimal(sp.reserved_quantity or 0) + qty
        db.session.add(OrderItem(order_id=order.id, product_id=sp.product_id, product_name_snapshot=sp.product.name,
                                 sku_snapshot=sp.product.sku, unit_price=sp.selling_price, quantity=qty, line_total=line))
    db.session.commit()
    return jsonify(ok=True, order_id=order.id, order_number=order_number, total=str(order.total), payment_status=order.payment_status)

@bp.post("/payments/mpesa/initiate")
@bp.post("/payments/daraja/initiate")
@login_required
def mpesa_initiate():
    data = request.get_json(silent=True) or {}
    amount = Decimal(str(data.get("amount", 0)))
    phone = data.get("phone_number", "").strip()
    sale_id = data.get("sale_id")
    order_id = data.get("order_id")
    if amount <= 0 or not phone: return jsonify(error="amount_and_phone_required"), 400
    if not sale_id and not order_id: return jsonify(error="sale_or_order_required"), 400
    entity = db.session.get(Sale, sale_id) if sale_id else db.session.get(Order, order_id)
    if not entity or entity.store_id != current_user.store_id: return jsonify(error="entity_not_found"), 404
    payment = Payment(business_id=current_user.business_id, store_id=current_user.store_id, sale_id=sale_id, order_id=order_id,
                      provider="SAFARICOM", method="MPESA", amount=amount, currency=current_app.config["CURRENCY"], status="PENDING", phone_number=phone)
    db.session.add(payment); db.session.flush()
    provider = DarajaProvider(current_app.config["DARAJA_CONSUMER_KEY"], current_app.config["DARAJA_CONSUMER_SECRET"], current_app.config["DARAJA_SHORTCODE"], current_app.config["DARAJA_PASSKEY"], current_app.config["DARAJA_ENV"], current_app.config["DARAJA_CALLBACK_URL"])
    try:
        response = provider.initiate_payment(amount=amount, phone_number=phone, account_reference=(entity.receipt_number if sale_id else entity.order_number), transaction_desc="REAL MART purchase")
    except Exception as exc:
        db.session.delete(payment); db.session.commit()
        return jsonify(error="daraja_request_failed", detail=str(exc)), 502
    payment.merchant_request_id = response.get("MerchantRequestID")
    payment.checkout_request_id = response.get("CheckoutRequestID")
    payment.external_reference = response.get("CustomerMessage")
    db.session.commit()
    return jsonify(ok=True, payment_id=payment.id, status="PENDING", provider_response=response)

@csrf.exempt
@bp.post("/payments/mpesa/callback")
@bp.post("/payments/daraja/callback")
def mpesa_callback():
    payload = request.get_json(silent=True) or {}
    provider = DarajaProvider("", "", "", "", current_app.config["DARAJA_ENV"], current_app.config["DARAJA_CALLBACK_URL"])
    result = provider.handle_callback(payload)
    payment = None
    if result.get("checkout_request_id"):
        payment = Payment.query.filter_by(checkout_request_id=result["checkout_request_id"]).first()
    if not payment:
        return jsonify(ResultCode=0, ResultDesc="Accepted"), 200
    if payment.status in {"PAID", "FAILED"}:
        return jsonify(ResultCode=0, ResultDesc="Already processed"), 200
    if result.get("result_code") == 0:
        callback_amount = Decimal(str(result.get("amount", payment.amount))) if result.get("amount") is not None else Decimal(payment.amount)
        if callback_amount != Decimal(payment.amount):
            payment.status = "FAILED"
            payment.failure_message = "Provider amount did not match the recorded payment amount"
        else:
            payment.status = "PAID"
            payment.provider_transaction_id = result.get("receipt")
            payment.completed_at = now()
            if payment.sale_id:
                sale = db.session.get(Sale, payment.sale_id)
                if sale:
                    sale.status = "COMPLETED"; sale.payment_status = "PAID"; sale.completed_at = now()
                    for line in SaleItem.query.filter_by(sale_id=sale.id).all():
                        sp = StoreProduct.query.filter_by(store_id=sale.store_id, product_id=line.product_id).first()
                        if sp:
                            qty = Decimal(line.quantity)
                            sp.stock_quantity = Decimal(sp.stock_quantity or 0) - qty
                            db.session.add(InventoryTransaction(store_id=sale.store_id, product_id=line.product_id, transaction_type="SALE", quantity=-qty, unit_cost=sp.cost_price, reference_type="SALE", reference_id=sale.id))
            if payment.order_id:
                order = db.session.get(Order, payment.order_id)
                if order:
                    order.payment_status = "PAID"; order.status = "CONFIRMED"
                    for line in OrderItem.query.filter_by(order_id=order.id).all():
                        sp = StoreProduct.query.filter_by(store_id=order.store_id, product_id=line.product_id).first()
                        if sp:
                            qty = Decimal(line.quantity)
                            sp.reserved_quantity = max(Decimal("0"), Decimal(sp.reserved_quantity or 0) - qty)
                            sp.stock_quantity = Decimal(sp.stock_quantity or 0) - qty
                            db.session.add(InventoryTransaction(store_id=order.store_id, product_id=line.product_id, transaction_type="SALE", quantity=-qty, unit_cost=sp.cost_price, reference_type="ORDER", reference_id=order.id))
    else:
        payment.status = "FAILED"
        payment.failure_message = result.get("result_desc")
        if payment.sale_id:
            sale = db.session.get(Sale, payment.sale_id); sale.payment_status = "FAILED" if sale else "FAILED"
    payment.raw_provider_reference = str(payload)
    db.session.commit()
    return jsonify(ResultCode=0, ResultDesc="Accepted"), 200

@csrf.exempt
@bp.post("/sync/offline")
@login_required
def sync_offline():
    data = request.get_json(silent=True) or {}
    # Offline sync needs server-side validation/idempotency; this endpoint only acknowledges the envelope in v1.
    operations = data.get("operations", [])
    return jsonify(ok=True, accepted=len(operations), note="Process queued operations through /api/pos/sales with client_operation_id enforcement before production offline sync is enabled")
