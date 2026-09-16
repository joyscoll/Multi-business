from decimal import Decimal
from flask import Blueprint, jsonify, render_template, request, jsonify as _jsonify
from flask_login import current_user, login_required
from extensions import csrf, db
from models import Sale, SaleItem, StoreProduct, InventoryTransaction, Payment, Shift, now, Store
from services.audit import audit

bp = Blueprint("pos", __name__)


def cashier_required(fn):
    from functools import wraps
    @wraps(fn)
    @login_required
    def wrapped(*args, **kwargs):
        if not current_user.has_permission("sales.create"):
            return "Forbidden", 403
        return fn(*args, **kwargs)
    return wrapped


@bp.get("/otcOmc")
def dashboard_entry():
    if not current_user.is_authenticated:
        return __import__('flask').redirect("/otcOmc/login?next=/otcOmc")
    if not current_user.has_permission("sales.create"):
        return "Forbidden", 403
    return dashboard()


@cashier_required
def dashboard():
    store = db.session.get(Store, current_user.store_id) if current_user.store_id else None
    return render_template("pos/index.html", store=store, pwa_manifest="/otcOmc/manifest.webmanifest")


@bp.get("/otcOmc/manifest.webmanifest")
def pos_manifest():
    base = request.host_url.rstrip("/")
    return _jsonify({
        "name": "REAL MART Till",
        "short_name": "Mart Till",
        "start_url": base + "/otcOmc",
        "scope": base + "/otcOmc",
        "display": "standalone",
        "background_color": "#12202a",
        "theme_color": "#55b8dc",
        "description": "Cashier till for REAL MART.",
        "icons": [{"src": base + "/static/pwa/icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any maskable"}]
    })

@bp.get("/otcOmc/sw.js")
def pos_service_worker():
    from flask import Response
    js = """const CACHE='real-mart-pos-v1';
self.addEventListener('install',e=>self.skipWaiting());
self.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));
self.addEventListener('fetch',e=>{
  const u=new URL(e.request.url);
  if(u.origin!==location.origin)return;
  if(e.request.method!=='GET')return;
  if(!u.pathname.startsWith('/otcOmc'))return;
  e.respondWith(fetch(e.request).catch(()=>new Response('POS terminal offline',{status:503,headers:{'Content-Type':'text/plain'}})));
});

"""
    return Response(js, mimetype="application/javascript", headers={"Service-Worker-Allowed": "/otcOmc"})

@bp.get("/otcOmc/receipt/<receipt_number>")
@cashier_required
def receipt(receipt_number):
    sale = Sale.query.filter_by(receipt_number=receipt_number).first_or_404()
    if sale.store_id != current_user.store_id and not current_user.has_permission("reports.view"):
        return "Forbidden", 403
    items = SaleItem.query.filter_by(sale_id=sale.id).all()
    return render_template("pos/receipt.html", sale=sale, items=items)


@csrf.exempt
@bp.post("/api/pos/sales")
@cashier_required
def create_sale():
    data = request.get_json(silent=True) or {}
    if not current_user.store_id:
        return jsonify(error="user_has_no_store"), 400
    items = data.get("items", [])
    payment_method = (data.get("payment_method") or "CASH").upper()
    if not items:
        return jsonify(error="cart_empty"), 400
    subtotal = Decimal("0")
    prepared = []
    for raw in items:
        sp = db.session.get(StoreProduct, raw.get("store_product_id"))
        qty = Decimal(str(raw.get("quantity", 0)))
        if not sp or sp.store_id != current_user.store_id or qty <= 0 or not sp.available_pos:
            return jsonify(error="invalid_item", item=raw), 400
        available = Decimal(sp.stock_quantity or 0) - Decimal(sp.reserved_quantity or 0)
        if available < qty:
            return jsonify(error="insufficient_stock", product=sp.product.name, available=str(available)), 409
        line = Decimal(sp.selling_price) * qty
        subtotal += line
        prepared.append((sp, qty, line))
    receipt_number = f"RM-{now().strftime('%Y%m%d-%H%M%S')}-{Sale.query.count()+1:05d}"
    sale = Sale(business_id=current_user.business_id, store_id=current_user.store_id, cashier_id=current_user.id,
                receipt_number=receipt_number, subtotal=subtotal, total=subtotal,
                status="COMPLETED" if payment_method == "CASH" else "PENDING",
                payment_status="PAID" if payment_method == "CASH" else "PENDING",
                completed_at=now() if payment_method == "CASH" else None)
    db.session.add(sale)
    db.session.flush()
    for sp, qty, line in prepared:
        db.session.add(SaleItem(sale_id=sale.id, product_id=sp.product_id, product_name_snapshot=sp.product.name,
                               barcode_snapshot=sp.product.barcode, unit_price=sp.selling_price, quantity=qty, line_total=line))
    if payment_method == "CASH":
        for sp, qty, _ in prepared:
            sp.stock_quantity = Decimal(sp.stock_quantity) - qty
            db.session.add(InventoryTransaction(store_id=sp.store_id, product_id=sp.product_id, transaction_type="SALE", quantity=-qty, unit_cost=sp.cost_price, reference_type="SALE", reference_id=sale.id, created_by=current_user.id))
    db.session.commit()
    audit("SALE_CREATED", "Sale", sale.id, new_values={"total": str(sale.total), "payment_method": payment_method})
    return jsonify(ok=True, sale_id=sale.id, receipt_number=receipt_number, payment_status=sale.payment_status, total=str(sale.total))


@csrf.exempt
@bp.post("/api/pos/shifts/open")
@cashier_required
def open_shift():
    if not current_user.store_id:
        return jsonify(error="user_has_no_store"), 400
    existing = Shift.query.filter_by(store_id=current_user.store_id, cashier_id=current_user.id, status="OPEN").first()
    if existing:
        return jsonify(error="shift_already_open", id=existing.id), 409
    data = request.get_json(silent=True) or {}
    shift = Shift(store_id=current_user.store_id, cashier_id=current_user.id, opening_cash=Decimal(str(data.get("opening_cash", 0))))
    db.session.add(shift); db.session.commit()
    audit("SHIFT_OPENED", "Shift", shift.id, new_values={"opening_cash": str(shift.opening_cash)})
    return jsonify(ok=True, shift_id=shift.id)
