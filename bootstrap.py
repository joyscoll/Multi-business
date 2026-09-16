"""Production-safe first-boot database bootstrap and catalogue seed."""
import os
import re
from decimal import Decimal
from sqlalchemy.exc import IntegrityError
from extensions import db
from models import (
    Business, Store, Role, Permission, User, Category,
    Product, PricingRule, StoreProduct,
)

ROLES = {
    "OWNER": ["*"],
    "ADMIN": ["products.view", "products.create", "products.edit", "products.delete", "sales.view", "inventory.view", "inventory.adjust", "reports.view", "payments.view", "backup.create", "users.manage"],
    "MANAGER": ["products.view", "products.edit", "sales.view", "sales.create", "sales.void", "inventory.view", "inventory.adjust", "reports.view", "payments.view"],
    "CASHIER": ["products.view", "sales.create"],
    "STOCK_CONTROLLER": ["products.view", "inventory.view", "inventory.adjust"],
    "DELIVERY": [],
    "ACCOUNTANT": ["sales.view", "payments.view", "reports.view"],
}

# Stable, real-photograph product imagery hosted by Unsplash. The catalogue is
# deliberately broad; administrators can replace every image with their own.
IMAGE_BY_CATEGORY = {
    "fresh-food": "https://images.unsplash.com/photo-1550583724-b2692b85b150?auto=format&fit=crop&w=700&q=82",
    "bakery": "https://images.unsplash.com/photo-1509440159596-0249088772ff?auto=format&fit=crop&w=700&q=82",
    "produce": "https://images.unsplash.com/photo-1610832958506-aa56368176cf?auto=format&fit=crop&w=700&q=82",
    "meat": "https://images.unsplash.com/photo-1607623814075-e51df1bdc82f?auto=format&fit=crop&w=700&q=82",
    "drinks": "https://images.unsplash.com/photo-1544145945-f90425340c7e?auto=format&fit=crop&w=700&q=82",
    "pantry": "https://images.unsplash.com/photo-1583875762487-5f8f7c9efc9c?auto=format&fit=crop&w=700&q=82",
    "snacks": "https://images.unsplash.com/photo-1599599810769-bcde5a160d32?auto=format&fit=crop&w=700&q=82",
    "personal-care": "https://images.unsplash.com/photo-1556228578-8c89e6adf883?auto=format&fit=crop&w=700&q=82",
    "household": "https://images.unsplash.com/photo-1583947215259-38e31be8751f?auto=format&fit=crop&w=700&q=82",
    "baby": "https://images.unsplash.com/photo-1604917877934-07d8d248d396?auto=format&fit=crop&w=700&q=82",
    "stationery": "https://images.unsplash.com/photo-1455390582262-044cdead277a?auto=format&fit=crop&w=700&q=82",
    "local": "https://images.unsplash.com/photo-1606914469633-bd3921af41e0?auto=format&fit=crop&w=700&q=82",
}

