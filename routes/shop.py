from io import BytesIO
from flask import Blueprint, render_template, request, session, send_file, jsonify, Response
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


def catalogue_query(store=None, q="", category=""):
    query = (StoreProduct.query.join(Product)
             .filter(StoreProduct.is_available.is_(True), StoreProduct.available_online.is_(True),
                     StoreProduct.stock_quantity > StoreProduct.reserved_quantity, Product.status == "ACTIVE"))
    if store:
        query = query.filter(StoreProduct.store_id == store.id)
    if category:
        query = query.filter(Product.category_id == category)
    if q:
        like = f"%{q}%"
        query = query.filter((Product.name.ilike(like)) | (Product.brand.ilike(like)) |
                             (Product.search_keywords.ilike(like)) | (Product.barcode.ilike(like)))
    return query.order_by(Product.name)


@bp.get("/")
def home():
    store = selected_store()
    categories = (Category.query.filter_by(business_id=store.business_id, is_active=True)
                  .order_by(Category.sort_order, Category.name).all()) if store else []
    rows = catalogue_query(store).limit(600).all() if store else []
    priority = [
        "sugar", "fresh milk", "yoghurt", "bread", "maize meal", "rice", "cooking oil",
        "eggs", "tea", "coffee", "water", "tissue", "toilet", "washing", "soap", "biscuits",
    ]
    def rank(item):
        text = f"{item.product.name} {item.product.brand or ''}".lower()
        for i, term in enumerate(priority):
            if term in text:
                return i
        return 99
    ranked = sorted(rows, key=lambda x: (rank(x), x.product.name.lower()))
    essentials = ranked[:24]
    more_products = [x for x in ranked[24:] if x not in essentials][:32]
    return render_template("shop/home.html", stores=active_stores(), store=store, essentials=essentials, more_products=more_products, categories=categories)


@bp.get("/shop")
def shop():
    q = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    store = selected_store()
    products = catalogue_query(store, q=q, category=category).limit(300).all()
    categories = (Category.query.filter_by(business_id=store.business_id, is_active=True)
                  .order_by(Category.sort_order, Category.name).all()) if store else []
    return render_template("shop/shop.html", products=products, q=q, store=store, stores=active_stores(), categories=categories)


@bp.get("/product/<slug>")
def product(slug):
    store = selected_store()
    item = (StoreProduct.query.join(Product)
            .filter(Product.slug == slug, StoreProduct.is_available.is_(True), StoreProduct.available_online.is_(True), Product.status == "ACTIVE")
            .filter(StoreProduct.store_id == store.id if store else True).first_or_404())
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
    # The QR represents the site origin, never a hard-coded Render/custom domain.
    img = qrcode.make(request.url_root.rstrip("/"))
    buf = BytesIO(); img.save(buf, format="PNG"); buf.seek(0)
    return send_file(buf, mimetype="image/png", max_age=3600)


@bp.get("/shop/manifest.webmanifest")
def shop_manifest():
    base = request.host_url.rstrip("/")
    return jsonify({
        "name": "REAL MART",
        "short_name": "REAL MART",
        "start_url": f"{base}/",
        "scope": f"{base}/",
        "display": "standalone",
        "background_color": "#f7fafb",
        "theme_color": "#193849",
        "description": "REAL MART online supermarket",
        "icons": [{"src": f"{base}/static/pwa/icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any maskable"}],
    })


@bp.get("/shop/sw.js")
def shop_service_worker():
    js = """const CACHE='real-mart-public-v8';\nself.addEventListener('install',e=>e.waitUntil(self.skipWaiting()));\nself.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));\nself.addEventListener('fetch',e=>{const u=new URL(e.request.url);if(u.origin!==location.origin||e.request.method!=='GET')return;e.respondWith(fetch(e.request).catch(()=>caches.match(e.request).then(r=>r||new Response('REAL MART is temporarily offline',{status:503}))));});\n"""
    return Response(js, mimetype="application/javascript", headers={"Service-Worker-Allowed": "/"})


