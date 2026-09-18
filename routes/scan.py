import re
from decimal import Decimal, InvalidOperation
from functools import wraps

from flask import Blueprint, jsonify, render_template, request
from flask_login import current_user, login_required

from extensions import db
from models import Business, Store, StoreProduct, Product, InventoryTransaction, AuditLog, Category, now

bp = Blueprint("scan", __name__)


def scan_admin_required(fn):
    @wraps(fn)
    @login_required
    def wrapped(*args, **kwargs):
        if (
            not current_user.is_authenticated
            or session_portal() != "admin"
            or not current_user.role
            or current_user.role.name != "OWNER"
        ):
            return "Forbidden", 403
        return fn(*args, **kwargs)
    return wrapped


def session_portal():
    # Imported lazily so this module stays standalone and avoids circular imports.
    from flask import session
    return session.get("portal")


def _business_stores():
    return Store.query.filter_by(business_id=current_user.business_id, is_active=True).order_by(Store.name).all()


def _valid_store(store_id):
    if not store_id:
        return None
    return Store.query.filter_by(id=store_id, business_id=current_user.business_id, is_active=True).first()


def _default_store(stores):
    if current_user.store_id:
        owned = next((s for s in stores if s.id == current_user.store_id), None)
        if owned:
            return owned
    return stores[0] if len(stores) == 1 else None


def _normalize_barcode(value):
    return re.sub(r"\s+", "", str(value or "")).strip()


def _slug_base(name, barcode):
    base = re.sub(r"[^a-z0-9]+", "-", str(name or "product").lower()).strip("-") or "product"
    code = re.sub(r"[^a-z0-9]+", "", str(barcode or "").lower())
    return f"{base}-{code}"[:240].strip("-") if code else base[:240].strip("-")


def _unique_slug(name, barcode):
    base = _slug_base(name, barcode)
    candidate = base
    counter = 2
    while Product.query.filter_by(slug=candidate).first():
        suffix = f"-{counter}"
        candidate = (base[: 240 - len(suffix)] + suffix).strip("-")
        counter += 1
    return candidate


def _product_candidates(barcode):
    if not barcode:
        return []
    rows = (
        db.session.query(Product, StoreProduct, Store)
        .join(StoreProduct, StoreProduct.product_id == Product.id)
        .join(Store, Store.id == StoreProduct.store_id)
        .filter(
            Product.barcode == barcode,
            Store.business_id == current_user.business_id,
        )
        .order_by(Product.name)
        .all()
    )
    seen = set()
    result = []
    for product, store_product, store in rows:
        if product.id in seen:
            continue
        seen.add(product.id)
        result.append((product, store_product, store))
    return result


@bp.get("/scan")
@scan_admin_required
def scan_page():
    stores = _business_stores()
    selected_store = _valid_store(request.args.get("store_id")) or _default_store(stores)
    return render_template(
        "scan/index.html",
        stores=stores,
        selected_store=selected_store,
    )


@bp.get("/scan/api/lookup")
@scan_admin_required
def lookup():
    barcode = _normalize_barcode(request.args.get("barcode"))
    store = _valid_store(request.args.get("store_id")) or _default_store(_business_stores())
    if not barcode:
        return jsonify(ok=False, error="barcode_required"), 400
    if not store:
        return jsonify(ok=False, error="store_required", message="Choose the mart where this stock belongs."), 400

    matches = _product_candidates(barcode)
    if not matches:
        return jsonify(
            ok=True,
            found=False,
            barcode=barcode,
            store={"id": store.id, "name": store.name},
            product=None,
        )

    payload = []
    for product, sp, source_store in matches:
        selected_sp = StoreProduct.query.filter_by(store_id=store.id, product_id=product.id).first()
        payload.append({
            "id": product.id,
            "name": product.name,
            "barcode": product.barcode,
            "sku": product.sku,
            "brand": product.brand,
            "image_url": product.image_url or "",
            "stock": str(selected_sp.stock_quantity if selected_sp else 0),
            "reserved": str(selected_sp.reserved_quantity if selected_sp else 0),
            "cost_price": str(selected_sp.cost_price if selected_sp else 0),
            "selling_price": str(selected_sp.selling_price if selected_sp else 0),
            "linked_to_store": bool(selected_sp),
            "source_store": source_store.name,
        })
    return jsonify(
        ok=True,
        found=True,
        barcode=barcode,
        store={"id": store.id, "name": store.name},
        multiple=len(payload) > 1,
        products=payload,
        product=payload[0] if len(payload) == 1 else None,
    )


