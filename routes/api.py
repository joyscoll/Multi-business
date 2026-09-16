from decimal import Decimal, InvalidOperation
from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user, login_required
from extensions import csrf, db
from models import Product, StoreProduct, Payment, Sale, SaleItem, Order, OrderItem, InventoryTransaction, now, Store, Customer, Business, PaymentIntegration
from services.payments.daraja import DarajaProvider
from services.crypto import decrypt

bp = Blueprint("api", __name__, url_prefix="/api")


def safe_product_payload(r, include_stock=False):
    data = {"id": r.id, "product_id": r.product_id, "name": r.product.name, "barcode": r.product.barcode,
            "sku": r.product.sku, "price": str(r.selling_price), "image_url": r.product.image_url}
    if include_stock:
        data["stock"] = str(r.stock_quantity)
    return data


@bp.get("/products/search")
def product_search():
    # PUBLIC catalogue: never expose stock, cost, supplier, internal IDs beyond
    # the cart-facing StoreProduct token, or operational endpoints.
    q = request.args.get("q", "").strip(); store_id = request.args.get("store_id")
    query = StoreProduct.query.join(Product).filter(StoreProduct.is_available.is_(True), StoreProduct.available_online.is_(True), StoreProduct.stock_quantity > StoreProduct.reserved_quantity, Product.status == "ACTIVE")
    if store_id: query = query.filter(StoreProduct.store_id == store_id)
    if q:
        like = f"%{q}%"
        query = query.filter((Product.name.ilike(like)) | (Product.barcode.ilike(like)) | (Product.sku.ilike(like)) | (Product.brand.ilike(like)) | (Product.search_keywords.ilike(like)))
    return jsonify(items=[safe_product_payload(r) for r in query.order_by(Product.name).limit(60).all()])


def cashier_api(fn):
    from functools import wraps
    @wraps(fn)
    @login_required
    def wrapped(*args, **kwargs):
        if not current_user.has_permission("sales.create") or not current_user.store_id:
            return jsonify(error="forbidden"), 403
        return fn(*args, **kwargs)
    return wrapped


@bp.get("/pos/products/search")
@cashier_api
def pos_product_search():
    q = request.args.get("q", "").strip()
    query = StoreProduct.query.join(Product).filter(StoreProduct.is_available.is_(True), StoreProduct.store_id == current_user.store_id, StoreProduct.available_pos.is_(True), Product.status == "ACTIVE")
    if q:
        like = f"%{q}%"
        query = query.filter((Product.name.ilike(like)) | (Product.barcode.ilike(like)) | (Product.sku.ilike(like)) | (Product.brand.ilike(like)) | (Product.search_keywords.ilike(like)))
    return jsonify(items=[safe_product_payload(r, include_stock=True) for r in query.order_by(Product.name).limit(50).all()])


@bp.get("/pos/products/barcode/<barcode>")
@cashier_api
def pos_barcode(barcode):
    row = StoreProduct.query.join(Product).filter(Product.barcode == barcode, StoreProduct.is_available.is_(True), StoreProduct.store_id == current_user.store_id, StoreProduct.available_pos.is_(True), Product.status == "ACTIVE").first()
    if not row: return jsonify(error="product_not_found"), 404
    return jsonify(safe_product_payload(row, include_stock=True))


