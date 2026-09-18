from decimal import Decimal, InvalidOperation
import secrets
from flask import Blueprint, jsonify, render_template, request, redirect
from flask_login import current_user, login_required
from extensions import csrf, db
from models import Sale, SaleItem, StoreProduct, InventoryTransaction, Shift, CashDrawerTransaction, Payment, now, Store, User
from services.audit import audit

bp = Blueprint("pos", __name__)


def cashier_required(fn):
    from functools import wraps
    @wraps(fn)
    @login_required
    def wrapped(*args, **kwargs):
        from flask import session
        if session.get("portal") != "pos" or not current_user.is_active or not current_user.business_id or not current_user.role:
            return jsonify(error="forbidden"), 403
        # A merchant account created by the admin may omit a mart assignment.
        # Use the first active mart automatically so a valid cashier can sign in
        # without an unnecessary "till" setup step.
        if not current_user.store_id:
            store = (Store.query.filter_by(business_id=current_user.business_id, is_active=True)
                     .order_by(Store.created_at).first())
            if not store:
                return jsonify(error="no_active_store"), 503
            current_user.store_id = store.id
            db.session.commit()
        return fn(*args, **kwargs)
    return wrapped


@bp.get("/merchant/on")
@cashier_required
def dashboard_entry():
    return dashboard()


@cashier_required
def dashboard():
    store = db.session.get(Store, current_user.store_id)
    shift = Shift.query.filter_by(store_id=current_user.store_id, cashier_id=current_user.id, status="OPEN").first()
    last_agent = User.query.filter(User.business_id == current_user.business_id, User.store_id == current_user.store_id, User.id != current_user.id, User.last_login_at.isnot(None)).order_by(User.last_login_at.desc()).first()
    return render_template("pos/index.html", store=store, shift=shift, pwa_manifest="/merchant/manifest.webmanifest", last_agent=last_agent)


@bp.get("/merchant/manifest.webmanifest")
def pos_manifest():
    base=request.host_url.rstrip("/")
    return jsonify({
        "name":"Denmart Till", "short_name":"Till", "start_url":f"{base}/merchant/on",
        "scope":f"{base}/merchant", "display":"standalone", "background_color":"#24180f",
        "theme_color":"#f29b38", "description":"Cashier till application.",
        "icons":[{"src":f"{base}/static/pwa/icon.svg","sizes":"any","type":"image/svg+xml","purpose":"any maskable"}],
    })


@bp.get("/merchant/sw.js")
def pos_service_worker():
    from flask import Response
    js="""const CACHE='denmart-agent-v16';\nself.addEventListener('install',e=>e.waitUntil(self.skipWaiting()));\nself.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));\nself.addEventListener('fetch',e=>{const u=new URL(e.request.url);if(u.origin!==location.origin||e.request.method!=='GET'||!u.pathname.startsWith('/merchant'))return;e.respondWith(fetch(e.request).catch(()=>caches.match(e.request).then(r=>r||new Response('Till connection unavailable',{status:503}))))});\n"""
    return Response(js,mimetype="application/javascript",headers={"Service-Worker-Allowed":"/merchant"})


@bp.get("/merchant/receipt/<receipt_number>")
@cashier_required
def receipt(receipt_number):
    sale=Sale.query.filter_by(receipt_number=receipt_number).first_or_404()
    if sale.store_id!=current_user.store_id:return "Forbidden",403
    items=SaleItem.query.filter_by(sale_id=sale.id).all()
    return render_template("pos/receipt.html",sale=sale,items=items)


@csrf.exempt
@bp.post("/api/pos/sales")
@cashier_required
def create_sale():
    data = request.get_json(silent=True) or {}
    return _record_sale(data, allow_offline=False)


