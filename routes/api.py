from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta, timezone
import json
import re
from flask import Blueprint, current_app, jsonify, request, session
from flask_login import current_user, login_required
from extensions import csrf, db
from models import (Product, ProductAlias, StoreProduct, Payment, Sale, SaleItem, Order, OrderItem,
                    InventoryTransaction, now, Store, Customer, Business, PaymentIntegration,
                    SystemSetting, PaymentGatewayEvent)
from services.search import forgiving_rank
from services.payments.daraja import DarajaProvider
from services.payments.settlement import order_received_total, order_outstanding, sale_received_total, sale_outstanding, settle_gateway_order_payment, settle_gateway_sale_payment
from services.crypto import decrypt
from services.loyalty import award_purchase_points

bp = Blueprint("api", __name__, url_prefix="/api")


def safe_product_payload(r, include_stock=False):
    data = {"id": r.id, "product_id": r.product_id, "name": r.product.name, "barcode": r.product.barcode,
            "sku": r.product.sku, "price": str(r.selling_price), "image_url": r.product.image_url, "slug": r.product.slug, "category_id": r.product.category_id}
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
    rows = query.order_by(Product.name).limit(2000).all()
    if q:
        aliases_by_product = {}
        ids = [r.product_id for r in rows]
        if ids:
            for alias in ProductAlias.query.filter(ProductAlias.product_id.in_(ids)).all():
                aliases_by_product.setdefault(alias.product_id, []).append(alias.alias)
        rows = forgiving_rank(rows, q, aliases_by_product=aliases_by_product, limit=60)
    else:
        rows = rows[:60]
    return jsonify(items=[safe_product_payload(r) for r in rows])


def cashier_api(fn):
    from functools import wraps
    @wraps(fn)
    @login_required
    def wrapped(*args, **kwargs):
        from flask import session
        if session.get("portal") != "pos" or not current_user.has_permission("sales.create") or not current_user.store_id:
            return jsonify(error="forbidden"), 403
        return fn(*args, **kwargs)
    return wrapped


@bp.get("/pos/products/search")
@cashier_api
def pos_product_search():
    q = request.args.get("q", "").strip()
    query = StoreProduct.query.join(Product).filter(StoreProduct.is_available.is_(True), StoreProduct.store_id == current_user.store_id, StoreProduct.available_pos.is_(True), Product.status == "ACTIVE")
    rows = query.order_by(Product.name).limit(2000).all()
    if q:
        aliases_by_product = {}
        ids = [r.product_id for r in rows]
        if ids:
            for alias in ProductAlias.query.filter(ProductAlias.product_id.in_(ids)).all():
                aliases_by_product.setdefault(alias.product_id, []).append(alias.alias)
        rows = forgiving_rank(rows, q, aliases_by_product=aliases_by_product, limit=50)
    else:
        rows = rows[:50]
    return jsonify(items=[safe_product_payload(r, include_stock=True) for r in rows])


@bp.get("/pos/mpesa-feed")
@cashier_api
def pos_mpesa_feed():
    """Branch-scoped live M-PESA notifications for the POS face of the business."""
    today = db.func.date(PaymentGatewayEvent.received_at) == db.func.current_date()
    q = PaymentGatewayEvent.query.filter(
        PaymentGatewayEvent.business_id == current_user.business_id,
        PaymentGatewayEvent.store_id == current_user.store_id,
    )
    events = q.order_by(PaymentGatewayEvent.received_at.desc()).limit(8).all()
    received = q.filter(today, PaymentGatewayEvent.status.in_(["MATCHED", "UNMATCHED"])).with_entities(
        db.func.coalesce(db.func.sum(PaymentGatewayEvent.amount), 0)
    ).scalar() or 0
    matched = q.filter(today, PaymentGatewayEvent.status == "MATCHED").with_entities(
        db.func.coalesce(db.func.sum(PaymentGatewayEvent.amount), 0)
    ).scalar() or 0
    feed=[]
    for e in events:
        row={"time": e.received_at.isoformat() if e.received_at else None, "amount": str(e.amount or 0),
             "customer": e.customer or "M-PESA customer", "transaction": e.transaction_id or "—", "status": e.status,
             "order_number": None, "receipt_number": None, "received_amount": None, "outstanding_amount": None, "required_amount": None,
             "payment_label": "Received"}
        if e.matched_payment_id:
            paid = db.session.get(Payment, e.matched_payment_id)
            if paid and paid.order_id:
                order = db.session.get(Order, paid.order_id)
                if order:
                    row.update(order_number=order.order_number, required_amount=str(order.total),
                               received_amount=str(order_received_total(order)), outstanding_amount=str(order_outstanding(order)),
                               payment_label="Fully paid" if order.payment_status == "PAID" else "Part payment")
            elif paid and paid.sale_id:
                sale = db.session.get(Sale, paid.sale_id)
                if sale:
                    row.update(receipt_number=sale.receipt_number, required_amount=str(sale.total),
                               received_amount=str(sale_received_total(sale)), outstanding_amount=str(sale_outstanding(sale)),
                               payment_label="Fully paid" if sale.payment_status == "PAID" else "Part payment")
        feed.append(row)
    return jsonify(ok=True, received_total=str(received), matched_total=str(matched), events=feed)


