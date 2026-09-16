from decimal import Decimal
from flask import Blueprint, render_template, request
from extensions import db
from models import Product, Store, StoreProduct

bp = Blueprint("shop", __name__)

@bp.get("/")
def home():
    return render_template("shop/home.html")

@bp.get("/shop")
def shop():
    q = request.args.get("q", "").strip()
    store = Store.query.filter_by(is_active=True).order_by(Store.created_at).first()
    query = StoreProduct.query.join(Product).filter(StoreProduct.is_available.is_(True), StoreProduct.available_online.is_(True))
    if store:
        query = query.filter(StoreProduct.store_id == store.id)
    if q:
        like = f"%{q}%"
        query = query.filter((Product.name.ilike(like)) | (Product.brand.ilike(like)) | (Product.search_keywords.ilike(like)) | (Product.barcode.ilike(like)))
    products = query.order_by(Product.name).limit(100).all()
    return render_template("shop/shop.html", products=products, q=q)

@bp.get("/product/<slug>")
def product(slug):
    item = StoreProduct.query.join(Product).filter(Product.slug == slug, StoreProduct.is_available.is_(True), StoreProduct.available_online.is_(True)).first_or_404()
    return render_template("shop/product.html", item=item)

@bp.get("/cart")
def cart():
    return render_template("shop/cart.html")

@bp.get("/checkout")
def checkout():
    return render_template("shop/checkout.html")
