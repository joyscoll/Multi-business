from datetime import datetime, timezone
import uuid
from decimal import Decimal
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db


def uid():
    return str(uuid.uuid4())


def now():
    return datetime.now(timezone.utc)


class Business(db.Model):
    __tablename__ = "businesses"
    id = db.Column(db.String(36), primary_key=True, default=uid)
    name = db.Column(db.String(160), nullable=False)
    legal_name = db.Column(db.String(200))
    phone = db.Column(db.String(40))
    email = db.Column(db.String(160))
    address = db.Column(db.Text)
    county = db.Column(db.String(100))
    town = db.Column(db.String(100))
    tax_identifier = db.Column(db.String(100))
    logo_url = db.Column(db.Text)
    currency = db.Column(db.String(8), default="KES")
    timezone = db.Column(db.String(64), default="Africa/Nairobi")
    status = db.Column(db.String(30), default="ACTIVE", nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=now, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=now, onupdate=now, nullable=False)
    stores = db.relationship("Store", back_populates="business", cascade="all, delete-orphan")


class Store(db.Model):
    __tablename__ = "stores"
    id = db.Column(db.String(36), primary_key=True, default=uid)
    business_id = db.Column(db.String(36), db.ForeignKey("businesses.id"), nullable=False, index=True)
    name = db.Column(db.String(160), nullable=False)
    code = db.Column(db.String(30), nullable=False)
    phone = db.Column(db.String(40))
    address = db.Column(db.Text)
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=now, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=now, onupdate=now, nullable=False)
    business = db.relationship("Business", back_populates="stores")
    products = db.relationship("StoreProduct", back_populates="store", cascade="all, delete-orphan")


class Role(db.Model):
    __tablename__ = "roles"
    id = db.Column(db.String(36), primary_key=True, default=uid)
    name = db.Column(db.String(50), unique=True, nullable=False)
    permissions = db.relationship("Permission", secondary="role_permissions", back_populates="roles")


class Permission(db.Model):
    __tablename__ = "permissions"
    id = db.Column(db.String(36), primary_key=True, default=uid)
    code = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.String(240))
    roles = db.relationship("Role", secondary="role_permissions", back_populates="permissions")