CATALOG = {
    "Fresh Food": [
        ("Fresh Whole Milk 500ml", 55, 70, "fresh-food"), ("Fresh Whole Milk 1L", 105, 125, "fresh-food"),
        ("Mala 500ml", 70, 90, "fresh-food"), ("Plain Yoghurt 500ml", 80, 100, "fresh-food"),
        ("Greek Style Yoghurt 450g", 120, 145, "fresh-food"), ("Salted Butter 250g", 180, 220, "fresh-food"),
        ("Margarine 500g", 190, 235, "fresh-food"), ("Cheddar Cheese 200g", 260, 320, "fresh-food"),
        ("Farm Eggs 6 Pack", 105, 130, "fresh-food"), ("Farm Eggs 30 Pack", 490, 560, "fresh-food"),
        ("Fresh Cream 250ml", 130, 160, "fresh-food"), ("Cooking Cream 250ml", 145, 175, "fresh-food"),
    ],
    "Bakery": [
        ("White Bread 400g", 55, 70, "bakery"), ("Brown Bread 400g", 65, 82, "bakery"),
        ("High Fibre Bread 400g", 75, 95, "bakery"), ("Bread Rolls 6 Pack", 70, 90, "bakery"),
        ("Tea Scones 6 Pack", 75, 95, "bakery"), ("Mandazi 6 Pack", 60, 80, "bakery"),
        ("Chapati 5 Pack", 80, 110, "bakery"), ("Cinnamon Buns 4 Pack", 140, 175, "bakery"),
        ("Plain Cake 400g", 210, 260, "bakery"), ("Muffins 4 Pack", 150, 190, "bakery"),
    ],
    "Fruits & Vegetables": [
        ("Bananas 1kg", 90, 120, "produce"), ("Oranges 1kg", 110, 145, "produce"),
        ("Apples 1kg", 180, 230, "produce"), ("Mangoes 1kg", 100, 145, "produce"),
        ("Avocado 1kg", 110, 150, "produce"), ("Tomatoes 1kg", 80, 110, "produce"),
        ("Onions 1kg", 75, 100, "produce"), ("Potatoes 2kg", 120, 155, "produce"),
        ("Carrots 1kg", 75, 100, "produce"), ("Spinach Bunch", 25, 35, "produce"),
        ("Sukuma Wiki Bunch", 25, 35, "produce"), ("Cabbage 1 Head", 55, 75, "produce"),
        ("Lemons 500g", 75, 100, "produce"), ("Garlic 250g", 70, 95, "produce"),
    ],
    "Meat & Poultry": [
        ("Chicken Whole 1kg", 420, 520, "meat"), ("Chicken Breast 500g", 300, 380, "meat"),
        ("Beef Steak 500g", 350, 430, "meat"), ("Beef Mince 500g", 310, 390, "meat"),
        ("Beef Liver 500g", 180, 230, "meat"), ("Goat Meat 500g", 360, 450, "meat"),
        ("Sausages 500g", 260, 320, "meat"), ("Smokies 500g", 230, 285, "meat"),
        ("Bacon 250g", 260, 325, "meat"), ("Beef Samosas 6 Pack", 150, 195, "meat"),
    ],
    "Drinks": [
        ("Drinking Water 500ml", 25, 35, "drinks"), ("Drinking Water 1L", 40, 50, "drinks"),
        ("Soda 500ml", 55, 70, "drinks"), ("Soda 1.25L", 95, 120, "drinks"),
        ("Soda 2L", 120, 145, "drinks"), ("Orange Juice 1L", 170, 210, "drinks"),
        ("Apple Juice 1L", 170, 210, "drinks"), ("Mango Juice 1L", 160, 200, "drinks"),
        ("Energy Drink 500ml", 110, 140, "drinks"), ("Sparkling Water 500ml", 55, 70, "drinks"),
        ("Malted Drink 400g", 230, 285, "drinks"), ("Instant Coffee 100g", 260, 320, "drinks"),
        ("Tea Bags 100s", 180, 230, "drinks"),
    ],
    "Pantry": [
        ("Maize Flour 2kg", 145, 175, "pantry"), ("Maize Flour 1kg", 75, 95, "pantry"),
        ("Sifted Maize Flour 2kg", 160, 190, "pantry"), ("Wheat Flour 2kg", 155, 190, "pantry"),
        ("Self Raising Flour 2kg", 180, 215, "pantry"), ("Sugar 2kg", 250, 295, "pantry"),
        ("Sugar 1kg", 125, 150, "pantry"), ("Rice 2kg", 270, 330, "pantry"),
        ("Pishori Rice 2kg", 330, 400, "pantry"), ("Cooking Oil 1L", 210, 250, "pantry"),
        ("Cooking Oil 2L", 400, 470, "pantry"), ("Salt 1kg", 45, 60, "pantry"),
        ("Beans 1kg", 180, 230, "pantry"), ("Ndengu 1kg", 180, 230, "pantry"),
        ("Njahi 1kg", 220, 275, "pantry"), ("Green Grams 1kg", 180, 230, "pantry"),
        ("Kamande 1kg", 190, 240, "pantry"), ("Lentils 1kg", 180, 230, "pantry"),
        ("Wimbi Flour 1kg", 170, 215, "local"), ("Uji Mix 1kg", 170, 215, "local"),
        ("Cassava Flour 1kg", 150, 190, "local"), ("Sorghum Flour 1kg", 150, 190, "local"),
        ("Groundnuts 500g", 180, 230, "pantry"), ("Peanut Butter 400g", 250, 310, "pantry"),
        ("Tomato Paste 400g", 120, 150, "pantry"), ("Baked Beans 420g", 130, 160, "pantry"),
        ("Spaghetti 500g", 110, 140, "pantry"), ("Pasta 500g", 100, 130, "pantry"),
        ("Noodles 4 Pack", 110, 145, "pantry"), ("Wheat Biscuits 500g", 140, 180, "pantry"),
    ],
    "Snacks & Treats": [
        ("Potato Crisps 100g", 90, 115, "snacks"), ("Popcorn 100g", 65, 85, "snacks"),
        ("Chocolate Bar 80g", 90, 120, "snacks"), ("Milk Chocolate 100g", 180, 220, "snacks"),
        ("Peanut Cookies 150g", 90, 120, "snacks"), ("Cream Crackers 200g", 85, 110, "snacks"),
        ("Vanilla Biscuits 200g", 90, 120, "snacks"), ("Digestive Biscuits 400g", 180, 220, "snacks"),
        ("Chewing Gum 10s", 45, 60, "snacks"), ("Gummy Sweets 100g", 70, 95, "snacks"),
        ("Peanuts 250g", 120, 150, "snacks"), ("Cashew Nuts 200g", 260, 320, "snacks"),
    ],
    "Personal Care": [
        ("Bathing Soap 125g", 55, 75, "personal-care"), ("Beauty Soap 125g", 70, 95, "personal-care"),
        ("Liquid Hand Wash 500ml", 150, 190, "personal-care"), ("Petroleum Jelly 250ml", 180, 220, "personal-care"),
        ("Body Lotion 400ml", 320, 390, "personal-care"), ("Shampoo 400ml", 330, 410, "personal-care"),
        ("Conditioner 400ml", 340, 420, "personal-care"), ("Toothpaste 150ml", 130, 165, "personal-care"),
        ("Toothbrush Medium", 75, 100, "personal-care"), ("Mouthwash 500ml", 320, 390, "personal-care"),
        ("Deodorant Spray 150ml", 250, 310, "personal-care"), ("Roll On Deodorant", 190, 235, "personal-care"),
        ("Men's Shaving Foam", 290, 360, "personal-care"), ("Men's Razor Pack", 210, 260, "personal-care"),
        ("Beard Oil 30ml", 280, 350, "personal-care"), ("Hair Food 250ml", 180, 230, "personal-care"),
        ("Hair Relaxer Kit", 320, 390, "personal-care"), ("Sanitary Pads 10s", 140, 180, "personal-care"),
        ("Cotton Wool 100g", 90, 120, "personal-care"), ("Tissues Pocket 10 Pack", 60, 80, "household"),
    ],
    "Household": [
        ("Toilet Tissue 4 Pack", 160, 205, "household"), ("Toilet Tissue 10 Pack", 390, 470, "household"),
        ("Kitchen Towels 2 Roll", 170, 220, "household"), ("Laundry Powder 1kg", 180, 225, "household"),
        ("Laundry Powder 2kg", 350, 430, "household"), ("Dishwashing Liquid 500ml", 120, 155, "household"),
        ("Bleach 1L", 105, 135, "household"), ("Toilet Cleaner 750ml", 150, 190, "household"),
        ("Glass Cleaner 500ml", 160, 205, "household"), ("Floor Cleaner 1L", 180, 230, "household"),
        ("Multipurpose Cleaner 750ml", 170, 215, "household"), ("Sponge Scourer 3 Pack", 70, 95, "household"),
        ("Bin Bags 20 Pack", 120, 155, "household"), ("Air Freshener 300ml", 190, 240, "household"),
        ("Mosquito Repellent", 170, 220, "household"), ("Matches 10 Pack", 35, 50, "household"),
        ("Candles 6 Pack", 80, 110, "household"), ("Aluminium Foil 10m", 160, 205, "household"),
        ("Cling Film 20m", 150, 190, "household"), ("Food Storage Bags 20s", 140, 180, "household"),
    ],
    "Baby": [
        ("Baby Diapers Newborn 24s", 560, 690, "baby"), ("Baby Diapers Medium 24s", 650, 790, "baby"),
        ("Baby Wipes 80s", 150, 190, "baby"), ("Baby Lotion 300ml", 220, 275, "baby"),
        ("Baby Shampoo 200ml", 210, 260, "baby"), ("Baby Powder 200g", 180, 225, "baby"),
        ("Baby Bath Soap", 100, 130, "baby"), ("Infant Cereal 400g", 250, 320, "baby"),
    ],
    "Stationery": [
        ("A4 Printing Paper 80gsm", 520, 620, "stationery"), ("Ball Pens Blue 10 Pack", 100, 140, "stationery"),
        ("Ball Pens Black 10 Pack", 100, 140, "stationery"), ("HB Pencils 12 Pack", 120, 160, "stationery"),
        ("Exercise Book 200 Pages", 110, 140, "stationery"), ("Counter Book 160 Pages", 100, 130, "stationery"),
        ("Permanent Marker", 55, 75, "stationery"), ("Glue Stick 20g", 45, 65, "stationery"),
        ("Clear Tape", 55, 75, "stationery"), ("School Ruler 30cm", 35, 50, "stationery"),
    ],
}


