from decimal import Decimal
from flask import Blueprint, flash, redirect, render_template, request, url_for, Response
from flask_login import current_user, login_required
from extensions import db
from models import Product, StoreProduct, PricingRule, PriceHistory, InventoryTransaction, User, AuditLog, Sale, SaleItem, Order, Store, Business, Category, SystemError, OfflineOperation, Payment, Expense, Role
from services.pricing import suggested_price
from services.audit import audit
from services.export import export_business
import json
import re

bp = Blueprint("admin", __name__)


def admin_required(permission=None):
    def decorator(fn):
        from functools import wraps
        @wraps(fn)
        @login_required
        def wrapped(*args, **kwargs):
            if current_user.role and current_user.role.name == "OWNER":
                return fn(*args, **kwargs)
            if permission and not current_user.has_permission(permission):
                return "Forbidden", 403
            return fn(*args, **kwargs)
        return wrapped
    return decorator


def admin_home():
    sales_total = db.session.query(db.func.coalesce(db.func.sum(Sale.total), 0)).filter_by(business_id=current_user.business_id, payment_status="PAID").scalar() or 0
    today = db.func.date(Sale.created_at) == db.func.current_date()
    today_sales = db.session.query(db.func.coalesce(db.func.sum(Sale.total), 0)).filter(Sale.business_id == current_user.business_id, Sale.payment_status == "PAID", today).scalar() or 0
    expenses_total = db.session.query(db.func.coalesce(db.func.sum(Expense.amount), 0)).filter(Expense.business_id == current_user.business_id).scalar() or 0
    cost_total = (db.session.query(db.func.coalesce(db.func.sum(SaleItem.line_total - (StoreProduct.cost_price * SaleItem.quantity)), 0))
                  .join(Sale, Sale.id == SaleItem.sale_id)
                  .join(StoreProduct, (StoreProduct.product_id == SaleItem.product_id) & (StoreProduct.store_id == Sale.store_id))
                  .filter(Sale.business_id == current_user.business_id, Sale.payment_status == "PAID").scalar() or 0)
    gross_profit = Decimal(str(sales_total)) - Decimal(str(cost_total))
    net_result = gross_profit - Decimal(str(expenses_total))
    orders = Order.query.filter_by(business_id=current_user.business_id).count()
    low_stock = (StoreProduct.query.filter(StoreProduct.stock_quantity <= StoreProduct.reorder_level)
                 .join(Product).join(Store).filter(Store.business_id == current_user.business_id).count())
    products_online = (StoreProduct.query.join(Store).filter(Store.business_id == current_user.business_id, StoreProduct.is_available.is_(True), StoreProduct.available_online.is_(True)).count())
    stores = Store.query.filter_by(business_id=current_user.business_id).order_by(Store.name).all()
    recent = Sale.query.filter_by(business_id=current_user.business_id).order_by(Sale.created_at.desc()).limit(10).all()
    return render_template("admin/dashboard.html", sales_total=sales_total, today_sales=today_sales, expenses_total=expenses_total, cost_total=cost_total, gross_profit=gross_profit, net_result=net_result, orders=orders, low_stock=low_stock, products_online=products_online, stores=stores, recent=recent)


@bp.get("/fr%2")
@admin_required("reports.view")
def dashboard_obscured():
    return admin_home()


@bp.get("/fr%252")
@admin_required("reports.view")
def dashboard_obscured_encoded():
    return admin_home()



@bp.get("/admin/products")
@admin_required("products.view")
def products():
    items = (StoreProduct.query.join(Product).join(Store)
             .filter(Store.business_id == current_user.business_id)
             .order_by(Product.name).limit(1500).all())
    return render_template("admin/products.html", items=items, stores=Store.query.filter_by(business_id=current_user.business_id).order_by(Store.name).all())


@bp.post("/admin/products/<store_product_id>/availability")
@admin_required("products.edit")
def toggle_product_availability(store_product_id):
    item=db.session.get(StoreProduct, store_product_id)
    if not item or item.store.business_id != current_user.business_id:return "Not found",404
    item.available_online = request.form.get("online") == "1"
    item.available_pos = request.form.get("pos") == "1"
    item.is_available = request.form.get("enabled") == "1"
    db.session.commit()
    audit("PRODUCT_VISIBILITY_CHANGED","StoreProduct",item.id,new_values={"online":item.available_online,"pos":item.available_pos,"enabled":item.is_available})
    flash("Product availability updated.","success")
    return redirect(url_for("admin.products"))


