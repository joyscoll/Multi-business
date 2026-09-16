from decimal import Decimal
from flask import Blueprint, jsonify, render_template, request
from flask_login import current_user, login_required
from extensions import csrf
from extensions import db
from models import Sale, SaleItem, StoreProduct, InventoryTransaction, Payment, Shift, now
from services.audit import audit

bp = Blueprint("pos", __name__)

@bp.get("/pos")
@login_required
def dashboard():
    return render_template("pos/index.html")

@bp.get("/pos/receipt/<receipt_number>")
@login_required
def receipt(receipt_number):
    sale = Sale.query.filter_by(receipt_number=receipt_number).first_or_404()
    items = SaleItem.query.filter_by(sale_id=sale.id).all()
    return render_template("pos/receipt.html", sale=sale, items=items)

@csrf.exempt
@bp.post("/api/pos/sales")
@login_required
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
                status="COMPLETED" if payment_method == "CASH" else "PENDING", payment_status="PAID" if payment_method == "CASH" else "PENDING", completed_at=now() if payment_method == "CASH" else None)
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
@login_required
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