role_permissions = db.Table(
    "role_permissions",
    db.Column("role_id", db.String(36), db.ForeignKey("roles.id"), primary_key=True),
    db.Column("permission_id", db.String(36), db.ForeignKey("permissions.id"), primary_key=True),
)


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.String(36), primary_key=True, default=uid)
    business_id = db.Column(db.String(36), db.ForeignKey("businesses.id"), nullable=False, index=True)
    store_id = db.Column(db.String(36), db.ForeignKey("stores.id"), index=True)
    name = db.Column(db.String(160), nullable=False)
    email = db.Column(db.String(160), unique=True, index=True)
    phone = db.Column(db.String(40))
    username = db.Column(db.String(80), unique=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role_id = db.Column(db.String(36), db.ForeignKey("roles.id"), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    last_login_at = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(db.DateTime(timezone=True), default=now, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=now, onupdate=now, nullable=False)
    role = db.relationship("Role")
    store = db.relationship("Store")
    business = db.relationship("Business")

    def set_password(self, value):
        self.password_hash = generate_password_hash(value)

    def check_password(self, value):
        return check_password_hash(self.password_hash, value)

    def has_permission(self, code):
        return bool(self.role and (self.role.name == "OWNER" or any(p.code == code for p in self.role.permissions)))


class Category(db.Model):
    __tablename__ = "categories"
    id = db.Column(db.String(36), primary_key=True, default=uid)
    business_id = db.Column(db.String(36), db.ForeignKey("businesses.id"), nullable=False, index=True)
    parent_id = db.Column(db.String(36), db.ForeignKey("categories.id"), index=True)
    name = db.Column(db.String(120), nullable=False)
    slug = db.Column(db.String(140), nullable=False)
    description = db.Column(db.Text)
    image_url = db.Column(db.Text)
    sort_order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    parent = db.relationship("Category", remote_side=[id])


class Product(db.Model):
    __tablename__ = "products"
    id = db.Column(db.String(36), primary_key=True, default=uid)
    barcode = db.Column(db.String(80), index=True)
    sku = db.Column(db.String(80), index=True)
    name = db.Column(db.String(240), nullable=False)
    slug = db.Column(db.String(260), unique=True, index=True, nullable=False)
    brand = db.Column(db.String(160))
    description = db.Column(db.Text)
    category_id = db.Column(db.String(36), db.ForeignKey("categories.id"), index=True)
    subcategory_id = db.Column(db.String(36), db.ForeignKey("categories.id"), index=True)
    unit = db.Column(db.String(40), default="unit")
    pack_size = db.Column(db.String(80))
    weight = db.Column(db.Numeric(14, 4))
    volume = db.Column(db.Numeric(14, 4))
    manufacturer = db.Column(db.String(180))
    country_of_origin = db.Column(db.String(100))
    search_keywords = db.Column(db.Text)
    image_url = db.Column(db.Text)
    status = db.Column(db.String(30), default="ACTIVE", nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=now, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=now, onupdate=now, nullable=False)


class ProductImage(db.Model):
    __tablename__ = "product_images"
    id = db.Column(db.String(36), primary_key=True, default=uid)
    product_id = db.Column(db.String(36), db.ForeignKey("products.id"), nullable=False, index=True)
    image_url = db.Column(db.Text, nullable=False)
    thumbnail_url = db.Column(db.Text)
    alt_text = db.Column(db.String(240))
    source_type = db.Column(db.String(60))
    license_info = db.Column(db.Text)
    sort_order = db.Column(db.Integer, default=0)
    is_primary = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime(timezone=True), default=now, nullable=False)


class ProductAlias(db.Model):
    __tablename__ = "product_aliases"
    id = db.Column(db.String(36), primary_key=True, default=uid)
    product_id = db.Column(db.String(36), db.ForeignKey("products.id"), nullable=False, index=True)
    alias = db.Column(db.String(240), nullable=False, index=True)
    alias_type = db.Column(db.String(50), default="SEARCH")


class PricingRule(db.Model):
    __tablename__ = "pricing_rules"
    id = db.Column(db.String(36), primary_key=True, default=uid)
    business_id = db.Column(db.String(36), db.ForeignKey("businesses.id"), nullable=False, index=True)
    store_id = db.Column(db.String(36), db.ForeignKey("stores.id"), index=True)
    name = db.Column(db.String(160), nullable=False)
    rule_type = db.Column(db.String(50), nullable=False, default="COST_PLUS_PERCENT")
    margin_percent = db.Column(db.Numeric(9, 4))
    fixed_markup = db.Column(db.Numeric(14, 2))
    rounding_rule = db.Column(db.Numeric(14, 2), default=Decimal("1"))
    min_margin_percent = db.Column(db.Numeric(9, 4))
    max_discount_percent = db.Column(db.Numeric(9, 4))
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    priority = db.Column(db.Integer, default=100)
    starts_at = db.Column(db.DateTime(timezone=True))
    ends_at = db.Column(db.DateTime(timezone=True))


class StoreProduct(db.Model):
    __tablename__ = "store_products"
    id = db.Column(db.String(36), primary_key=True, default=uid)
    store_id = db.Column(db.String(36), db.ForeignKey("stores.id"), nullable=False, index=True)
    product_id = db.Column(db.String(36), db.ForeignKey("products.id"), nullable=False, index=True)
    cost_price = db.Column(db.Numeric(14, 2), default=0, nullable=False)
    selling_price = db.Column(db.Numeric(14, 2), default=0, nullable=False)
    minimum_price = db.Column(db.Numeric(14, 2), default=0)
    maximum_price = db.Column(db.Numeric(14, 2))
    stock_quantity = db.Column(db.Numeric(14, 3), default=0, nullable=False)
    reserved_quantity = db.Column(db.Numeric(14, 3), default=0, nullable=False)
    reorder_level = db.Column(db.Numeric(14, 3), default=0)
    is_available = db.Column(db.Boolean, default=True, nullable=False)
    available_online = db.Column(db.Boolean, default=True, nullable=False)
    available_pos = db.Column(db.Boolean, default=True, nullable=False)
    pricing_rule_id = db.Column(db.String(36), db.ForeignKey("pricing_rules.id"))
    created_at = db.Column(db.DateTime(timezone=True), default=now, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=now, onupdate=now, nullable=False)
    store = db.relationship("Store", back_populates="products")
    product = db.relationship("Product")
    pricing_rule = db.relationship("PricingRule")
    __table_args__ = (db.UniqueConstraint("store_id", "product_id", name="uq_store_product"),)


class PriceHistory(db.Model):
    __tablename__ = "price_history"
    id = db.Column(db.String(36), primary_key=True, default=uid)
    store_product_id = db.Column(db.String(36), db.ForeignKey("store_products.id"), nullable=False, index=True)
    old_price = db.Column(db.Numeric(14, 2), nullable=False)
    new_price = db.Column(db.Numeric(14, 2), nullable=False)
    reason = db.Column(db.String(240))
    source = db.Column(db.String(80), default="MANUAL")
    changed_by = db.Column(db.String(36), db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime(timezone=True), default=now, nullable=False)


class InventoryTransaction(db.Model):
    __tablename__ = "inventory_transactions"
    id = db.Column(db.String(36), primary_key=True, default=uid)
    store_id = db.Column(db.String(36), db.ForeignKey("stores.id"), nullable=False, index=True)
    product_id = db.Column(db.String(36), db.ForeignKey("products.id"), nullable=False, index=True)
    transaction_type = db.Column(db.String(50), nullable=False)
    quantity = db.Column(db.Numeric(14, 3), nullable=False)
    unit_cost = db.Column(db.Numeric(14, 2), default=0)
    reference_type = db.Column(db.String(60))
    reference_id = db.Column(db.String(36))
    notes = db.Column(db.Text)
    created_by = db.Column(db.String(36), db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime(timezone=True), default=now, nullable=False)


class Supplier(db.Model):
    __tablename__ = "suppliers"
    id = db.Column(db.String(36), primary_key=True, default=uid)
    business_id = db.Column(db.String(36), db.ForeignKey("businesses.id"), nullable=False, index=True)
    name = db.Column(db.String(180), nullable=False)
    phone = db.Column(db.String(40))
    email = db.Column(db.String(160))
    address = db.Column(db.Text)
    tax_identifier = db.Column(db.String(100))
    is_active = db.Column(db.Boolean, default=True, nullable=False)


class PurchaseOrder(db.Model):
    __tablename__ = "purchase_orders"
    id = db.Column(db.String(36), primary_key=True, default=uid)
    business_id = db.Column(db.String(36), db.ForeignKey("businesses.id"), nullable=False, index=True)
    store_id = db.Column(db.String(36), db.ForeignKey("stores.id"), nullable=False, index=True)
    supplier_id = db.Column(db.String(36), db.ForeignKey("suppliers.id"), nullable=False)
    reference_number = db.Column(db.String(80), unique=True, nullable=False)
    status = db.Column(db.String(40), default="DRAFT", nullable=False)
    subtotal = db.Column(db.Numeric(14, 2), default=0)
    tax = db.Column(db.Numeric(14, 2), default=0)
    total = db.Column(db.Numeric(14, 2), default=0)
    created_by = db.Column(db.String(36), db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime(timezone=True), default=now, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=now, onupdate=now, nullable=False)


class PurchaseOrderItem(db.Model):
    __tablename__ = "purchase_order_items"
    id = db.Column(db.String(36), primary_key=True, default=uid)
    purchase_order_id = db.Column(db.String(36), db.ForeignKey("purchase_orders.id"), nullable=False, index=True)
    product_id = db.Column(db.String(36), db.ForeignKey("products.id"), nullable=False)
    quantity = db.Column(db.Numeric(14, 3), nullable=False)
    unit_cost = db.Column(db.Numeric(14, 2), nullable=False)
    tax = db.Column(db.Numeric(14, 2), default=0)
    total = db.Column(db.Numeric(14, 2), default=0)


class Customer(db.Model):
    __tablename__ = "customers"
    id = db.Column(db.String(36), primary_key=True, default=uid)
    business_id = db.Column(db.String(36), db.ForeignKey("businesses.id"), nullable=False, index=True)
    name = db.Column(db.String(160), nullable=False)
    phone = db.Column(db.String(40), index=True)
    email = db.Column(db.String(160), index=True)
    password_hash = db.Column(db.String(255))
    address = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=now, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=now, onupdate=now, nullable=False)


