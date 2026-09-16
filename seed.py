import os
import re
import hashlib
from decimal import Decimal

from extensions import db
from models import (
    Business, Store, Role, Permission, User, Category, Product, ProductAlias,
    PricingRule, StoreProduct, SystemSetting,
)
from catalog_data import CATALOG, PRICE_BANDS
from werkzeug.security import generate_password_hash

ROLES = {
    "OWNER": ["*"],
    "ADMIN": ["products.view", "products.edit", "products.delete", "sales.view", "inventory.view", "reports.view", "payments.view", "backup.create", "users.manage"],
    "MANAGER": ["products.view", "products.edit", "sales.view", "sales.create", "sales.void", "inventory.view", "inventory.adjust", "reports.view", "payments.view"],
    "CASHIER": ["products.view", "sales.create"],
    "STOCK_CONTROLLER": ["products.view", "inventory.view", "inventory.adjust"],
    "DELIVERY": [],
    "ACCOUNTANT": ["sales.view", "payments.view", "reports.view"],
}


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def image_for(name: str, category: str, brand: str) -> str:
    # Real product photography only where the exact SKU/identity is known.
    # Unknown long-tail items intentionally use no photo rather than a wrong
    # repeated supermarket image.
    exact = {
        "Superloaf White Bread 400g": "https://cdn.mafrservices.com/sys-master-root/hb4/h24/12681202991134/82690_main.jpg?im=Resize%3D376",
        "Brookside Fresh Milk 500ml": "https://cdn.mafrservices.com/pim-content/KEN/media/product/43276/1742392804/43276_main.jpg",
        "KCC Fresh Milk 500ml": "https://cdn.mafrservices.com/sys-master-root/hc1/h82/12452122132510/11666_Main.jpg?im=Resize%3D480",
        "Brookside Yoghurt Strawberry 500ml": "https://cdn.mafrservices.com/pim-content/KEN/media/product/43324/1742392804/43324_main.jpg",
        "Rina Cooking Oil 1L": "https://cdn.mafrservices.com/pim-content/KEN/media/product/21018/1742392804/21018_main.jpg",
        "Tropical Heat Chilli Lemon Crisps 100g": "https://cdn.mafrservices.com/pim-content/KEN/media/product/32275/1742392804/32275_main.jpg",
        "Del Monte Mango Juice 1L": "https://cdn.mafrservices.com/pim-content/KEN/media/product/38611/1742392804/38611_main.jpg",
        "Colgate Maximum Cavity Protection 100ml": "https://cdn.mafrservices.com/pim-content/KEN/media/product/222023/1742392804/222023_main.jpg",
    }
    return exact.get(name, "")


def starter_price(category: str, index: int) -> Decimal:
    low, high = PRICE_BANDS[category]
    ratio = (index % 10) / 9 if index % 10 else 0
    return Decimal(str(round((low + (high - low) * ratio) / 5) * 5))