@bp.post("/admin/products/create")
@admin_required("products.create")
def create_product():
    name=request.form.get("name","").strip(); image_url=request.form.get("image_url","").strip(); category_id=request.form.get("category_id") or None; store_id=request.form.get("store_id")
    try: cost=Decimal(request.form.get("cost_price","0")); price=Decimal(request.form.get("selling_price","0"))
    except Exception: cost=price=Decimal("0")
    store=db.session.get(Store,store_id)
    if not store or store.business_id!=current_user.business_id or not name or cost<0 or price<=0:
        flash("Product name, mart and a valid selling price are required.","error")
        return redirect(url_for("admin.products"))
    base=re.sub(r"[^a-z0-9]+","-",name.lower()).strip("-")
    slug=base
    i=2
    while Product.query.filter_by(slug=slug).first(): slug=f"{base}-{i}";i+=1
    product=Product(name=name,slug=slug,category_id=category_id,search_keywords=name.lower(),image_url=image_url or None,status="ACTIVE")
    db.session.add(product);db.session.flush()
    item=StoreProduct(store_id=store.id,product_id=product.id,cost_price=cost,selling_price=price,stock_quantity=0,reorder_level=1,is_available=True,available_online=True,available_pos=True)
    db.session.add(item);db.session.commit();audit("PRODUCT_CREATED","Product",product.id,new_values={"name":name,"store_id":store.id,"price":str(price)})
    flash("Product added to the catalogue.","success")
    return redirect(url_for("admin.products"))


@bp.post("/admin/products/<store_product_id>/price")
@admin_required("products.edit")
def update_price(store_product_id):
    item = db.session.get(StoreProduct, store_product_id)
    if not item or item.store.business_id != current_user.business_id:
        return "Not found", 404
    old = Decimal(item.selling_price or 0)
    new = Decimal(request.form.get("selling_price", "0"))
    if new <= 0:
        flash("Price must be greater than zero.", "error")
        return redirect(url_for("admin.products"))
    item.selling_price = new
    db.session.add(PriceHistory(store_product_id=item.id, old_price=old, new_price=new, reason=request.form.get("reason") or "Manual price update", source="MANUAL", changed_by=current_user.id))
    db.session.commit()
    audit("PRICE_CHANGED", "StoreProduct", item.id, old_values={"selling_price": str(old)}, new_values={"selling_price": str(new)})
    flash("Price updated.", "success")
    return redirect(url_for("admin.products"))


@bp.get("/admin/pricing")
@admin_required("products.view")
def pricing():
    rules = PricingRule.query.filter_by(business_id=current_user.business_id).order_by(PricingRule.priority).all()
    return render_template("admin/pricing.html", rules=rules)


@bp.post("/admin/products/<store_product_id>/auto-price")
@admin_required("products.edit")
def auto_price(store_product_id):
    item = db.session.get(StoreProduct, store_product_id)
    if not item or item.store.business_id != current_user.business_id:
        return "Not found", 404
    new = suggested_price(item, item.pricing_rule)
    old = Decimal(item.selling_price or 0)
    if new > 0 and new != old:
        item.selling_price = new
        db.session.add(PriceHistory(store_product_id=item.id, old_price=old, new_price=new, reason="Automatic pricing rule", source="PRICING_ENGINE", changed_by=current_user.id))
        db.session.commit()
        audit("PRICE_CHANGED", "StoreProduct", item.id, old_values={"selling_price": str(old)}, new_values={"selling_price": str(new), "source": "PRICING_ENGINE"})
    return redirect(url_for("admin.products"))


@bp.route("/admin/stores", methods=["GET", "POST"])
@admin_required("reports.view")
def stores():
    if request.method=="POST":
        name=request.form.get("name","").strip();code=request.form.get("code","").strip().upper();address=request.form.get("address","").strip();phone=request.form.get("phone","").strip()
        if not name or not code or Store.query.filter_by(business_id=current_user.business_id,code=code).first():
            flash("Mart name and a unique code are required.","error")
        else:
            store=Store(business_id=current_user.business_id,name=name,code=code,address=address or None,phone=phone or None,is_active=True);db.session.add(store);db.session.commit();audit("STORE_CREATED","Store",store.id,new_values={"name":name,"code":code});flash("Mart added.","success");return redirect(url_for("admin.stores"))
    return render_template("admin/stores.html", stores=Store.query.filter_by(business_id=current_user.business_id).order_by(Store.name).all())