class Order(db.Model):
    __tablename__ = "orders"
    id = db.Column(db.String(36), primary_key=True, default=uid)
    business_id = db.Column(db.String(36), db.ForeignKey("businesses.id"), nullable=False, index=True)
    store_id = db.Column(db.String(36), db.ForeignKey("stores.id"), nullable=False, index=True)
    order_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    customer_id = db.Column(db.String(36), db.ForeignKey("customers.id"), index=True)
    status = db.Column(db.String(40), default="PENDING", nullable=False)
    payment_status = db.Column(db.String(40), default="UNPAID", nullable=False)
    fulfillment_status = db.Column(db.String(40), default="PENDING", nullable=False)
    subtotal = db.Column(db.Numeric(14, 2), default=0)
    discount = db.Column(db.Numeric(14, 2), default=0)
    delivery_fee = db.Column(db.Numeric(14, 2), default=0)
    tax = db.Column(db.Numeric(14, 2), default=0)
    total = db.Column(db.Numeric(14, 2), default=0)
    delivery_address = db.Column(db.Text)
    delivery_notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=now, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=now, onupdate=now, nullable=False)


class OrderItem(db.Model):
    __tablename__ = "order_items"
    id = db.Column(db.String(36), primary_key=True, default=uid)
    order_id = db.Column(db.String(36), db.ForeignKey("orders.id"), nullable=False, index=True)
    product_id = db.Column(db.String(36), db.ForeignKey("products.id"), nullable=False)
    product_name_snapshot = db.Column(db.String(240), nullable=False)
    sku_snapshot = db.Column(db.String(80))
    unit_price = db.Column(db.Numeric(14, 2), nullable=False)
    quantity = db.Column(db.Numeric(14, 3), nullable=False)
    discount = db.Column(db.Numeric(14, 2), default=0)
    tax = db.Column(db.Numeric(14, 2), default=0)
    line_total = db.Column(db.Numeric(14, 2), nullable=False)


