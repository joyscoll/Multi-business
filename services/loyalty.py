from decimal import Decimal, ROUND_FLOOR

from extensions import db
from models import Customer, LoyaltyAccount, LoyaltyTransaction, SystemSetting


def _points_per_100(business_id):
    setting = SystemSetting.query.filter_by(
        business_id=business_id, key="loyalty_points_per_100"
    ).first()
    try:
        return max(0, int(setting.value)) if setting else 1
    except (TypeError, ValueError):
        return 1


def award_purchase_points(business_id, customer_id, amount, reference_type, reference_id):
    if not customer_id:
        return 0
    customer = db.session.get(Customer, customer_id)
    if not customer or not customer.is_active:
        return 0
    try:
        amount = Decimal(str(amount or 0))
    except Exception:
        return 0
    points_per_100 = _points_per_100(business_id)
    points = int((amount / Decimal("100")).to_integral_value(rounding=ROUND_FLOOR)) * points_per_100
    if points <= 0:
        return 0

    existing = LoyaltyTransaction.query.filter_by(
        reference_type=reference_type, reference_id=reference_id, transaction_type="EARN"
    ).first()
    if existing:
        return existing.points

    account = LoyaltyAccount.query.filter_by(
        business_id=business_id, customer_id=customer_id
    ).first()
    if not account:
        account = LoyaltyAccount(
            business_id=business_id, customer_id=customer_id,
            points_balance=0, lifetime_points=0
        )
        db.session.add(account)
        db.session.flush()

    account.points_balance += points
    account.lifetime_points += points
    db.session.add(LoyaltyTransaction(
        business_id=business_id, customer_id=customer_id, points=points,
        transaction_type="EARN", reference_type=reference_type,
        reference_id=reference_id,
        note=f"Purchase reward at {points_per_100} point(s) per KES 100"
    ))
    return points
