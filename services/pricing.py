from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone
from models import PricingRule

def round_price(value: Decimal, increment: Decimal | None):
    increment = increment or Decimal("1")
    if increment <= 0:
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return (value / increment).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * increment

def suggested_price(store_product, rule: PricingRule | None):
    cost = Decimal(store_product.cost_price or 0)
    if not rule or not rule.is_active:
        return Decimal(store_product.selling_price or 0)
    if rule.rule_type == "FIXED_MARKUP":
        price = cost + Decimal(rule.fixed_markup or 0)
    else:
        price = cost * (Decimal("1") + Decimal(rule.margin_percent or 0) / Decimal("100"))
    minimum = Decimal(store_product.minimum_price or 0)
    maximum = Decimal(store_product.maximum_price) if store_product.maximum_price is not None else None
    if minimum and price < minimum:
        price = minimum
    if maximum and price > maximum:
        price = maximum
    return round_price(price, Decimal(rule.rounding_rule or 1))
