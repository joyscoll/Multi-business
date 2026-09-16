from decimal import Decimal
from io import BytesIO
from flask import Blueprint, render_template, request, session, redirect, url_for, jsonify, send_file
from extensions import db
from models import Product, Store, StoreProduct, Category

bp = Blueprint("shop", __name__)


def active_stores():
    return Store.query.filter_by(is_active=True).order_by(Store.name).all()


def selected_store():
    stores = active_stores()
    requested = request.args.get("store", "").strip()
    store = next((s for s in stores if s.code.lower() == requested.lower() or s.id == requested), None)
    if store:
        session["store_code"] = store.code
        return store
    saved = session.get("store_code")
    if saved:
        store = next((s for s in stores if s.code.lower() == str(saved).lower()), None)
        if store:
            return store
    return stores[0] if stores else None


@bp.get("/")
def home():
    stores = active_stores()
    featured_store = selected_store()
    products = []
    categories = []
    if featured_store:
        products = (StoreProduct.query.join(Product)
                    .filter(StoreProduct.store_id == featured_store.id,
                            StoreProduct.is_available.is_(True),
                            StoreProduct.available_online.is_(True))
                    .order_by(Product.name).limit(12).all())
        categories = (Category.query.filter_by(business_id=featured_store.business_id, is_active=True)
                      .order_by(Category.sort_order, Category.name).limit(12).all())
    return render_template("shop/home.html", stores=stores, featured_store=featured_store, products=products, categories=categories)


@bp.get("/shop")
def shop():
    q = request.args.get("q", "").strip()
    store = selected_store()
    category = request.args.get("category", "").strip()
    query = StoreProduct.query.join(Product).filter(StoreProduct.is_available.is_(True), StoreProduct.available_online.is_(True))
    if store:
        query = query.filter(StoreProduct.store_id == store.id)
    if category:
        query = query.filter(Product.category_id == category)
    if q:
        like = f"%{q}%"
        query = query.filter((Product.name.ilike(like)) | (Product.brand.ilike(like)) | (Product.search_keywords.ilike(like)) | (Product.barcode.ilike(like)))
    products = query.order_by(Product.name).limit(150).all()
    categories = []
    if store:
        categories = Category.query.filter_by(business_id=store.business_id, is_active=True).order_by(Category.sort_order, Category.name).all()
    return render_template("shop/shop.html", products=products, q=q, store=store, stores=active_stores(), categories=categories)


@bp.get("/product/<slug>")
def product(slug):
    store = selected_store()
    query = StoreProduct.query.join(Product).filter(Product.slug == slug, StoreProduct.is_available.is_(True), StoreProduct.available_online.is_(True))
    if store:
        query = query.filter(StoreProduct.store_id == store.id)
    item = query.first_or_404()
    return render_template("shop/product.html", item=item, store=store)


@bp.get("/cart")
def cart():
    return render_template("shop/cart.html", store=selected_store())


@bp.get("/checkout")
def checkout():
    return render_template("shop/checkout.html", store=selected_store())


@bp.get("/order/<order_number>")
def order_confirmation(order_number):
    from models import Order, OrderItem
    order = Order.query.filter_by(order_number=order_number).first_or_404()
    items = OrderItem.query.filter_by(order_id=order.id).all()
    return render_template("shop/order_confirmation.html", order=order, items=items, store=Store.query.get(order.store_id))


@bp.get("/app-qr.png")
def app_qr():
    import qrcode
    img = qrcode.make(request.host_url.rstrip("/") + "/supermarket")
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png", max_age=3600)


@bp.get("/supermarket")
def supermarket():
    stores = active_stores()
    return render_template("shop/supermarket.html", stores=stores, selected=selected_store())


@bp.get("/supermarket/<code>")
def supermarket_store(code):
    store = Store.query.filter_by(code=code, is_active=True).first_or_404()
    session["store_code"] = store.code
    return redirect(url_for("shop.supermarket", store=store.code))


@bp.get("/supermarket/manifest/<code>.webmanifest")
def mart_manifest(code):
    store = Store.query.filter_by(code=code, is_active=True).first_or_404()
    base = request.host_url.rstrip("/")
    return jsonify({
        "name": f"{store.name} • {store.business.name if store.business else 'Mart'}",
        "short_name": store.name,
        "start_url": f"{base}/shop?store={store.code}",
        "scope": base + "/",
        "display": "standalone",
        "background_color": "#f6fbff",
        "theme_color": "#55b8dc",
        "description": f"Shop online from {store.name}.",
        "icons": [{"src": f"{base}/static/pwa/icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any maskable"}]
    })
