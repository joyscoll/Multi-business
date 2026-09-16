import os
from app import app
from extensions import db
from models import Business, Store, Role, Permission, User, Category, Product, PricingRule, StoreProduct
from werkzeug.security import generate_password_hash

ROLES = {"OWNER": ["*"], "ADMIN": ["products.view","products.create","products.edit","products.delete","sales.view","inventory.view","reports.view","payments.view","backup.create","users.manage"], "MANAGER": ["products.view","products.edit","sales.view","sales.create","sales.void","inventory.view","inventory.adjust","reports.view","payments.view"], "CASHIER": ["products.view","sales.create"], "STOCK_CONTROLLER": ["products.view","inventory.view","inventory.adjust"], "DELIVERY": [], "ACCOUNTANT": ["sales.view","payments.view","reports.view"]}

with app.app_context():
    db.create_all()
    b = Business.query.first()
    if not b:
        b = Business(name=os.getenv("BUSINESS_NAME","REAL MART"), currency=os.getenv("CURRENCY","KES"), timezone=os.getenv("TIMEZONE","Africa/Nairobi"))
        db.session.add(b); db.session.flush()
    store = Store.query.filter_by(business_id=b.id).first()
    if not store:
        store = Store(business_id=b.id, name="Main Branch", code="MAIN")
        db.session.add(store); db.session.flush()
    all_codes = sorted({c for vals in ROLES.values() for c in vals if c != "*"})
    perms = {}
    for code in all_codes:
        p = Permission.query.filter_by(code=code).first() or Permission(code=code, description=code)
        db.session.add(p); perms[code]=p
    db.session.flush()
    roles={}
    for name,codes in ROLES.items():
        r = Role.query.filter_by(name=name).first() or Role(name=name)
        r.permissions=[]
        if codes != ["*"]:
            r.permissions=[perms[c] for c in codes]
        db.session.add(r); roles[name]=r
    db.session.flush()
    email=os.getenv("ADMIN_EMAIL","admin@realmart.local").lower()
    user=User.query.filter_by(email=email).first()
    if not user:
        user=User(business_id=b.id,store_id=store.id,name="REAL MART Owner",email=email,username="owner",role_id=roles["OWNER"].id,password_hash=generate_password_hash(os.getenv("ADMIN_PASSWORD","ChangeMe123!")))
        db.session.add(user)
    cat=Category.query.filter_by(business_id=b.id,name="General").first()
    if not cat:
        cat=Category(business_id=b.id,name="General",slug="general")
        db.session.add(cat); db.session.flush()
    if not PricingRule.query.filter_by(business_id=b.id,name="Default 20% Cost Plus").first():
        rule=PricingRule(business_id=b.id,store_id=store.id,name="Default 20% Cost Plus",rule_type="COST_PLUS_PERCENT",margin_percent=20,rounding_rule=5,is_active=True,priority=10)
        db.session.add(rule); db.session.flush()
    samples=[("Demo Fresh Milk 500ml","500000000001",60,75), ("Demo Bread 400g","500000000002",50,65), ("Demo Sugar 2kg","500000000003",220,280)]
    for name,barcode,cost,price in samples:
        product=Product.query.filter_by(barcode=barcode).first()
        if not product:
            slug=name.lower().replace(" ","-")
            product=Product(name=name,slug=slug,barcode=barcode,sku=barcode,category_id=cat.id,unit="unit",search_keywords=name.lower())
            db.session.add(product); db.session.flush()
        sp=StoreProduct.query.filter_by(store_id=store.id,product_id=product.id).first()
        if not sp:
            rule=PricingRule.query.filter_by(business_id=b.id,name="Default 20% Cost Plus").first()
            sp=StoreProduct(store_id=store.id,product_id=product.id,cost_price=cost,selling_price=price,stock_quantity=100,reorder_level=10,pricing_rule_id=rule.id)
            db.session.add(sp)
    db.session.commit()
    print("Seed complete", email)