@bp.get("/pos/catalogue/cache")
@cashier_api
def pos_catalogue_cache():
    rows = (StoreProduct.query.join(Product)
            .filter(StoreProduct.is_available.is_(True), StoreProduct.store_id == current_user.store_id,
                    StoreProduct.available_pos.is_(True), Product.status == "ACTIVE")
            .order_by(Product.name).limit(min(int(request.args.get("limit", 500)), 1000)).all())
    return jsonify(items=[safe_product_payload(r, include_stock=True) for r in rows])


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
    import secrets
    order_number=f"DM-{now().strftime('%Y%m%d')}-{secrets.token_hex(3).upper()}"
    c=data.get("customer") or {}; phone=(c.get("phone") or "").strip(); email=(c.get("email") or "").strip().lower(); name=(c.get("name") or "").strip()
    customer=None
    if phone or email:
        matches=[]
        if phone: matches.append(Customer.phone == phone)
        if email: matches.append(Customer.email == email)
        from sqlalchemy import or_
        customer=Customer.query.filter(or_(*matches)).first() if matches else None
        if not customer:
            customer=Customer(business_id=business.id,name=name or "Online customer",phone=phone or None,email=email or None)
            db.session.add(customer);db.session.flush()
        elif name:
            customer.name=name
    order=Order(business_id=business.id,store_id=store.id,order_number=order_number,customer_id=customer.id if customer else None,subtotal=subtotal,total=subtotal,delivery_address=data.get("delivery_address"),delivery_notes=data.get("delivery_notes"))
    db.session.add(order);db.session.flush()
    for sp,qty,line in prepared:
        sp.reserved_quantity=Decimal(sp.reserved_quantity or 0)+qty
        db.session.add(OrderItem(order_id=order.id,product_id=sp.product_id,product_name_snapshot=sp.product.name,sku_snapshot=sp.product.sku,unit_price=sp.selling_price,quantity=qty,line_total=line))
    db.session.commit()
    return jsonify(ok=True,order_id=order.id,order_number=order_number,total=str(order.total),payment_status=order.payment_status)



def normalize_ke_phone(value):
    digits = re.sub(r"\D", "", str(value or ""))
    if digits.startswith("254") and len(digits) == 12 and digits[3] in "17":
        return digits
    if digits.startswith("0") and len(digits) == 10 and digits[1] in "17":
        return "254" + digits[1:]
    if digits.startswith("7") and len(digits) == 9:
        return "254" + digits
    return None


def active_daraja_integration(business_id):
    return PaymentIntegration.query.filter_by(
        business_id=business_id, provider="SAFARICOM", is_active=True
    ).first()

def configured_daraja(business_id):
    integration = active_daraja_integration(business_id)
    if not integration:
        return None
    try:
        shortcode = decrypt(integration.shortcode_encrypted) or ""
        extra = {}
        if integration.other_credentials_encrypted:
            try:
                import json
                extra = json.loads(decrypt(integration.other_credentials_encrypted) or "{}")
            except Exception:
                extra = {}
        transaction_type = extra.get("transaction_type", "CustomerPayBillOnline")
        till_setting = SystemSetting.query.filter_by(business_id=business_id, key="mpesa_till_number").first()
        till_number = str(till_setting.value or "").strip() if till_setting else ""
        effective_shortcode = till_number if transaction_type == "CustomerBuyGoodsOnline" and till_number else shortcode
        provider = DarajaProvider(
            decrypt(integration.consumer_key_encrypted) or "",
            decrypt(integration.consumer_secret_encrypted) or "",
            effective_shortcode,
            decrypt(integration.passkey_encrypted) or "",
            integration.environment or "sandbox",
            integration.callback_url or current_app.config.get("DARAJA_CALLBACK_URL", ""),
        )
        provider.transaction_type = transaction_type
        provider.till_number = till_number
        if not all([provider.consumer_key, provider.consumer_secret, provider.shortcode, provider.passkey, provider.callback_url]):
            return None
        return provider
    except Exception:
        return None


def _gateway_secret():
    setting = SystemSetting.query.filter_by(key="payment_gateway_secret").first()
    return (setting.value or "").strip() if setting else ""


def _gateway_is_payment_message(sender, message):
    text = f"{sender} {message}".lower()
    if not re.search(r"mpesa|m-pesa|safaricom", text):
        return False
    # Never forward merchant balance/statement/airtime-only messages as receipts.
    if re.search(r"balance|available balance|mini[- ]?statement|statement|airtime|bundle|data balance|new balance", text):
        return False
    return bool(re.search(r"received|paid|payment|confirmed|transaction", text))