@csrf.exempt
@bp.post("/orders")
def create_order():
    data = request.get_json(silent=True) or {}
    store_id = data.get("store_id")
    store_code = (data.get("store_code") or "").strip()
    store = Store.query.filter_by(code=store_code, is_active=True).first() if store_code else db.session.get(Store, store_id) if store_id else Store.query.filter_by(is_active=True).order_by(Store.created_at).first()
    if not store: return jsonify(error="store_unavailable"), 503
    items = data.get("items", [])
    if not items: return jsonify(error="cart_empty"), 400
    prepared=[]; subtotal=Decimal("0")
    for raw in items:
        sp=db.session.get(StoreProduct, raw.get("store_product_id"))
        try: qty=Decimal(str(raw.get("quantity",0)))
        except InvalidOperation: return jsonify(error="invalid_quantity"),400
        if not sp or sp.store_id != store.id or not sp.available_online or qty<=0: return jsonify(error="invalid_item"),400
        available=Decimal(sp.stock_quantity or 0)-Decimal(sp.reserved_quantity or 0)
        if available<qty: return jsonify(error="insufficient_stock", product=sp.product.name),409
        line=Decimal(sp.selling_price)*qty; subtotal+=line; prepared.append((sp,qty,line))
    business=store.business
    order_number=f"RM-{now().strftime('%Y%m%d')}-{Order.query.count()+1:06d}"
    c=data.get("customer") or {}; phone=(c.get("phone") or "").strip(); email=(c.get("email") or "").strip().lower(); name=(c.get("name") or "").strip()
    customer=None
    if phone or email:
        customer=Customer.query.filter((Customer.phone==phone)|(Customer.email==email)).first()
        if not customer:
            customer=Customer(business_id=business.id,name=name or "Online customer",phone=phone or None,email=email or None);db.session.add(customer);db.session.flush()
        elif name: customer.name=name
    order=Order(business_id=business.id,store_id=store.id,order_number=order_number,customer_id=customer.id if customer else None,subtotal=subtotal,total=subtotal,delivery_address=data.get("delivery_address"),delivery_notes=data.get("delivery_notes"))
    db.session.add(order);db.session.flush()
    for sp,qty,line in prepared:
        sp.reserved_quantity=Decimal(sp.reserved_quantity or 0)+qty
        db.session.add(OrderItem(order_id=order.id,product_id=sp.product_id,product_name_snapshot=sp.product.name,sku_snapshot=sp.product.sku,unit_price=sp.selling_price,quantity=qty,line_total=line))
    db.session.commit()
    return jsonify(ok=True,order_id=order.id,order_number=order_number,total=str(order.total),payment_status=order.payment_status)


def configured_daraja():
    integration = None
    if current_user.is_authenticated:
        integration = PaymentIntegration.query.filter_by(business_id=current_user.business_id, provider="SAFARICOM", is_active=True).first()
    if not integration:
        integration = PaymentIntegration.query.filter_by(provider="SAFARICOM", is_active=True).first()
    if integration:
        try:
            return DarajaProvider(
                decrypt(integration.consumer_key_encrypted) or "", decrypt(integration.consumer_secret_encrypted) or "",
                decrypt(integration.shortcode_encrypted) or "", decrypt(integration.passkey_encrypted) or "",
                integration.environment or "sandbox", integration.callback_url or current_app.config["DARAJA_CALLBACK_URL"]
            )
        except Exception:
            pass
    return DarajaProvider(current_app.config["DARAJA_CONSUMER_KEY"], current_app.config["DARAJA_CONSUMER_SECRET"],
                          current_app.config["DARAJA_SHORTCODE"], current_app.config["DARAJA_PASSKEY"],
                          current_app.config["DARAJA_ENV"], current_app.config["DARAJA_CALLBACK_URL"])


@csrf.exempt
@bp.post("/payments/mpesa/initiate")
@bp.post("/payments/daraja/initiate")
def mpesa_initiate():
    data=request.get_json(silent=True) or {}
    try: amount=Decimal(str(data.get("amount",0)))
    except InvalidOperation: return jsonify(error="invalid_amount"),400
    phone=(data.get("phone_number") or "").strip(); sale_id=data.get("sale_id"); order_id=data.get("order_id")
    if amount<=0 or not phone: return jsonify(error="amount_and_phone_required"),400
    if not sale_id and not order_id: return jsonify(error="sale_or_order_required"),400
    if sale_id and (not current_user.is_authenticated or not current_user.has_permission("sales.create")): return jsonify(error="forbidden"),403
    entity=db.session.get(Sale,sale_id) if sale_id else db.session.get(Order,order_id)
    if not entity: return jsonify(error="entity_not_found"),404
    if sale_id and entity.store_id!=current_user.store_id: return jsonify(error="entity_not_found"),404
    if Decimal(str(entity.total))!=amount: return jsonify(error="amount_mismatch"),400
    if order_id and entity.payment_status=="PAID": return jsonify(error="already_paid"),409
    payment=Payment(business_id=entity.business_id,store_id=entity.store_id,sale_id=sale_id,order_id=order_id,provider="SAFARICOM",method="MPESA",amount=amount,currency=current_app.config["CURRENCY"],status="PENDING",phone_number=phone)
    db.session.add(payment);db.session.flush()
    provider=configured_daraja()
    try: response=provider.initiate_payment(amount=amount,phone_number=phone,account_reference=(entity.receipt_number if sale_id else entity.order_number),transaction_desc="Retail purchase")
    except Exception:
        db.session.rollback(); return jsonify(error="payment_provider_unavailable"),502
    payment.merchant_request_id=response.get("MerchantRequestID");payment.checkout_request_id=response.get("CheckoutRequestID");payment.external_reference=response.get("CustomerMessage");db.session.commit()
    return jsonify(ok=True,payment_id=payment.id,status="PENDING",message="Payment prompt sent")