def _record_sale(data, allow_offline=False):
    payment_method = (data.get("payment_method") or "CASH").upper()
    items = data.get("items") or []
    client_ref = (data.get("client_ref") or "").strip()[:80]
    shift = Shift.query.filter_by(store_id=current_user.store_id, cashier_id=current_user.id, status="OPEN").first()
    if not shift:
        return jsonify(error="shift_not_open"), 409
    if not items:
        return jsonify(error="cart_empty"), 400
    if payment_method not in {"CASH", "CARD", "MPESA"}:
        return jsonify(error="unsupported_payment_method"), 400
    if allow_offline and payment_method == "MPESA":
        return jsonify(error="mpesa_requires_connection"), 400

    if client_ref:
        existing = Sale.query.filter_by(receipt_number=client_ref).first()
        if existing:
            return jsonify(ok=True, sale_id=existing.id, receipt_number=existing.receipt_number,
                           payment_status=existing.payment_status, total=str(existing.total), duplicate=True)

    subtotal = Decimal("0")
    prepared = []
    for raw in items:
        sp = (StoreProduct.query.filter_by(id=raw.get("store_product_id"), store_id=current_user.store_id)
              .with_for_update().first())
        try:
            qty = Decimal(str(raw.get("quantity", 0)))
        except InvalidOperation:
            return jsonify(error="invalid_quantity"), 400
        if not sp or not sp.available_pos or not sp.is_available or qty <= 0:
            return jsonify(error="invalid_item"), 400
        available = Decimal(sp.stock_quantity or 0) - Decimal(sp.reserved_quantity or 0)
        if available < qty:
            return jsonify(error="insufficient_stock", product=sp.product.name, available=str(available)), 409
        line = Decimal(sp.selling_price) * qty
        subtotal += line
        prepared.append((sp, qty, line))

    receipt_number = client_ref or f"DM-{now().strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3).upper()}"
    paid_now = payment_method in {"CASH", "CARD"}
    sale = Sale(
        business_id=current_user.business_id,
        store_id=current_user.store_id,
        cashier_id=current_user.id,
        receipt_number=receipt_number,
        subtotal=subtotal,
        total=subtotal,
        status="COMPLETED" if paid_now else "PENDING",
        payment_status="PAID" if paid_now else "PENDING",
        completed_at=now() if paid_now else None,
    )
    db.session.add(sale)
    db.session.flush()
    for sp, qty, line in prepared:
        db.session.add(SaleItem(
            sale_id=sale.id, product_id=sp.product_id, product_name_snapshot=sp.product.name,
            barcode_snapshot=sp.product.barcode, unit_price=sp.selling_price,
            quantity=qty, line_total=line,
        ))
        if payment_method == "MPESA" and not paid_now:
            sp.reserved_quantity = Decimal(sp.reserved_quantity or 0) + qty

    if paid_now:
        for sp, qty, _ in prepared:
            sp.stock_quantity = Decimal(sp.stock_quantity or 0) - qty
            db.session.add(InventoryTransaction(
                store_id=sp.store_id, product_id=sp.product_id, transaction_type="SALE", quantity=-qty,
                unit_cost=sp.cost_price, reference_type="SALE", reference_id=sale.id, created_by=current_user.id,
            ))
        if payment_method == "CASH":
            db.session.add(CashDrawerTransaction(
                shift_id=shift.id, transaction_type="SALE_CASH", amount=subtotal,
                reference_type="SALE", reference_id=sale.id, created_by=current_user.id,
            ))
        else:
            db.session.add(Payment(
                business_id=current_user.business_id, store_id=current_user.store_id, sale_id=sale.id,
                provider="MANUAL", method=payment_method, amount=subtotal, currency="KES", status="PAID",
                external_reference=(data.get("payment_reference") or "")[:160], completed_at=now(),
            ))

    db.session.commit()
    audit("SALE_CREATED", "Sale", sale.id,
          new_values={"total": str(sale.total), "payment_method": payment_method, "offline": allow_offline})
    return jsonify(ok=True, sale_id=sale.id, receipt_number=receipt_number,
                   payment_status=sale.payment_status, total=str(sale.total))


@csrf.exempt
@bp.post("/api/pos/shifts/open")
@cashier_required
def open_shift():
    existing=Shift.query.filter_by(store_id=current_user.store_id,cashier_id=current_user.id,status="OPEN").first()
    if existing:return jsonify(error="shift_already_open",id=existing.id,opening_cash=str(existing.opening_cash)),409
    data=request.get_json(silent=True) or {}
    try:cash=Decimal(str(data.get("opening_cash",0)))
    except InvalidOperation:return jsonify(error="invalid_cash"),400
    if cash<0:return jsonify(error="invalid_cash"),400
    shift=Shift(store_id=current_user.store_id,cashier_id=current_user.id,opening_cash=cash)
    db.session.add(shift);db.session.commit();audit("SHIFT_OPENED","Shift",shift.id,new_values={"opening_cash":str(cash)})
    return jsonify(ok=True,shift_id=shift.id,opening_cash=str(cash))