def slugify(value):
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def seed_defaults():
    business = Business.query.first()
    if not business:
        business = Business(
            name=os.getenv("BUSINESS_NAME", "REAL MART"),
            currency=os.getenv("CURRENCY", "KES"),
            timezone=os.getenv("TIMEZONE", "Africa/Nairobi"),
        )
        db.session.add(business)
        db.session.flush()

    store = Store.query.filter_by(business_id=business.id, code="MAIN").first()
    if not store:
        store = Store(business_id=business.id, name="Main Branch", code="MAIN", is_active=True)
        db.session.add(store)
        db.session.flush()

    # Permissions and roles can be safely created on subsequent upgrades.
    existing_permissions = {p.code: p for p in Permission.query.all()}
    codes = sorted({code for values in ROLES.values() for code in values if code != "*"})
    for code in codes:
        if code not in existing_permissions:
            p = Permission(code=code, description=code.replace('.', ' '))
            db.session.add(p); existing_permissions[code] = p
    db.session.flush()

    roles = {r.name: r for r in Role.query.all()}
    for name, role_codes in ROLES.items():
        role = roles.get(name)
        if not role:
            role = Role(name=name); db.session.add(role); roles[name] = role
        role.permissions = [] if role_codes == ["*"] else [existing_permissions[c] for c in role_codes]
    db.session.flush()

    admin_username = os.getenv("ADMIN_USERNAME", "").strip()
    admin_password = os.getenv("ADMIN_PASSWORD", "")
    production = os.getenv("FLASK_ENV", "development") == "production"
    if not admin_username or not admin_password:
        raise RuntimeError("ADMIN_USERNAME and ADMIN_PASSWORD must be set in the environment")

    owner = User.query.filter_by(business_id=business.id, role_id=roles["OWNER"].id).first()
    if not owner:
        owner = User(
            business_id=business.id,
            store_id=store.id,
            name="Master Administrator",
            email=None,
            username=admin_username,
            role_id=roles["OWNER"].id,
            is_active=True,
        )
        db.session.add(owner)
    else:
        owner.username = admin_username
        owner.name = "Master Administrator"
        owner.store_id = store.id
        owner.is_active = True
    owner.set_password(admin_password)

    # Seed a serious starter catalogue once; later admin changes are preserved.
    category_map = {c.slug: c for c in Category.query.filter_by(business_id=business.id).all()}
    for category_name in CATALOG:
        slug = slugify(category_name)
        if slug not in category_map:
            cat = Category(business_id=business.id, name=category_name, slug=slug, sort_order=len(category_map), is_active=True)
            db.session.add(cat); category_map[slug] = cat
    db.session.flush()

    default_rule = PricingRule.query.filter_by(business_id=business.id, store_id=store.id).first()
    if not default_rule:
        default_rule = PricingRule(business_id=business.id, store_id=store.id, name="Default", rule_type="COST_PLUS_PERCENT", margin_percent=20, rounding_rule=5, is_active=True, priority=10)
        db.session.add(default_rule); db.session.flush()

    existing = {p.name.lower(): p for p in Product.query.all()}
    barcode_counter = 500100000000
    for category_name, products in CATALOG.items():
        category = category_map[slugify(category_name)]
        for name, cost, price, image_group in products:
            if name.lower() in existing:
                continue
            barcode_counter += 1
            product = Product(
                name=name,
                slug=slugify(name),
                barcode=str(barcode_counter),
                sku=f"RM-{barcode_counter}",
                brand=name.split()[0] if name else "",
                description=f"{name}. Available for online ordering when this item is enabled for the selected mart.",
                category_id=category.id,
                unit="unit",
                search_keywords=name.lower(),
                image_url=IMAGE_BY_CATEGORY.get(image_group, IMAGE_BY_CATEGORY["pantry"]),
                status="ACTIVE",
            )
            db.session.add(product); db.session.flush()
            db.session.add(StoreProduct(
                store_id=store.id, product_id=product.id,
                cost_price=Decimal(str(cost)), selling_price=Decimal(str(price)),
                stock_quantity=100, reorder_level=10,
                is_available=True, available_online=True, available_pos=True,
                pricing_rule_id=default_rule.id,
            ))

    db.session.commit()


def bootstrap_database():
    db.create_all()
    try:
        seed_defaults()
    except IntegrityError:
        db.session.rollback()
        # Another worker may have raced us during first boot. A subsequent
        # request can complete bootstrap work without exposing raw DB errors.


def database_summary():
    return {
        "dialect": db.engine.url.get_backend_name(),
        "database": str(db.engine.url.database or ""),
        "has_business": Business.query.first() is not None,
        "store_count": Store.query.count(),
    }
