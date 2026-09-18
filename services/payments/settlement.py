from decimal import Decimal

from extensions import db
from models import Payment, Order, OrderItem, Sale, SaleItem, StoreProduct, InventoryTransaction, now
from services.loyalty import award_purchase_points


def _has_duplicate_reference(payment, reference):
    return bool(Payment.query.filter(
        Payment.provider_transaction_id == reference,
        Payment.id != payment.id
    ).first())


def settle_order_payment(order, payment, actor_id=None):
    if payment.status == "PAID":
        return True
    for line in OrderItem.query.filter_by(order_id=order.id).all():
        sp = StoreProduct.query.filter_by(
            store_id=order.store_id, product_id=line.product_id
        ).first()
        if not sp:
            return False
        available = Decimal(sp.stock_quantity or 0)
        reserved = Decimal(sp.reserved_quantity or 0)
        qty = Decimal(line.quantity)
        if reserved < qty or available < qty:
            return False

    reference = (payment.external_reference or "").strip().upper()
    if payment.provider_transaction_id:
        reference = payment.provider_transaction_id
    if not reference or _has_duplicate_reference(payment, reference):
        return False

    payment.status = "PAID"
    payment.provider_transaction_id = reference
    payment.completed_at = now
    order.payment_status = "PAID"
    order.status = "CONFIRMED"

    for line in OrderItem.query.filter_by(order_id=order.id).all():
        sp = StoreProduct.query.filter_by(
            store_id=order.store_id, product_id=line.product_id
        ).first()
        qty = Decimal(line.quantity)
        sp.reserved_quantity = max(Decimal("0"), Decimal(sp.reserved_quantity or 0) - qty)
        sp.stock_quantity = Decimal(sp.stock_quantity or 0) - qty
        db.session.add(InventoryTransaction(
            store_id=order.store_id, product_id=line.product_id,
            transaction_type="SALE", quantity=-qty, unit_cost=sp.cost_price,
            reference_type="ORDER", reference_id=order.id, created_by=actor_id
        ))

    award_purchase_points(order.business_id, order.customer_id, order.total, "ORDER", order.id)
    return True


def settle_sale_payment(sale, payment, actor_id=None):
    if payment.status == "PAID":
        return True
    for line in SaleItem.query.filter_by(sale_id=sale.id).all():
        sp = StoreProduct.query.filter_by(
            store_id=sale.store_id, product_id=line.product_id
        ).first()
        if not sp:
            return False
        available = Decimal(sp.stock_quantity or 0)
        reserved = Decimal(sp.reserved_quantity or 0)
        qty = Decimal(line.quantity)
        if reserved < qty or available < qty:
            return False

    reference = (payment.provider_transaction_id or payment.external_reference or "").strip().upper()
    if not reference or _has_duplicate_reference(payment, reference):
        return False

    payment.status = "PAID"
    payment.provider_transaction_id = reference
    payment.completed_at = now
    sale.status = "COMPLETED"
    sale.payment_status = "PAID"
    sale.completed_at = now

    for line in SaleItem.query.filter_by(sale_id=sale.id).all():
        sp = StoreProduct.query.filter_by(
            store_id=sale.store_id, product_id=line.product_id
        ).first()
        qty = Decimal(line.quantity)
        sp.reserved_quantity = max(Decimal("0"), Decimal(sp.reserved_quantity or 0) - qty)
        sp.stock_quantity = Decimal(sp.stock_quantity or 0) - qty
        db.session.add(InventoryTransaction(
            store_id=sale.store_id, product_id=line.product_id,
            transaction_type="SALE", quantity=-qty, unit_cost=sp.cost_price,
            reference_type="SALE", reference_id=sale.id, created_by=actor_id
        ))
    return True
