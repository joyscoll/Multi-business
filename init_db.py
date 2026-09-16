"""Safe first-boot initializer for a fresh Render/Postgres or local SQLite database."""
from app import app
from extensions import db
from models import Business, Store, Role, Permission, User, Category, Product, PricingRule, StoreProduct
from werkzeug.security import generate_password_hash
import os

ROLES = {
    "OWNER": ["*"],
    "ADMIN": ["products.view","products.create","products.edit","products.delete","sales.view","inventory.view","reports.view","payments.view","backup.create","users.manage"],
    "MANAGER": ["products.view","products.edit","sales.view","sales.create","sales.void","inventory.view","inventory.adjust","reports.view","payments.view"],
    "CASHIER": ["products.view","sales.create"],
    "STOCK_CONTROLLER": ["products.view","inventory.view","inventory.adjust"],
    "DELIVERY": [],
    "ACCOUNTANT": ["sales.view","payments.view","reports.view"],
}


def run():
    with app.app_context():
        db.create_all()
        business = Business.query.first()
        if not business:
            business = Business(name=os.getenv("BUSINESS_NAME", "REAL MART"), currency=os.getenv("CURRENCY", "KES"), timezone=os.getenv("TIMEZONE", "Africa/Nairobi"))
            db.session.add(business); db.session.flush()
        store = Store.query.filter_by(business_id=business.id).first()
        if not store:
            store = Store(business_id=business.id, name="Main Branch", code="MAIN")
            db.session.add(store); db.session.flush()

        codes = sorted({x for role in ROLES.values() for x in role if x != "*"})
        permissions = {}
        for code in codes:
            p = Permission.query.filter_by(code=code).first() or Permission(code=code, description=code)
            db.session.add(p); permissions[code] = p
        db.session.flush()
        roles = {}
        for name, codes_for_role in ROLES.items():
            role = Role.query.filter_by(name=name).first() or Role(name=name)
            role.permissions = [] if codes_for_role == ["*"] else [permissions[c] for c in codes_for_role]
            db.session.add(role); roles[name] = role
        db.session.flush()

        email = os.getenv("ADMIN_EMAIL", "admin@realmart.local").lower()
        admin_password = os.getenv("ADMIN_PASSWORD", "ChangeMe123!")
        user = User.query.filter_by(email=email).first()
        if not user:
            user = User(business_id=business.id, store_id=store.id, name="REAL MART Owner", email=email, username="owner", role_id=roles["OWNER"].id)
            user.set_password(admin_password)
            db.session.add(user)

        category = Category.query.filter_by(business_id=business.id, name="General").first()
        if not category:
            category = Category(business_id=business.id, name="General", slug="general")
            db.session.add(category); db.session.flush()
        rule = PricingRule.query.filter_by(business_id=business.id, name="Default 20% Cost Plus").first()
        if not rule:
            rule = PricingRule(business_id=business.id, store_id=store.id, name="Default 20% Cost Plus", rule_type="COST_PLUS_PERCENT", margin_percent=20, rounding_rule=5, is_active=True, priority=10)
            db.session.add(rule); db.session.flush()

        samples = [
            ("Demo Fresh Milk 500ml", "500000000001", 60, 75),
            ("Demo Bread 400g", "500000000002", 50, 65),
            ("Demo Sugar 2kg", "500000000003", 220, 280),
        ]
        for name, barcode, cost, price in samples:
            product = Product.query.filter_by(barcode=barcode).first()
            if not product:
                product = Product(name=name, slug=name.lower().replace(" ", "-"), barcode=barcode, sku=barcode, category_id=category.id, unit="unit", search_keywords=name.lower())
                db.session.add(product); db.session.flush()
            if not StoreProduct.query.filter_by(store_id=store.id, product_id=product.id).first():
                db.session.add(StoreProduct(store_id=store.id, product_id=product.id, cost_price=cost, selling_price=price, stock_quantity=100, reorder_level=10, pricing_rule_id=rule.id))
        db.session.commit()
        print(f"REAL MART database ready. Admin: {email}")


if __name__ == "__main__":
    run()