@csrf.exempt
@bp.post("/api/pos/shifts/close")
@cashier_required
def close_shift():
    shift=Shift.query.filter_by(store_id=current_user.store_id,cashier_id=current_user.id,status="OPEN").first()
    if not shift:return jsonify(error="shift_not_open"),409
    data=request.get_json(silent=True) or {}
    try:closing=Decimal(str(data.get("closing_cash",0)))
    except InvalidOperation:return jsonify(error="invalid_cash"),400
    sales_cash=db.session.query(db.func.coalesce(db.func.sum(CashDrawerTransaction.amount),0)).filter(CashDrawerTransaction.shift_id==shift.id,CashDrawerTransaction.transaction_type=="SALE_CASH").scalar()
    withdrawals=db.session.query(db.func.coalesce(db.func.sum(CashDrawerTransaction.amount),0)).filter(CashDrawerTransaction.shift_id==shift.id,CashDrawerTransaction.transaction_type.in_(["CASH_DROP","PAID_OUT"])).scalar()
    expected=Decimal(shift.opening_cash or 0)+Decimal(sales_cash or 0)-Decimal(withdrawals or 0)
    shift.closing_cash=closing;shift.expected_cash=expected;shift.difference=closing-expected;shift.closed_at=now();shift.status="CLOSED"
    db.session.commit();audit("SHIFT_CLOSED","Shift",shift.id,new_values={"closing_cash":str(closing),"expected_cash":str(expected),"difference":str(shift.difference)})
    return jsonify(ok=True,expected_cash=str(expected),difference=str(shift.difference))




@bp.get("/api/pos/day-summary")
@cashier_required
def day_summary():
    from sqlalchemy import func
    today = db.func.date(Sale.created_at) == db.func.current_date()
    rows = db.session.query(Sale.payment_status, db.func.count(Sale.id), db.func.coalesce(db.func.sum(Sale.total),0)).filter(Sale.store_id==current_user.store_id, today).group_by(Sale.payment_status).all()
    paid = next((Decimal(str(total)) for status,count,total in rows if status=="PAID"), Decimal("0"))
    count = sum(int(count) for status,count,total in rows if status=="PAID")
    cash = db.session.query(db.func.coalesce(db.func.sum(CashDrawerTransaction.amount),0)).join(Shift, Shift.id==CashDrawerTransaction.shift_id).filter(Shift.store_id==current_user.store_id, CashDrawerTransaction.transaction_type=="SALE_CASH", db.func.date(CashDrawerTransaction.created_at)==db.func.current_date()).scalar() or 0
    return jsonify(ok=True, sales_count=count, sales_total=str(paid), cash_sales=str(cash))

@csrf.exempt
@bp.post("/api/pos/cash-drawer")
@cashier_required
def cash_drawer():
    shift=Shift.query.filter_by(store_id=current_user.store_id,cashier_id=current_user.id,status="OPEN").first()
    if not shift:return jsonify(error="shift_not_open"),409
    data=request.get_json(silent=True) or {}; kind=(data.get("type") or "CASH_DROP").upper()
    try:amount=Decimal(str(data.get("amount",0)))
    except InvalidOperation:return jsonify(error="invalid_amount"),400
    if amount<=0 or kind not in {"CASH_DROP","PAID_OUT"}:return jsonify(error="invalid_drawer_transaction"),400
    txn=CashDrawerTransaction(shift_id=shift.id,transaction_type=kind,amount=amount,notes=(data.get("notes") or "")[:240],created_by=current_user.id)
    db.session.add(txn);db.session.commit();audit("CASH_DRAWER_ACTIVITY","Shift",shift.id,new_values={"type":kind,"amount":str(amount)})
    return jsonify(ok=True)


@csrf.exempt
@bp.post("/api/pos/sync/offline")
@cashier_required
def sync_offline():
    data = request.get_json(silent=True) or {}
    queue = data.get("sales") or []
    if not isinstance(queue, list):
        return jsonify(error="invalid_queue"), 400
    if len(queue) > 50:
        return jsonify(error="queue_too_large"), 413
    results = []
    for sale_data in queue:
        if not isinstance(sale_data, dict):
            results.append({"ok": False, "error": "invalid_sale"})
            continue
        method = (sale_data.get("payment_method") or "CASH").upper()
        if method == "MPESA":
            results.append({"ok": False, "client_ref": sale_data.get("client_ref"), "error": "mpesa_requires_connection"})
            continue
        try:
            response, status_code = _record_sale({**sale_data, "payment_method": method}, allow_offline=True)
            payload = response.get_json() if hasattr(response, "get_json") else None
            results.append({"ok": status_code < 400, "client_ref": sale_data.get("client_ref"), **(payload or {})})
            if status_code >= 400:
                db.session.rollback()
        except Exception as exc:
            db.session.rollback()
            results.append({"ok": False, "client_ref": sale_data.get("client_ref"), "error": "sync_failed"})
    return jsonify(ok=all(x.get("ok") for x in results) if results else True, results=results)
