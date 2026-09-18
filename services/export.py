from datetime import datetime, timezone
from flask import current_app
from extensions import db
from models import Business, Store, Role, Permission, User, Category, Product, ProductAlias, PricingRule, StoreProduct, Supplier, Customer, Order, OrderItem, Sale, SaleItem, Payment, PaymentGatewayEvent, LoyaltyAccount, LoyaltyTransaction

TABLES = [Business, Store, Role, Permission, User, Category, Product, ProductAlias, PricingRule, StoreProduct, Supplier, Customer, Order, OrderItem, Sale, SaleItem, Payment, PaymentGatewayEvent, LoyaltyAccount, LoyaltyTransaction]

def export_business(business_id):
    data = {"format": "real-mart-json-v1", "exported_at": datetime.now(timezone.utc).isoformat(), "business_id": business_id, "tables": {}}
    for model in TABLES:
        rows = model.query.filter_by(business_id=business_id).all() if hasattr(model, "business_id") else model.query.all()
        data["tables"][model.__tablename__] = [
            {c.name: getattr(row, c.name).isoformat() if hasattr(getattr(row, c.name), "isoformat") else getattr(row, c.name) for c in model.__table__.columns}
            for row in rows
        ]
    return data