class Sale(db.Model):
    __tablename__ = "sales"
    id = db.Column(db.String(36), primary_key=True, default=uid)
    business_id = db.Column(db.String(36), db.ForeignKey("businesses.id"), nullable=False, index=True)
    store_id = db.Column(db.String(36), db.ForeignKey("stores.id"), nullable=False, index=True)
    cashier_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=False)
    receipt_number = db.Column(db.String(60), unique=True, nullable=False, index=True)
    subtotal = db.Column(db.Numeric(14, 2), default=0)
    discount = db.Column(db.Numeric(14, 2), default=0)
    tax = db.Column(db.Numeric(14, 2), default=0)
    total = db.Column(db.Numeric(14, 2), nullable=False)
    status = db.Column(db.String(40), default="COMPLETED", nullable=False)
    payment_status = db.Column(db.String(40), default="UNPAID", nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=now, nullable=False)
    completed_at = db.Column(db.DateTime(timezone=True))


class SaleItem(db.Model):
    __tablename__ = "sale_items"
    id = db.Column(db.String(36), primary_key=True, default=uid)
    sale_id = db.Column(db.String(36), db.ForeignKey("sales.id"), nullable=False, index=True)
    product_id = db.Column(db.String(36), db.ForeignKey("products.id"), nullable=False)
    product_name_snapshot = db.Column(db.String(240), nullable=False)
    barcode_snapshot = db.Column(db.String(80))
    unit_price = db.Column(db.Numeric(14, 2), nullable=False)
    quantity = db.Column(db.Numeric(14, 3), nullable=False)
    discount = db.Column(db.Numeric(14, 2), default=0)
    tax = db.Column(db.Numeric(14, 2), default=0)
    line_total = db.Column(db.Numeric(14, 2), nullable=False)