@bp.route("/admin/users", methods=["GET", "POST"])
@admin_required("users.manage")
def users():
    stores=Store.query.filter_by(business_id=current_user.business_id).order_by(Store.name).all()
    roles=Role.query.filter(Role.name != "OWNER").order_by(Role.name).all()
    if request.method=="POST":
        username=request.form.get("username","").strip()
        name=request.form.get("name","").strip()
        password=request.form.get("password","")
        role_id=request.form.get("role_id")
        store_id=request.form.get("store_id") or None
        if not username or not name or len(password)<8 or not role_id:
            flash("Name, username, role and an 8+ character password are required.","error")
        elif User.query.filter_by(username=username).first():
            flash("That username is already in use.","error")
        else:
            role=db.session.get(Role,role_id)
            if not role or role.name=="OWNER": flash("That role cannot be assigned here.","error")
            else:
                user=User(business_id=current_user.business_id,store_id=store_id,name=name,username=username,role_id=role.id,is_active=True)
                user.set_password(password);db.session.add(user);db.session.commit()
                audit("USER_CREATED","User",user.id,new_values={"username":username,"role":role.name,"store_id":store_id})
                flash("User created.","success")
                return redirect(url_for("admin.users"))
    users=User.query.filter_by(business_id=current_user.business_id).order_by(User.name).all()
    return render_template("admin/users.html", users=users, stores=stores, roles=roles)


@bp.get("/admin/audit")
@admin_required("reports.view")
def audit_logs():
    logs = AuditLog.query.filter_by(business_id=current_user.business_id).order_by(AuditLog.created_at.desc()).limit(300).all()
    return render_template("admin/audit.html", logs=logs)


@bp.get("/admin/system-errors")
@admin_required("reports.view")
def system_errors():
    errors = SystemError.query.filter_by(business_id=current_user.business_id).order_by(SystemError.created_at.desc()).limit(300).all()
    return render_template("admin/system_errors.html", errors=errors)


@bp.get("/admin/security")
@admin_required("reports.view")
def security():
    users = User.query.filter_by(business_id=current_user.business_id).order_by(User.name).all()
    failedish = AuditLog.query.filter_by(business_id=current_user.business_id).order_by(AuditLog.created_at.desc()).limit(100).all()
    return render_template("admin/security.html", users=users, logs=failedish)


@bp.get("/admin/backups")
@admin_required("backup.create")
def backups():
    latest = AuditLog.query.filter_by(business_id=current_user.business_id).filter(AuditLog.action.in_(["BACKUP_EXPORTED","BACKUP_CREATED"])).order_by(AuditLog.created_at.desc()).limit(20).all()
    return render_template("admin/backups.html", latest=latest)


@bp.post("/admin/users/<user_id>/toggle")
@admin_required("users.manage")
def toggle_user(user_id):
    user = db.session.get(User, user_id)
    if not user or user.business_id != current_user.business_id:
        return "Not found", 404
    if user.id == current_user.id:
        flash("You cannot disable your own account.", "error")
        return redirect(url_for("admin.users"))
    user.is_active = not user.is_active
    db.session.commit()
    audit("USER_STATUS_CHANGED", "User", user.id, new_values={"is_active": user.is_active})
    flash("User status updated.", "success")
    return redirect(url_for("admin.users"))


@bp.route("/admin/expenses", methods=["GET", "POST"])
@admin_required("reports.view")
def expenses():
    stores=Store.query.filter_by(business_id=current_user.business_id).order_by(Store.name).all()
    if request.method=="POST":
        try: amount=Decimal(request.form.get("amount","0"))
        except Exception: amount=Decimal("0")
        category=request.form.get("category","General").strip() or "General"
        description=request.form.get("description","").strip()
        if amount<=0 or not description:
            flash("Expense amount and description are required.","error")
        else:
            e=Expense(business_id=current_user.business_id,store_id=request.form.get("store_id") or None,category=category,description=description,amount=amount,created_by=current_user.id)
            db.session.add(e);db.session.commit();audit("EXPENSE_RECORDED","Expense",e.id,new_values={"amount":str(amount),"category":category});flash("Expense recorded.","success");return redirect(url_for("admin.expenses"))
    rows=Expense.query.filter_by(business_id=current_user.business_id).order_by(Expense.incurred_at.desc()).limit(200).all()
    total=db.session.query(db.func.coalesce(db.func.sum(Expense.amount),0)).filter(Expense.business_id==current_user.business_id).scalar() or 0
    return render_template("admin/expenses.html",rows=rows,total=total,stores=stores)


@bp.get("/admin/export.json")
@admin_required("backup.create")
def export_json():
    payload = export_business(current_user.business_id)
    audit("BACKUP_EXPORTED", "Business", current_user.business_id, new_values={"format":"json"})
    return Response(json.dumps(payload, default=str), mimetype="application/json", headers={"Content-Disposition": "attachment; filename=real-mart-export.json"})