def seed_defaults():
    db.create_all()
    business = Business.query.first()
    if not business:
        business = Business(
            name=os.getenv("BUSINESS_NAME", "Denmart"),
            currency=os.getenv("CURRENCY", "KES"),
            timezone=os.getenv("TIMEZONE", "Africa/Nairobi"),
        )
        db.session.add(business)
        db.session.flush()

    # Denmart is the canonical customer-facing brand for this build.
    business.name = os.getenv("BUSINESS_NAME", "Denmart").strip() or "Denmart"

    store = Store.query.filter_by(business_id=business.id).first()
    if not store:
        store = Store(business_id=business.id, name="Main Branch", code="MAIN", is_active=True)
        db.session.add(store)
        db.session.flush()

    existing_permissions = {p.code: p for p in Permission.query.all()}
    codes = sorted({code for values in ROLES.values() for code in values if code != "*"})
    for code in codes:
        if code not in existing_permissions:
            existing_permissions[code] = Permission(code=code, description=code)
            db.session.add(existing_permissions[code])
    db.session.flush()

    roles = {r.name: r for r in Role.query.all()}
    for name, role_codes in ROLES.items():
        role = roles.get(name) or Role(name=name)
        role.permissions = [] if role_codes == ["*"] else [existing_permissions[c] for c in role_codes]
        db.session.add(role)
        roles[name] = role
    db.session.flush()

    username = os.getenv("ADMIN_USERNAME", "").strip()
    password = os.getenv("ADMIN_PASSWORD", "")
    if username and password:
        owner = User.query.filter_by(username=username).first()
        if not owner:
            owner = User(
                business_id=business.id, store_id=store.id, name="Master Administrator",
                username=username, role_id=roles["OWNER"].id,
                password_hash=generate_password_hash(password), is_active=True,
            )
            db.session.add(owner)
        else:
            owner.business_id = business.id
            owner.store_id = store.id
            owner.role_id = roles["OWNER"].id
            owner.is_active = True
            owner.set_password(password)

    catalog_version = SystemSetting.query.filter_by(business_id=business.id, key="catalog_seed_version").first()
    first_catalog_boot = catalog_version is None
    refresh_catalog_assets = first_catalog_boot or (catalog_version and catalog_version.value != "denmart-2026-09-16-v9")
    if refresh_catalog_assets:
        for legacy in StoreProduct.query.filter_by(store_id=store.id).all():
            legacy.is_available = False
            legacy.available_online = False
            legacy.available_pos = False
        catalog_version = SystemSetting(
            business_id=business.id,
            key="catalog_seed_version",
            value="denmart-2026-09-16-v9",
        )
        db.session.add(catalog_version)

    category_map = {}
    for sort_order, category_name in enumerate(CATALOG):
        slug = slugify(category_name)
        category = Category.query.filter_by(business_id=business.id, slug=slug).first()
        if not category:
            category = Category(
                business_id=business.id, name=category_name, slug=slug,
                sort_order=sort_order, is_active=True,
            )
            db.session.add(category)
            db.session.flush()
        category_map[category_name] = category

    rule = PricingRule.query.filter_by(business_id=business.id, name="Default 20% Cost Plus").first()
    if not rule:
        rule = PricingRule(
            business_id=business.id, store_id=store.id, name="Default 20% Cost Plus",
            rule_type="COST_PLUS_PERCENT", margin_percent=20, rounding_rule=5,
            is_active=True, priority=10,
        )
        db.session.add(rule)
        db.session.flush()

    for category_name, products in CATALOG.items():
        category = category_map[category_name]
        for index, (name, brand, unit) in enumerate(products, start=1):
            slug = slugify(name)
            product = Product.query.filter_by(slug=slug).first()
            if not product:
                barcode = f"290{int(hashlib.sha1((brand + name).encode()).hexdigest()[:9], 16) % 900000000 + 100000000}"
                product = Product(
                    name=name,
                    slug=slug,
                    barcode=barcode,
                    sku=barcode,
                    brand=brand,
                    category_id=category.id,
                    unit=unit,
                    pack_size=unit,
                    search_keywords=f"{name.lower()} {brand.lower()} {category_name.lower()}",
                    image_url=image_for(name, category_name, brand),
                    status="ACTIVE",
                )
                db.session.add(product)
                db.session.flush()
                price = starter_price(category_name, index)
                db.session.add(StoreProduct(
                    store_id=store.id,
                    product_id=product.id,
                    cost_price=(price * Decimal("0.80")).quantize(Decimal("1")),
                    selling_price=price,
                    stock_quantity=25,
                    reserved_quantity=0,
                    reorder_level=5,
                    minimum_price=price,
                    maximum_price=price * Decimal("1.30"),
                    is_available=True,
                    available_online=True,
                    available_pos=True,
                    pricing_rule_id=rule.id,
                ))
            else:
                product.brand = brand
                product.category_id = category.id
                product.unit = unit
                product.search_keywords = f"{name.lower()} {brand.lower()} {category_name.lower()}"
                if refresh_catalog_assets or not product.image_url:
                    product.image_url = image_for(name, category_name, brand)

                sp = StoreProduct.query.filter_by(store_id=store.id, product_id=product.id).first()
                if not sp:
                    price = starter_price(category_name, index)
                    db.session.add(StoreProduct(
                        store_id=store.id, product_id=product.id,
                        cost_price=(price * Decimal("0.80")).quantize(Decimal("1")),
                        selling_price=price, stock_quantity=25, reorder_level=5,
                        is_available=True, available_online=True, available_pos=True,
                        pricing_rule_id=rule.id,
                    ))
                elif refresh_catalog_assets:
                    price = starter_price(category_name, index)
                    sp.selling_price = price
                    sp.cost_price = (price * Decimal("0.80")).quantize(Decimal("1"))
                    sp.minimum_price = price
                    sp.maximum_price = price * Decimal("1.30")

            if not ProductAlias.query.filter_by(product_id=product.id, alias=name).first():
                db.session.add(ProductAlias(product_id=product.id, alias=name, alias_type="SEARCH"))

    defaults = {
        "footer_text": "All rights reserved · Denmart Merchants",
        "shop_tagline": "Everyday groceries and household essentials, ready for delivery or pickup.",
    }
    for key, value in defaults.items():
        setting = SystemSetting.query.filter_by(business_id=business.id, key=key).first()
        if not setting:
            db.session.add(SystemSetting(business_id=business.id, key=key, value=value))

    db.session.commit()
    return first_catalog_boot


if __name__ == "__main__":
    from app import create_app
    app = create_app()
    with app.app_context():
        seed_defaults()