class Payment(db.Model):
    __tablename__ = "payments"
    id = db.Column(db.String(36), primary_key=True, default=uid)
    business_id = db.Column(db.String(36), db.ForeignKey("businesses.id"), nullable=False, index=True)
    store_id = db.Column(db.String(36), db.ForeignKey("stores.id"), nullable=False, index=True)
    sale_id = db.Column(db.String(36), db.ForeignKey("sales.id"), index=True)
    order_id = db.Column(db.String(36), db.ForeignKey("orders.id"), index=True)
    provider = db.Column(db.String(50), nullable=False)
    method = db.Column(db.String(30), nullable=False)
    amount = db.Column(db.Numeric(14, 2), nullable=False)
    currency = db.Column(db.String(8), default="KES")
    status = db.Column(db.String(30), default="PENDING", nullable=False)
    external_reference = db.Column(db.String(160), index=True)
    provider_transaction_id = db.Column(db.String(160), unique=True, index=True)
    merchant_request_id = db.Column(db.String(160), index=True)
    checkout_request_id = db.Column(db.String(160), unique=True, index=True)
    phone_number = db.Column(db.String(40))
    initiated_at = db.Column(db.DateTime(timezone=True), default=now)
    completed_at = db.Column(db.DateTime(timezone=True))
    failure_code = db.Column(db.String(80))
    failure_message = db.Column(db.String(500))
    raw_provider_reference = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=now, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=now, onupdate=now, nullable=False)


class PaymentIntegration(db.Model):
    __tablename__ = "payment_integrations"
    id = db.Column(db.String(36), primary_key=True, default=uid)
    business_id = db.Column(db.String(36), db.ForeignKey("businesses.id"), nullable=False, index=True)
    provider = db.Column(db.String(50), nullable=False)
    environment = db.Column(db.String(30), default="sandbox")
    consumer_key_encrypted = db.Column(db.Text)
    consumer_secret_encrypted = db.Column(db.Text)
    shortcode_encrypted = db.Column(db.Text)
    passkey_encrypted = db.Column(db.Text)
    other_credentials_encrypted = db.Column(db.Text)
    callback_url = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=False, nullable=False)
    last_tested_at = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(db.DateTime(timezone=True), default=now, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=now, onupdate=now, nullable=False)


class Delivery(db.Model):
    __tablename__ = "deliveries"
    id = db.Column(db.String(36), primary_key=True, default=uid)
    order_id = db.Column(db.String(36), db.ForeignKey("orders.id"), nullable=False, unique=True)
    driver_id = db.Column(db.String(36), db.ForeignKey("users.id"))
    status = db.Column(db.String(40), default="PENDING", nullable=False)
    pickup_at = db.Column(db.DateTime(timezone=True))
    dispatched_at = db.Column(db.DateTime(timezone=True))
    delivered_at = db.Column(db.DateTime(timezone=True))
    recipient_name = db.Column(db.String(160))
    recipient_phone = db.Column(db.String(40))
    notes = db.Column(db.Text)


