from decimal import Decimal

from extensions import db
from models import Payment, Order, OrderItem, Sale, SaleItem, StoreProduct, InventoryTransaction, now
from services.loyalty import award_purchase_points


COUNTED_PAYMENT_METHODS = {
    "MPESA", "MPESA_TILL", "MPESA_GATEWAY", "CASH", "CARD", "BANK", "OTHER"
}


def _has_duplicate_reference(payment, reference):
    if not reference:
        return False
    return bool(Payment.query.filter(
        Payment.provider_transaction_id == reference,
        Payment.id != payment.id
    ).first())


def order_received_total(order):
    total = db.session.query(db.func.coalesce(db.func.sum(Payment.amount), 0)).filter(
        Payment.order_id == order.id,
        Payment.status == "PAID",
        Payment.method.in_(COUNTED_PAYMENT_METHODS),
    ).scalar() or 0
    return Decimal(str(total))


def sale_received_total(sale):
    total = db.session.query(db.func.coalesce(db.func.sum(Payment.amount), 0)).filter(
        Payment.sale_id == sale.id,
        Payment.status == "PAID",
        Payment.method.in_(COUNTED_PAYMENT_METHODS),
    ).scalar() or 0
    return Decimal(str(total))


def order_outstanding(order):
    return max(Decimal("0"), Decimal(str(order.total or 0)) - order_received_total(order))


def sale_outstanding(sale):
    return max(Decimal("0"), Decimal(str(sale.total or 0)) - sale_received_total(sale))


def _reserved_order_stock_ok(order):
    for line in OrderItem.query.filter_by(order_id=order.id).all():
        sp = StoreProduct.query.filter_by(store_id=order.store_id, product_id=line.product_id).first()
        if not sp:
            return False
        available = Decimal(sp.stock_quantity or 0)
        reserved = Decimal(sp.reserved_quantity or 0)
        if reserved < Decimal(line.quantity) or available < Decimal(line.quantity):
            return False
    return True


def _reserved_sale_stock_ok(sale):
    for line in SaleItem.query.filter_by(sale_id=sale.id).all():
        sp = StoreProduct.query.filter_by(store_id=sale.store_id, product_id=line.product_id).first()
        if not sp:
            return False
        available = Decimal(sp.stock_quantity or 0)
        reserved = Decimal(sp.reserved_quantity or 0)
        if reserved < Decimal(line.quantity) or available < Decimal(line.quantity):
            return False
    return True


def _order_stock_already_finalized(order):
    return db.session.query(InventoryTransaction.id).filter(
        InventoryTransaction.reference_type == "ORDER",
        InventoryTransaction.reference_id == order.id,
        InventoryTransaction.transaction_type == "SALE",
        InventoryTransaction.quantity < 0,
    ).first() is not None


def _sale_stock_already_finalized(sale):
    return db.session.query(InventoryTransaction.id).filter(
        InventoryTransaction.reference_type == "SALE",
        InventoryTransaction.reference_id == sale.id,
        InventoryTransaction.transaction_type == "SALE",
        InventoryTransaction.quantity < 0,
    ).first() is not None


def _finalize_order_stock(order, actor_id=None):
    if _order_stock_already_finalized(order):
        return True
    if not _reserved_order_stock_ok(order):
        return False
    for line in OrderItem.query.filter_by(order_id=order.id).all():
        sp = StoreProduct.query.filter_by(store_id=order.store_id, product_id=line.product_id).first()
        qty = Decimal(line.quantity)
        sp.reserved_quantity = max(Decimal("0"), Decimal(sp.reserved_quantity or 0) - qty)
        sp.stock_quantity = Decimal(sp.stock_quantity or 0) - qty
        db.session.add(InventoryTransaction(
            store_id=order.store_id, product_id=line.product_id,
            transaction_type="SALE", quantity=-qty, unit_cost=sp.cost_price,
            reference_type="ORDER", reference_id=order.id, created_by=actor_id
        ))
    return True