@bp.get("/scan/api/recent")
@scan_admin_required
def recent():
    stores = _business_stores()
    store = _valid_store(request.args.get("store_id")) or _default_store(stores)
    if not store:
        return jsonify(ok=True, items=[])
    rows = (
        InventoryTransaction.query
        .filter(
            InventoryTransaction.store_id == store.id,
            InventoryTransaction.transaction_type.in_(["SCAN_STOCK", "BARCODE_SCAN"]),
        )
        .order_by(InventoryTransaction.created_at.desc())
        .limit(40)
        .all()
    )
    product_ids = [r.product_id for r in rows]
    products = {p.id: p for p in Product.query.filter(Product.id.in_(product_ids)).all()} if product_ids else {}
    return jsonify(
        ok=True,
        items=[
            {
                "id": row.id,
                "barcode": products.get(row.product_id).barcode if products.get(row.product_id) else "",
                "name": products.get(row.product_id).name if products.get(row.product_id) else "Product",
                "quantity": str(abs(Decimal(row.quantity or 0))),
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ],
    )


@bp.post("/scan/api/save")
@scan_admin_required
def save():
    data = request.get_json(silent=True) or {}
    barcode = _normalize_barcode(data.get("barcode"))
    name = str(data.get("name") or "").strip()
    product_id = str(data.get("product_id") or "").strip()
    store = _valid_store(str(data.get("store_id") or "")) or _default_store(_business_stores())
    if not store:
        return jsonify(ok=False, error="store_required", message="Choose the mart where this stock belongs."), 400
    if not barcode:
        return jsonify(ok=False, error="barcode_required", message="Scan a barcode first."), 400
    if not name:
        return jsonify(ok=False, error="name_required", message="Give the item a name."), 400
    raw_quantity = str(data.get("quantity") or "").strip()
    if raw_quantity:
        try:
            quantity = Decimal(raw_quantity)
        except InvalidOperation:
            return jsonify(ok=False, error="invalid_quantity", message="Enter a valid quantity."), 400
        if quantity < 0:
            return jsonify(ok=False, error="invalid_quantity", message="Quantity cannot be negative."), 400
    else:
        quantity = Decimal("0")
    if quantity > Decimal("1000000"):
        return jsonify(ok=False, error="invalid_quantity", message="Quantity is too large for one scan.") , 400

    try:
        product = db.session.get(Product, product_id) if product_id else None
        if product:
            if product.barcode and _normalize_barcode(product.barcode) != barcode:
                return jsonify(ok=False, error="barcode_mismatch"), 400
            owner_link = (
                db.session.query(StoreProduct)
                .join(Store, Store.id == StoreProduct.store_id)
                .filter(StoreProduct.product_id == product.id, Store.business_id == current_user.business_id)
                .first()
            )
            if not owner_link:
                return jsonify(ok=False, error="product_not_owned"), 403
        else:
            candidates = _product_candidates(barcode)
            if len(candidates) > 1:
                return jsonify(ok=False, error="ambiguous_barcode", message="This barcode belongs to more than one product. Choose the correct product first."), 409
            product = candidates[0][0] if candidates else None

        created = False
        renamed = False
        if not product:
            product = Product(
                barcode=barcode,
                name=name,
                slug=_unique_slug(name, barcode),
                status="ACTIVE",
            )
            db.session.add(product)
            db.session.flush()
            created = True
        else:
            if _normalize_barcode(product.barcode or "") != barcode:
                product.barcode = barcode
            if product.name.strip() != name:
                product.name = name
                renamed = True

        sp = StoreProduct.query.filter_by(store_id=store.id, product_id=product.id).first()
        if not sp:
            sp = StoreProduct(
                store_id=store.id,
                product_id=product.id,
                cost_price=Decimal("0"),
                selling_price=Decimal("0"),
                minimum_price=Decimal("0"),
                stock_quantity=Decimal("0"),
                reserved_quantity=Decimal("0"),
                reorder_level=Decimal("0"),
                is_available=False,
                available_online=False,
                available_pos=False,
            )
            db.session.add(sp)
            db.session.flush()

        before = Decimal(sp.stock_quantity or 0)
        if quantity > 0:
            sp.stock_quantity = before + quantity

        db.session.add(InventoryTransaction(
            store_id=store.id,
            product_id=product.id,
            transaction_type="SCAN_STOCK" if quantity > 0 else "BARCODE_SCAN",
            quantity=quantity,
            unit_cost=sp.cost_price,
            reference_type="BARCODE_SCAN",
            reference_id=product.id,
            notes=("Stock added through /scan barcode workflow" if quantity > 0 else "Barcode captured and product saved through /scan; stock unchanged"),
            created_by=current_user.id,
        ))
        db.session.add(AuditLog(
            business_id=current_user.business_id,
            user_id=current_user.id,
            action="BARCODE_PRODUCT_SAVED",
            entity_type="Product",
            entity_id=product.id,
            old_values={"stock": str(before), "name": product.name},
            new_values={"stock": str(sp.stock_quantity), "name": product.name, "barcode": barcode, "quantity_added": str(quantity), "store_id": store.id},
            ip_address=request.headers.get("X-Forwarded-For", request.remote_addr),
            user_agent=request.user_agent.string[:1000],
        ))
        db.session.commit()
        return jsonify(
            ok=True,
            created=created,
            renamed=renamed,
            product={
                "id": product.id,
                "name": product.name,
                "barcode": product.barcode,
                "stock": str(sp.stock_quantity),
                "added": str(quantity),
                "stock_changed": bool(quantity > 0),
                "store": store.name,
                "needs_setup": sp.selling_price in (None, 0),
            },
        )
    except Exception:
        db.session.rollback()
        raise