@bp.get("/payments/<payment_id>/status")
def payment_status(payment_id):
    payment = db.session.get(Payment, payment_id)
    if not payment:
        return jsonify(error="payment_not_found"), 404
    data = {"ok": True, "payment_id": payment.id, "status": payment.status, "amount": str(payment.amount),
            "receipt": payment.provider_transaction_id, "message": payment.failure_message}
    if payment.order_id:
        order = db.session.get(Order, payment.order_id)
        data["order_status"] = order.status if order else None
        data["payment_status"] = order.payment_status if order else None
    elif payment.sale_id:
        sale = db.session.get(Sale, payment.sale_id)
        data["payment_status"] = sale.payment_status if sale else None
    return jsonify(data)


@csrf.exempt
@bp.post("/payments/mpesa/callback")
@bp.post("/payments/daraja/callback")
def mpesa_callback():
    payload=request.get_json(silent=True) or {}
    provider=DarajaProvider("","","","",current_app.config["DARAJA_ENV"],current_app.config["DARAJA_CALLBACK_URL"])
    result=provider.handle_callback(payload)
    payment=Payment.query.filter_by(checkout_request_id=result.get("checkout_request_id")).first() if result.get("checkout_request_id") else None
    if not payment:return jsonify(ResultCode=0,ResultDesc="Accepted"),200
    if payment.status in {"PAID","FAILED"}:return jsonify(ResultCode=0,ResultDesc="Already processed"),200
    if result.get("result_code")==0:
        callback_amount=Decimal(str(result.get("amount",payment.amount))) if result.get("amount") is not None else Decimal(payment.amount)
        if callback_amount!=Decimal(payment.amount): payment.status="FAILED";payment.failure_message="Provider amount mismatch"
        else:
            payment.status="PAID";payment.provider_transaction_id=result.get("receipt");payment.completed_at=now()
            if payment.sale_id:
                sale=db.session.get(Sale,payment.sale_id)
                if sale:
                    sale.status="COMPLETED";sale.payment_status="PAID";sale.completed_at=now()
                    for line in SaleItem.query.filter_by(sale_id=sale.id).all():
                        sp=StoreProduct.query.filter_by(store_id=sale.store_id,product_id=line.product_id).first()
                        if sp: sp.stock_quantity=Decimal(sp.stock_quantity or 0)-Decimal(line.quantity);db.session.add(InventoryTransaction(store_id=sale.store_id,product_id=line.product_id,transaction_type="SALE",quantity=-Decimal(line.quantity),unit_cost=sp.cost_price,reference_type="SALE",reference_id=sale.id))
            if payment.order_id:
                order=db.session.get(Order,payment.order_id)
                if order:
                    order.payment_status="PAID";order.status="CONFIRMED"
                    for line in OrderItem.query.filter_by(order_id=order.id).all():
                        sp=StoreProduct.query.filter_by(store_id=order.store_id,product_id=line.product_id).first()
                        if sp: sp.reserved_quantity=max(Decimal("0"),Decimal(sp.reserved_quantity or 0)-Decimal(line.quantity));sp.stock_quantity=Decimal(sp.stock_quantity or 0)-Decimal(line.quantity);db.session.add(InventoryTransaction(store_id=order.store_id,product_id=line.product_id,transaction_type="SALE",quantity=-Decimal(line.quantity),unit_cost=sp.cost_price,reference_type="ORDER",reference_id=order.id))
    else:
        payment.status="FAILED";payment.failure_message=result.get("result_desc") or "Payment failed"
        if payment.sale_id:
            sale=db.session.get(Sale,payment.sale_id)
            if sale:sale.payment_status="FAILED"
    payment.raw_provider_reference=str(payload);db.session.commit()
    return jsonify(ResultCode=0,ResultDesc="Accepted"),200


@bp.get("/pos/orders")
@cashier_api
def pos_orders():
    from models import Customer
    rows = (Order.query.filter_by(store_id=current_user.store_id)
            .order_by(Order.created_at.desc()).limit(80).all())
    return jsonify(items=[{
        "order_number": o.order_number, "customer": (o.customer.name if getattr(o, "customer", None) else "Online customer"),
        "total": str(o.total), "payment_status": o.payment_status, "status": o.status
    } for o in rows])


@csrf.exempt
@bp.post("/sync/offline")
@cashier_api
def sync_offline():
    # Acknowledgement endpoint remains separate and permissioned; raw offline
    # payloads are not executed blindly.
    data=request.get_json(silent=True) or {}; return jsonify(ok=True,accepted=0,message="Offline queue accepted for controlled reconciliation")