def _gateway_parse_amount(message):
    patterns = [
        r"(?:KSH|KSHS|KES)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)",
        r"([0-9][0-9,]*(?:\.[0-9]{1,2})?)\s*(?:KSH|KSHS|KES)",
    ]
    for pattern in patterns:
        match = re.search(pattern, message or "", re.IGNORECASE)
        if match:
            try:
                return Decimal(match.group(1).replace(",", ""))
            except InvalidOperation:
                return None
    return None


def _gateway_parse_transaction(message):
    text = str(message or "").upper()
    patterns = [
        r"\b([A-Z0-9]{8,16})\s+CONFIRMED\b",
        r"\bCONFIRMED[.\s]+([A-Z0-9]{8,16})\b",
        r"\bTRANSACTION(?:\s+CODE)?[:\s]+([A-Z0-9]{8,16})\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return None


def _gateway_parse_customer(message):
    match = re.search(
        r"received\s+(?:from|by)\s+(.+?)(?=\s+(?:on behalf|for account|at\s+\d)|\s+\+?254\d{9}\b|\s+0[17]\d{8}\b|$)",
        str(message or ""),
        re.IGNORECASE,
    )
    return match.group(1).strip(" .,-")[:240] if match else ""


def _gateway_parse_phone(message):
    match = re.search(r"(?:\+?254|0)(?:7|1)\d{8}\b", str(message or ""))
    return normalize_ke_phone(match.group(0)) if match else None


def _gateway_store(business_id, sim_slot):
    setting = SystemSetting.query.filter_by(
        business_id=business_id, key=f"payment_gateway_sim_{sim_slot}_store_id"
    ).first()
    if not setting or not setting.value:
        return None
    store = db.session.get(Store, setting.value)
    return store if store and store.business_id == business_id and store.is_active else None


def _intent_status_for_entity(entity, gateway_method):
    total = Decimal(str(entity.total or 0))
    received = order_received_total(entity) if isinstance(entity, Order) else sale_received_total(entity)
    if received >= total and total > 0:
        return "PAID"
    return "PARTIALLY_PAID" if received > 0 else ("PENDING_APPROVAL" if gateway_method == "MPESA_TILL_INTENT" else "PENDING")


def _normalise_person_name(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _event_name_matches_order(event, order):
    if not event.customer or not order or not order.customer_id:
        return False
    customer = db.session.get(Customer, order.customer_id)
    if not customer:
        return False
    incoming = _normalise_person_name(event.customer)
    expected = _normalise_person_name(customer.name)
    return bool(incoming and expected and incoming == expected)


def _settle_gateway_intent(intent, event):
    from services.payments.settlement import _has_duplicate_reference
    reference = (event.transaction_id or "").strip().upper()
    amount = Decimal(str(event.amount or 0))
    if amount <= 0 or not reference or _has_duplicate_reference(intent, reference):
        return False, None
    if intent.order_id:
        order = db.session.get(Order, intent.order_id)
        outstanding = order_outstanding(order) if order else Decimal("0")
        if not order or outstanding < amount:
            return False, None
        if amount == outstanding:
            from services.payments.settlement import _reserved_order_stock_ok
            if not _reserved_order_stock_ok(order):
                return False, None
        actual = Payment(
            business_id=intent.business_id, store_id=intent.store_id, order_id=order.id,
            provider="SAFARICOM", method="MPESA_TILL" if intent.method in {"MPESA_TILL", "MPESA_TILL_INTENT"} else intent.method,
            amount=amount, currency=current_app.config["CURRENCY"], status="PAID",
            external_reference=reference, provider_transaction_id=reference,
            phone_number=event.customer_phone or intent.phone_number,
            raw_provider_reference=event.message, completed_at=now(),
        )
        db.session.add(actual); db.session.flush()
        if not settle_gateway_order_payment(order, actual):
            db.session.rollback(); return False, None
        intent.status = _intent_status_for_entity(order, intent.method)
        intent.provider_transaction_id = reference if intent.status == "PAID" else intent.provider_transaction_id
        return True, actual
    if intent.sale_id:
        sale = db.session.get(Sale, intent.sale_id)
        outstanding = sale_outstanding(sale) if sale else Decimal("0")
        if not sale or outstanding < amount:
            return False, None
        if amount == outstanding:
            from services.payments.settlement import _reserved_sale_stock_ok
            if not _reserved_sale_stock_ok(sale):
                return False, None
        actual = Payment(
            business_id=intent.business_id, store_id=intent.store_id, sale_id=sale.id,
            provider="SAFARICOM", method="MPESA_GATEWAY" if intent.method == "MPESA_GATEWAY_INTENT" else intent.method,
            amount=amount, currency=current_app.config["CURRENCY"], status="PAID",
            external_reference=reference, provider_transaction_id=reference,
            phone_number=event.customer_phone or intent.phone_number,
            raw_provider_reference=event.message, completed_at=now(),
        )
        db.session.add(actual); db.session.flush()
        if not settle_gateway_sale_payment(sale, actual):
            db.session.rollback(); return False, None
        intent.status = _intent_status_for_entity(sale, intent.method)
        intent.provider_transaction_id = reference if intent.status == "PAID" else intent.provider_transaction_id
        return True, actual
    return False, None


@csrf.exempt
@bp.post("/payment-gateway/sms")
def payment_gateway_sms():
    supplied_key = (request.args.get("key") or request.headers.get("X-RealMart-Gateway-Key") or "").strip()
    secret = _gateway_secret()
    if not secret or supplied_key != secret:
        return jsonify(error="gateway_not_authorized"), 401
    payload = request.get_json(silent=True) or {}
    event_id = (request.headers.get("X-RealMart-Event-Id") or payload.get("event_id") or "").strip()
    device_id = (request.headers.get("X-RealMart-Gateway-Id") or payload.get("gateway_device_id") or "").strip()[:120]
    message = str(payload.get("message") or "").strip()
    sender = str(payload.get("sender") or "").strip()[:120]
    source = str(payload.get("source") or "android_sms").strip()[:40]
    if not event_id or not device_id or not message:
        return jsonify(error="event_id_device_id_message_required"), 400
    if not _gateway_is_payment_message(sender, message):
        return jsonify(ok=True, ignored=True, reason="not_a_payment_notification"), 200
    business_setting = SystemSetting.query.filter_by(key="payment_gateway_secret", value=secret).first()
    if not business_setting:
        return jsonify(error="gateway_not_authorized"), 401
    business_id = business_setting.business_id
    try:
        sim_slot = int(payload.get("sim_slot", 0))
    except (TypeError, ValueError):
        sim_slot = 0
    sim_slot = 0 if sim_slot < 0 else min(sim_slot, 1)
    amount = None
    try:
        raw_amount = payload.get("amount")
        if raw_amount not in (None, ""):
            amount = Decimal(str(raw_amount).replace(",", ""))
    except InvalidOperation:
        amount = None
    if amount is None:
        amount = _gateway_parse_amount(message)
    transaction_id = str(payload.get("transaction_id") or "").strip().upper()[:160] or _gateway_parse_transaction(message)
    if not transaction_id:
        transaction_id = f"EVENT-{event_id}"[:160]
    existing = PaymentGatewayEvent.query.filter_by(business_id=business_id, gateway_device_id=device_id, transaction_id=transaction_id).first()
    if existing:
        return jsonify(ok=True, duplicate=True, event_id=existing.id, status=existing.status), 200
    customer = str(payload.get("customer") or "").strip()[:240] or _gateway_parse_customer(message)
    customer_phone = normalize_ke_phone(payload.get("customer_phone")) or _gateway_parse_phone(message)
    try:
        received_at = datetime.fromtimestamp(int(payload.get("received_at")) / 1000, tz=timezone.utc) if payload.get("received_at") else now()
    except Exception:
        received_at = now()
    store = _gateway_store(business_id, sim_slot)
    event = PaymentGatewayEvent(
        business_id=business_id, store_id=store.id if store else None, gateway_device_id=device_id,
        sim_slot=sim_slot, subscription_id=int(payload.get("subscription_id")) if str(payload.get("subscription_id") or "").isdigit() else None,
        source=source or "android_sms", sender=sender, message=message, received_at=received_at,
        transaction_id=transaction_id, amount=amount or Decimal("0"), customer=customer, customer_phone=customer_phone,
        status="UNMATCHED", raw_payload=payload,
    )
    db.session.add(event); db.session.flush()
    matched = False; actual = None
    # 1) Exact transaction reference, when a buyer supplied it as a fallback.
    if transaction_id:
        ref_intents = (Payment.query.filter(
            Payment.business_id == business_id, Payment.method.in_(["MPESA_TILL", "MPESA_TILL_INTENT"]),
            Payment.status.in_(["PENDING_APPROVAL", "PARTIALLY_PAID", "PENDING"]),
            Payment.external_reference == transaction_id,
        ).order_by(Payment.created_at.desc()).all())
        for intent in ref_intents:
            if intent.phone_number and customer_phone and normalize_ke_phone(intent.phone_number) != customer_phone:
                continue
            matched, actual = _settle_gateway_intent(intent, event)
            if matched: break
    # 2) Online Till automatic matching: prefer buyer phone; when the provider SMS has no phone,
    # fall back to an exact unique buyer-name match. Never auto-match an ambiguous candidate.
    if not matched and amount and store and (customer_phone or customer):
        cutoff = now() - timedelta(hours=2)
        candidates=[]
        intents=(Payment.query.filter(
            Payment.business_id == business_id, Payment.store_id == store.id,
            Payment.method.in_(["MPESA_TILL_INTENT", "MPESA_TILL"]),
            Payment.status.in_(["PENDING_APPROVAL", "PARTIALLY_PAID", "PENDING"]),
            Payment.created_at >= cutoff,
        ).order_by(Payment.created_at.desc()).all())
        for intent in intents:
            if not intent.order_id:
                continue
            if customer_phone:
                if normalize_ke_phone(intent.phone_number) != customer_phone:
                    continue
            else:
                order_for_name = db.session.get(Order, intent.order_id)
                if not _event_name_matches_order(event, order_for_name):
                    continue
            order=db.session.get(Order,intent.order_id)
            if order and order.payment_status != "PAID" and order_outstanding(order) >= amount:
                candidates.append(intent)
        if len(candidates)==1:
            matched, actual = _settle_gateway_intent(candidates[0], event)
    # 3) POS gateway automatic matching: same mart + customer phone + no overpayment.
    if not matched and amount and store and customer_phone:
        cutoff = now() - timedelta(hours=20/3)
        candidates=[]
        intents=(Payment.query.filter(
            Payment.business_id == business_id, Payment.store_id == store.id,
            Payment.method.in_(["MPESA_GATEWAY_INTENT", "MPESA_GATEWAY"]),
            Payment.status.in_(["PENDING", "PARTIALLY_PAID"]), Payment.created_at >= cutoff,
        ).order_by(Payment.created_at.desc()).all())
        for intent in intents:
            if normalize_ke_phone(intent.phone_number) != customer_phone or not intent.sale_id:
                continue
            sale=db.session.get(Sale,intent.sale_id)
            if sale and sale.payment_status != "PAID" and sale_outstanding(sale) >= amount:
                candidates.append(intent)
        if len(candidates)==1:
            matched, actual = _settle_gateway_intent(candidates[0], event)
    event.status = "MATCHED" if matched else "UNMATCHED"
    event.matched_payment_id = actual.id if actual else None
    if matched and actual:
        event.store_id = actual.store_id
    db.session.commit()
    return jsonify(ok=True, event_id=event.id, matched=matched, transaction_id=transaction_id, amount=str(amount or 0),
                   store_id=event.store_id, status=event.status, payment_id=actual.id if actual else None), 200


@csrf.exempt
@bp.post("/payments/mpesa/initiate")
@bp.post("/payments/daraja/initiate")
def mpesa_initiate():
    data = request.get_json(silent=True) or {}
    try:
        amount = Decimal(str(data.get("amount", 0)))
    except InvalidOperation:
        return jsonify(error="invalid_amount"), 400
    phone = normalize_ke_phone(data.get("phone_number"))
    sale_id = data.get("sale_id")
    order_id = data.get("order_id")
    if amount <= 0 or not phone:
        return jsonify(error="valid_kenyan_phone_and_amount_required"), 400
    if not sale_id and not order_id:
        return jsonify(error="sale_or_order_required"), 400
    if sale_id and (not current_user.is_authenticated or not current_user.has_permission("sales.create")):
        return jsonify(error="forbidden"), 403
    entity = db.session.get(Sale, sale_id) if sale_id else db.session.get(Order, order_id)
    if not entity:
        return jsonify(error="entity_not_found"), 404
    if sale_id and (session.get("portal") != "pos" or entity.store_id != current_user.store_id):
        return jsonify(error="forbidden"), 403
    if Decimal(str(entity.total)) != amount:
        return jsonify(error="amount_mismatch"), 400
    if entity.payment_status == "PAID":
        return jsonify(error="already_paid"), 409
    provider = configured_daraja(entity.business_id)
    if not provider:
        return jsonify(error="mpesa_not_configured", message="M-PESA is not configured for this business."), 503

    payment = Payment(
        business_id=entity.business_id, store_id=entity.store_id, sale_id=sale_id, order_id=order_id,
        provider="SAFARICOM", method="MPESA", amount=amount, currency=current_app.config["CURRENCY"],
        status="PENDING", phone_number=phone,
    )
    db.session.add(payment)
    db.session.flush()
    try:
        response = provider.initiate_payment(
            amount=amount, phone_number=phone,
            account_reference=(entity.receipt_number if sale_id else entity.order_number),
            transaction_desc="Denmart retail purchase",
            transaction_type=getattr(provider, "transaction_type", "CustomerPayBillOnline"),
        )
        if not response.get("CheckoutRequestID"):
            raise ValueError(response.get("errorMessage") or response.get("ResponseDescription") or "No CheckoutRequestID returned")
    except Exception as exc:
        payment.status = "FAILED"
        payment.failure_message = "Payment request could not be sent."
        if isinstance(entity, Sale):
            entity.payment_status = "FAILED"
            for line in SaleItem.query.filter_by(sale_id=entity.id).all():
                sp = StoreProduct.query.filter_by(store_id=entity.store_id, product_id=line.product_id).first()
                if sp:
                    sp.reserved_quantity = max(Decimal("0"), Decimal(sp.reserved_quantity or 0) - Decimal(line.quantity))
        else:
            entity.payment_status = "FAILED"
            entity.status = "PAYMENT_FAILED"
            for line in OrderItem.query.filter_by(order_id=entity.id).all():
                sp = StoreProduct.query.filter_by(store_id=entity.store_id, product_id=line.product_id).first()
                if sp:
                    sp.reserved_quantity = max(Decimal("0"), Decimal(sp.reserved_quantity or 0) - Decimal(line.quantity))
        db.session.commit()
        return jsonify(error="payment_provider_unavailable", detail=str(exc)[:240]), 502
    payment.merchant_request_id = response.get("MerchantRequestID")
    payment.checkout_request_id = response.get("CheckoutRequestID")
    payment.external_reference = response.get("CustomerMessage") or response.get("ResponseDescription")
    db.session.commit()
    return jsonify(ok=True, payment_id=payment.id, status="PENDING", message="Payment prompt sent")


@csrf.exempt
@bp.post("/payments/till/submit")
def till_payment_submit():
    data = request.get_json(silent=True) or {}
    order_id = data.get("order_id")
    reference = re.sub(r"[^A-Za-z0-9]", "", str(data.get("mpesa_reference") or "").strip()).upper()
    phone = normalize_ke_phone(data.get("phone_number"))
    if not order_id or not phone:
        return jsonify(error="order_and_valid_phone_required"), 400
    if reference and (len(reference) < 6 or len(reference) > 20):
        return jsonify(error="invalid_mpesa_reference"), 400
    order = db.session.get(Order, order_id)
    if not order:
        return jsonify(error="order_not_found"), 404
    if order.customer_id:
        customer = db.session.get(Customer, order.customer_id)
        if customer and normalize_ke_phone(customer.phone) and normalize_ke_phone(customer.phone) != phone:
            return jsonify(error="phone_does_not_match_order"), 403
    if order.payment_status == "PAID":
        return jsonify(error="already_paid"), 409
    till_setting = SystemSetting.query.filter_by(business_id=order.business_id, key="mpesa_till_number").first()
    till_number = str(till_setting.value or "").strip() if till_setting else ""
    if not till_number:
        return jsonify(error="mpesa_till_not_configured"), 503
    existing = (Payment.query.filter(Payment.order_id == order.id, Payment.method.in_(["MPESA_TILL_INTENT", "MPESA_TILL"]),
                                     Payment.status.in_(["PENDING_APPROVAL", "PARTIALLY_PAID", "PENDING"]))
                .order_by(Payment.created_at.desc()).first())
    if existing:
        if reference and not existing.external_reference:
            existing.external_reference = reference
            db.session.commit()
        return jsonify(ok=True, payment_id=existing.id, status=existing.status, message="Payment is being monitored automatically",
                       received=str(order_received_total(order)), outstanding=str(order_outstanding(order)), total=str(order.total))
    payment = Payment(
        business_id=order.business_id, store_id=order.store_id, order_id=order.id,
        provider="SAFARICOM", method="MPESA_TILL_INTENT", amount=order.total,
        currency=current_app.config["CURRENCY"], status="PENDING_APPROVAL",
        external_reference=reference or None, phone_number=phone,
    )
    db.session.add(payment)
    order.payment_status = "PENDING_APPROVAL"
    order.status = "PENDING"
    db.session.commit()
    # If the optional transaction code points to an SMS that arrived just before the intent
    # existed, reconcile that unmatched event immediately. This is the manual-reference backup.
    if reference:
        prior = (PaymentGatewayEvent.query.filter(
            PaymentGatewayEvent.business_id == order.business_id,
            PaymentGatewayEvent.store_id == order.store_id,
            PaymentGatewayEvent.status == "UNMATCHED",
            PaymentGatewayEvent.transaction_id == reference,
        ).order_by(PaymentGatewayEvent.received_at.desc()).first())
        if prior:
            matched, actual = _settle_gateway_intent(payment, prior)
            if matched:
                prior.status = "MATCHED"
                prior.matched_payment_id = actual.id if actual else None
                db.session.commit()
    current_status = _intent_status_for_entity(order, payment.method)
    return jsonify(ok=True, payment_id=payment.id, status=current_status,
                   order_number=order.order_number, till_number=till_number,
                   received=str(order_received_total(order)), outstanding=str(order_outstanding(order)),
                   message="Payment submitted. Real Mart is listening for the M-PESA confirmation automatically.")


@csrf.exempt
@bp.post("/payments/gateway/await")
@cashier_api
def payment_gateway_await():
    data = request.get_json(silent=True) or {}
    sale_id = data.get("sale_id")
    phone = normalize_ke_phone(data.get("phone_number"))
    if not sale_id:
        return jsonify(error="sale_required"), 400
    sale = db.session.get(Sale, sale_id)
    if not sale or sale.business_id != current_user.business_id or sale.store_id != current_user.store_id:
        return jsonify(error="sale_not_found"), 404
    if sale.payment_status == "PAID":
        return jsonify(error="already_paid"), 409

    existing = Payment.query.filter(Payment.sale_id == sale.id, Payment.method.in_(["MPESA_GATEWAY_INTENT", "MPESA_GATEWAY"]), Payment.status.in_(["PENDING", "PARTIALLY_PAID"])).order_by(Payment.created_at.desc()).first()
    if existing:
        return jsonify(ok=True, payment_id=existing.id, status=existing.status,
                       amount=str(existing.amount), message="Waiting for the M-PESA phone message")

    payment = Payment(
        business_id=sale.business_id, store_id=sale.store_id, sale_id=sale.id,
        provider="SAFARICOM", method="MPESA_GATEWAY_INTENT", amount=sale.total,
        currency=current_app.config["CURRENCY"], status="PENDING", phone_number=phone,
    )
    db.session.add(payment)
    db.session.commit()
    return jsonify(ok=True, payment_id=payment.id, status=payment.status,
                   amount=str(payment.amount), receipt=sale.receipt_number,
                   message="Waiting for the M-PESA phone message")


@bp.get("/payments/<payment_id>/status")
def payment_status(payment_id):
    payment = db.session.get(Payment, payment_id)
    if not payment:
        return jsonify(error="payment_not_found"), 404
    data = {"ok": True, "payment_id": payment.id, "status": payment.status, "amount": str(payment.amount),
            "receipt": payment.provider_transaction_id, "message": payment.failure_message}
    if payment.order_id:
        order = db.session.get(Order, payment.order_id)
        received = order_received_total(order) if order else Decimal("0")
        total = Decimal(str(order.total or 0)) if order else Decimal("0")
        outstanding = max(Decimal("0"), total - received)
        data.update({"order_status": order.status if order else None, "payment_status": order.payment_status if order else None,
                     "fulfillment_status": order.fulfillment_status if order else None, "required_amount": str(total),
                     "received_amount": str(received), "outstanding_amount": str(outstanding)})
        if order and received >= total > 0:
            data["status"] = "PAID"
        elif received > 0:
            data["status"] = "PARTIALLY_PAID"
    elif payment.sale_id:
        sale = db.session.get(Sale, payment.sale_id)
        received = sale_received_total(sale) if sale else Decimal("0")
        total = Decimal(str(sale.total or 0)) if sale else Decimal("0")
        outstanding = max(Decimal("0"), total - received)
        data.update({"payment_status": sale.payment_status if sale else None, "required_amount": str(total),
                     "received_amount": str(received), "outstanding_amount": str(outstanding)})
        if sale and received >= total > 0:
            data["status"] = "PAID"
        elif received > 0:
            data["status"] = "PARTIALLY_PAID"
    return jsonify(data)


@csrf.exempt
@bp.post("/payments/<payment_id>/reconcile")
def payment_reconcile(payment_id):
    payment = db.session.get(Payment, payment_id)
    if not payment:
        return jsonify(error="payment_not_found"), 404
    if payment.status in {"PAID", "FAILED"}:
        return jsonify(ok=True, status=payment.status, already_final=True)
    if payment.order_id:
        business_id = payment.business_id
    elif payment.sale_id:
        if not current_user.is_authenticated or session.get("portal") != "pos":
            return jsonify(error="forbidden"), 403
        business_id = payment.business_id
    else:
        return jsonify(error="payment_entity_missing"), 409
    provider = configured_daraja(business_id)
    if not provider or not payment.checkout_request_id:
        return jsonify(error="mpesa_not_configured"), 503
    try:
        result = provider.check_payment(checkout_request_id=payment.checkout_request_id)
    except Exception:
        return jsonify(ok=True, status="PENDING", message="Provider status not available yet"), 200
    result_code = str(result.get("ResultCode", ""))
    if result_code == "0":
        # Final settlement is performed through the same callback logic. Synthesize
        # a callback-shaped payload is unsafe because STK query lacks metadata,
        # so leave the payment pending until Safaricom's callback supplies receipt data.
        return jsonify(ok=True, status="PENDING", message="Payment accepted; awaiting callback"), 200
    if result_code and result_code not in {"1037", "49999"}:
        payment.status = "FAILED"
        payment.failure_code = result_code
        payment.failure_message = str(result.get("ResultDesc") or "Payment was not completed")[:500]
        db.session.commit()
    return jsonify(ok=True, status=payment.status, message=payment.failure_message)


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
        if callback_amount!=Decimal(payment.amount):
            payment.status="FAILED"
            payment.failure_message="Provider amount mismatch"
        else:
            payment.status="PAID";payment.provider_transaction_id=result.get("receipt");payment.completed_at=now()
            if payment.sale_id:
                sale=db.session.get(Sale,payment.sale_id)
                if sale:
                    sale.status="COMPLETED";sale.payment_status="PAID";sale.completed_at=now()
                    for line in SaleItem.query.filter_by(sale_id=sale.id).all():
                        sp=StoreProduct.query.filter_by(store_id=sale.store_id,product_id=line.product_id).first()
                        if sp:
                            sp.reserved_quantity=max(Decimal("0"),Decimal(sp.reserved_quantity or 0)-Decimal(line.quantity))
                            sp.stock_quantity=Decimal(sp.stock_quantity or 0)-Decimal(line.quantity)
                            db.session.add(InventoryTransaction(store_id=sale.store_id,product_id=line.product_id,transaction_type="SALE",quantity=-Decimal(line.quantity),unit_cost=sp.cost_price,reference_type="SALE",reference_id=sale.id))
            if payment.order_id:
                order=db.session.get(Order,payment.order_id)
                if order:
                    order.payment_status="PAID";order.status="CONFIRMED"
                    award_purchase_points(order.business_id, order.customer_id, order.total, "ORDER", order.id)
                    for line in OrderItem.query.filter_by(order_id=order.id).all():
                        sp=StoreProduct.query.filter_by(store_id=order.store_id,product_id=line.product_id).first()
                        if sp: sp.reserved_quantity=max(Decimal("0"),Decimal(sp.reserved_quantity or 0)-Decimal(line.quantity));sp.stock_quantity=Decimal(sp.stock_quantity or 0)-Decimal(line.quantity);db.session.add(InventoryTransaction(store_id=order.store_id,product_id=line.product_id,transaction_type="SALE",quantity=-Decimal(line.quantity),unit_cost=sp.cost_price,reference_type="ORDER",reference_id=order.id))
    else:
        payment.status="FAILED";payment.failure_message=result.get("result_desc") or "Payment failed"
        if payment.sale_id:
            sale=db.session.get(Sale,payment.sale_id)
            if sale:
                sale.payment_status="FAILED"
                for line in SaleItem.query.filter_by(sale_id=sale.id).all():
                    sp=StoreProduct.query.filter_by(store_id=sale.store_id,product_id=line.product_id).first()
                    if sp: sp.reserved_quantity=max(Decimal("0"),Decimal(sp.reserved_quantity or 0)-Decimal(line.quantity))
        if payment.order_id:
            order=db.session.get(Order,payment.order_id)
            if order:
                order.payment_status="FAILED"
                order.status="PAYMENT_FAILED"
                for line in OrderItem.query.filter_by(order_id=order.id).all():
                    sp=StoreProduct.query.filter_by(store_id=order.store_id,product_id=line.product_id).first()
                    if sp: sp.reserved_quantity=max(Decimal("0"),Decimal(sp.reserved_quantity or 0)-Decimal(line.quantity))
    payment.raw_provider_reference=str(payload);db.session.commit()
    return jsonify(ResultCode=0,ResultDesc="Accepted"),200


@bp.get("/pos/orders")
@cashier_api
def pos_orders():
    from models import Customer
    rows = (Order.query.filter_by(store_id=current_user.store_id)
            .order_by(Order.created_at.desc()).limit(80).all())
    from services.payments.settlement import order_received_total, order_outstanding
    return jsonify(items=[{
        "order_number": o.order_number, "customer": (o.customer.name if getattr(o, "customer", None) else "Online customer"),
        "total": str(o.total), "received_amount": str(order_received_total(o)),
        "outstanding_amount": str(order_outstanding(o)), "payment_status": o.payment_status,
        "status": o.status, "fulfillment_status": o.fulfillment_status
    } for o in rows])


@csrf.exempt


@csrf.exempt
@bp.post("/pos/orders/<order_number>/fulfillment")
@cashier_api
def pos_update_order_fulfillment(order_number):
    from models import Order
    states = {"PENDING", "PACKING", "READY_FOR_DISPATCH", "OUT_FOR_DELIVERY", "DELIVERED", "CANCELLED"}
    order = Order.query.filter_by(order_number=order_number, store_id=current_user.store_id).first()
    data = request.get_json(silent=True) or {}
    new_state = str(data.get("fulfillment_status") or "").upper()
    if not order or new_state not in states: return jsonify(error="invalid_order_or_status"), 400
    if order.payment_status != "PAID" and new_state not in {"PENDING", "CANCELLED"}: return jsonify(error="order_not_paid"), 409
    if new_state == "CANCELLED" and order.payment_status == "PAID": return jsonify(error="paid_order_requires_admin_refund_workflow"), 409
    order.fulfillment_status = new_state
    if new_state == "DELIVERED": order.status = "COMPLETED"
    elif order.payment_status == "PAID": order.status = "CONFIRMED"
    db.session.commit()
    return jsonify(ok=True, order_number=order.order_number, fulfillment_status=order.fulfillment_status, status=order.status)

@bp.post("/sync/offline")
@cashier_api
def sync_offline():
    # Acknowledgement endpoint remains separate and permissioned; raw offline
    # payloads are not executed blindly.
    data=request.get_json(silent=True) or {}; return jsonify(ok=True,accepted=0,message="Offline queue accepted for controlled reconciliation")