class Shift(db.Model):
    __tablename__ = "shifts"
    id = db.Column(db.String(36), primary_key=True, default=uid)
    store_id = db.Column(db.String(36), db.ForeignKey("stores.id"), nullable=False, index=True)
    cashier_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=False, index=True)
    opened_at = db.Column(db.DateTime(timezone=True), default=now, nullable=False)
    opening_cash = db.Column(db.Numeric(14, 2), default=0)
    closed_at = db.Column(db.DateTime(timezone=True))
    closing_cash = db.Column(db.Numeric(14, 2))
    expected_cash = db.Column(db.Numeric(14, 2))
    difference = db.Column(db.Numeric(14, 2))
    status = db.Column(db.String(20), default="OPEN", nullable=False)


class CashDrawerTransaction(db.Model):
    __tablename__ = "cash_drawer_transactions"
    id = db.Column(db.String(36), primary_key=True, default=uid)
    shift_id = db.Column(db.String(36), db.ForeignKey("shifts.id"), nullable=False, index=True)
    transaction_type = db.Column(db.String(40), nullable=False)
    amount = db.Column(db.Numeric(14, 2), nullable=False)
    reference_type = db.Column(db.String(50))
    reference_id = db.Column(db.String(36))
    notes = db.Column(db.Text)
    created_by = db.Column(db.String(36), db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime(timezone=True), default=now, nullable=False)


class AuditLog(db.Model):
    __tablename__ = "audit_logs"
    id = db.Column(db.String(36), primary_key=True, default=uid)
    business_id = db.Column(db.String(36), db.ForeignKey("businesses.id"), nullable=False, index=True)
    user_id = db.Column(db.String(36), db.ForeignKey("users.id"))
    action = db.Column(db.String(100), nullable=False)
    entity_type = db.Column(db.String(80), nullable=False)
    entity_id = db.Column(db.String(36))
    old_values = db.Column(db.JSON)
    new_values = db.Column(db.JSON)
    ip_address = db.Column(db.String(80))
    user_agent = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=now, nullable=False)


class SystemError(db.Model):
    __tablename__ = "system_errors"
    id = db.Column(db.String(36), primary_key=True, default=uid)
    business_id = db.Column(db.String(36), db.ForeignKey("businesses.id"), index=True)
    level = db.Column(db.String(20), default="ERROR", nullable=False)
    code = db.Column(db.String(120), nullable=False)
    message = db.Column(db.String(1000), nullable=False)
    path = db.Column(db.String(500))
    method = db.Column(db.String(20))
    user_id = db.Column(db.String(36), db.ForeignKey("users.id"))
    ip_address = db.Column(db.String(80))
    user_agent = db.Column(db.Text)
    resolved = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=now, nullable=False, index=True)


class OfflineOperation(db.Model):
    __tablename__ = "offline_operations"
    id = db.Column(db.String(36), primary_key=True, default=uid)
    client_operation_id = db.Column(db.String(120), unique=True, nullable=False, index=True)
    device_id = db.Column(db.String(120), nullable=False)
    user_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=False)
    store_id = db.Column(db.String(36), db.ForeignKey("stores.id"), nullable=False)
    operation_type = db.Column(db.String(60), nullable=False)
    payload = db.Column(db.JSON, nullable=False)
    status = db.Column(db.String(30), default="RECEIVED", nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=now, nullable=False)
    processed_at = db.Column(db.DateTime(timezone=True))

class Expense(db.Model):
    __tablename__ = "expenses"
    id = db.Column(db.String(36), primary_key=True, default=uid)
    business_id = db.Column(db.String(36), db.ForeignKey("businesses.id"), nullable=False, index=True)
    store_id = db.Column(db.String(36), db.ForeignKey("stores.id"), index=True)
    category = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(240), nullable=False)
    amount = db.Column(db.Numeric(14, 2), nullable=False)
    incurred_at = db.Column(db.DateTime(timezone=True), default=now, nullable=False, index=True)
    created_by = db.Column(db.String(36), db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime(timezone=True), default=now, nullable=False)