def _finalize_sale_stock(sale, actor_id=None):
    if _sale_stock_already_finalized(sale):
        return True
    if not _reserved_sale_stock_ok(sale):
        return False
    for line in SaleItem.query.filter_by(sale_id=sale.id).all():
        sp = StoreProduct.query.filter_by(store_id=sale.store_id, product_id=line.product_id).first()
        qty = Decimal(line.quantity)
        sp.reserved_quantity = max(Decimal("0"), Decimal(sp.reserved_quantity or 0) - qty)
        sp.stock_quantity = Decimal(sp.stock_quantity or 0) - qty
        db.session.add(InventoryTransaction(
            store_id=sale.store_id, product_id=line.product_id,
            transaction_type="SALE", quantity=-qty, unit_cost=sp.cost_price,
            reference_type="SALE", reference_id=sale.id, created_by=actor_id
        ))
    return True


def settle_order_payment(order, payment, actor_id=None):
    """Finalize a full payment created by an approved provider/manual workflow."""
    if payment.status == "PAID":
        return True
    reference = (payment.provider_transaction_id or payment.external_reference or "").strip().upper()
    if not reference or _has_duplicate_reference(payment, reference):
        return False
    payment.status = "PAID"
    payment.provider_transaction_id = reference
    payment.completed_at = now()
    if order_received_total(order) < Decimal(str(order.total or 0)):
        order.payment_status = "PARTIALLY_PAID"
        order.status = "PENDING"
        return True
    if order_received_total(order) > Decimal(str(order.total or 0)):
        return False
    if not _finalize_order_stock(order, actor_id):
        return False
    order.payment_status = "PAID"
    order.status = "CONFIRMED"
    award_purchase_points(order.business_id, order.customer_id, order.total, "ORDER", order.id)
    return True


def settle_gateway_order_payment(order, payment, actor_id=None):
    """Apply one received M-PESA payment and auto-settle when cumulative funds equal the order total."""
    amount = Decimal(str(payment.amount or 0))
    if amount <= 0 or amount > order_outstanding(order):
        return False
    payment.status = "PAID"
    payment.completed_at = now()
    received = order_received_total(order)
    total = Decimal(str(order.total or 0))
    if received < total:
        order.payment_status = "PARTIALLY_PAID"
        order.status = "PENDING"
        return True
    if received > total:
        return False
    if not _finalize_order_stock(order, actor_id):
        return False
    order.payment_status = "PAID"
    order.status = "CONFIRMED"
    award_purchase_points(order.business_id, order.customer_id, order.total, "ORDER", order.id)
    return True


def settle_sale_payment(sale, payment, actor_id=None):
    if payment.status == "PAID":
        return True
    reference = (payment.provider_transaction_id or payment.external_reference or "").strip().upper()
    if not reference or _has_duplicate_reference(payment, reference):
        return False
    payment.status = "PAID"
    payment.provider_transaction_id = reference
    payment.completed_at = now()
    if sale_received_total(sale) < Decimal(str(sale.total or 0)):
        sale.payment_status = "PARTIALLY_PAID"
        sale.status = "PENDING"
        return True
    if sale_received_total(sale) > Decimal(str(sale.total or 0)):
        return False
    if not _finalize_sale_stock(sale, actor_id):
        return False
    sale.status = "COMPLETED"
    sale.payment_status = "PAID"
    sale.completed_at = now()
    return True


def settle_gateway_sale_payment(sale, payment, actor_id=None):
    amount = Decimal(str(payment.amount or 0))
    if amount <= 0 or amount > sale_outstanding(sale):
        return False
    payment.status = "PAID"
    payment.completed_at = now()
    received = sale_received_total(sale)
    total = Decimal(str(sale.total or 0))
    if received < total:
        sale.payment_status = "PARTIALLY_PAID"
        sale.status = "PENDING"
        return True
    if received > total:
        return False
    if not _finalize_sale_stock(sale, actor_id):
        return False
    sale.status = "COMPLETED"
    sale.payment_status = "PAID"
    sale.completed_at = now()
    return True
