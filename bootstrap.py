"""Production-safe first-boot database bootstrap.

The Render service may start with `gunicorn app:app` without executing
init_db.py.  This module makes the application self-healing for a fresh
SQLite/Postgres database while keeping the explicit init script available.
"""
import os
from sqlalchemy.exc import IntegrityError
from extensions import db
from models import (
    Business, Store, Role, Permission, User, Category,
    Product, PricingRule, StoreProduct,
)

ROLES = {
    "OWNER": ["*"],
    "ADMIN": ["products.view", "products.create", "products.edit", "products.delete", "sales.view", "inventory.view", "reports.view", "payments.view", "backup.create", "users.manage"],
    "MANAGER": ["products.view", "products.edit", "sales.view", "sales.create", "sales.void", "inventory.view", "inventory.adjust", "reports.view", "payments.view"],
    "CASHIER": ["products.view", "sales.create"],
    "STOCK_CONTROLLER": ["products.view", "inventory.view", "inventory.adjust"],
    "DELIVERY": [],
    "ACCOUNTANT": ["sales.view", "payments.view", "reports.view"],
}


def seed_defaults():
    """Create the minimum business/store/security/catalogue records once."""
    business = Business.query.first()
    if business:
        return

    business = Business(
        name=os.getenv("BUSINESS_NAME", "REAL MART"),
        currency=os.getenv("CURRENCY", "KES"),
        timezone=os.getenv("TIMEZONE", "Africa/Nairobi"),
    )
    db.session.add(business)
    db.session.flush()

    store = Store(business_id=business.id, name="Main Branch", code="MAIN")
    db.session.add(store)
    db.session.flush()

    codes = sorted({code for values in ROLES.values() for code in values if code != "*"})
    permissions = {}
    for code in codes:
        permission = Permission(code=code, description=code)
        db.session.add(permission)
        permissions[code] = permission
    db.session.flush()

    roles = {}
    for name, role_codes in ROLES.items():
        role = Role(name=name)
        role.permissions = [] if role_codes == ["*"] else [permissions[c] for c in role_codes]
        db.session.add(role)
        roles[name] = role
    db.session.flush()

    email = os.getenv("ADMIN_EMAIL", "admin@realmart.local").lower()
    user = User(
        business_id=business.id,
        store_id=store.id,
        name="REAL MART Owner",
        email=email,
        username="owner",
        role_id=roles["OWNER"].id,
    )
    user.set_password(os.getenv("ADMIN_PASSWORD", "ChangeMe123!"))
    db.session.add(user)

    category = Category(business_id=business.id, name="General", slug="general")
    db.session.add(category)
    db.session.flush()

    rule = PricingRule(
        business_id=business.id,
        store_id=store.id,
        name="Default 20% Cost Plus",
        rule_type="COST_PLUS_PERCENT",
        margin_percent=20,
        rounding_rule=5,
        is_active=True,
        priority=10,
    )
    db.session.add(rule)
    db.session.flush()

    samples = [
        ("Demo Fresh Milk 500ml", "500000000001", 60, 75),
        ("Demo Bread 400g", "500000000002", 50, 65),
        ("Demo Sugar 2kg", "500000000003", 220, 280),
    ]
    for name, barcode, cost, price in samples:
        product = Product(
            name=name,
            slug=name.lower().replace(" ", "-"),
            barcode=barcode,
            sku=barcode,
            category_id=category.id,
            unit="unit",
            search_keywords=name.lower(),
        )
        db.session.add(product)
        db.session.flush()
        db.session.add(
            StoreProduct(
                store_id=store.id,
                product_id=product.id,
                cost_price=cost,
                selling_price=price,
                stock_quantity=100,
                reorder_level=10,
                pricing_rule_id=rule.id,
            )
        )

    db.session.commit()


def bootstrap_database():
    """Ensure schema exists and seed a fresh database when it is empty."""
    with db.engine.begin() as connection:
        pass
    db.create_all()
    if Business.query.first() is None:
        try:
            seed_defaults()
        except IntegrityError:
            # Another Render/Gunicorn worker can initialize at the same time.
            db.session.rollback()


def database_summary():
    return {
        "dialect": db.engine.url.get_backend_name(),
        "database": str(db.engine.url.database or ""),
        "has_business": Business.query.first() is not None,
        "store_count": Store.query.count(),
    }
