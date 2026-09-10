from flask import Flask, render_template, request, redirect, url_for, jsonify, flash, send_file, abort
from pathlib import Path
from datetime import datetime
import sqlite3, json, os, re, time, traceback, io, zipfile, uuid
import qrcode

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / 'data' / 'multibusiness.db'
JSON_PATH = BASE_DIR / 'data' / 'business.json'
BACKUP_DIR = BASE_DIR / 'backups'
ERROR_LOG = BASE_DIR / 'data' / 'system_errors.jsonl'

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'multibusiness-v1-serious-secret')
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 86400

# These are separate worlds. A selected engine never exposes another engine's content/workflows.
BUSINESS_TYPES = [
    ('vehicles', 'Vehicles', 'Cars, SUVs, trucks, vans, buses and motorcycles.'),
    ('hotels', 'Hotels & Lodges', 'Rooms, suites, reservations, stays and guest services.'),
    ('restaurants', 'Restaurants, Bars & Cafés', 'Menus, tables, orders, reservations and catering.'),
    ('marine', 'Boats, Marine & Yachts', 'Yachts, boats, charters and marine sales.'),
    ('property', 'Real Estate & Property', 'Homes, land, commercial property and rentals.'),
    ('electronics', 'Electronics & Appliances', 'Phones, computers, TVs, appliances and devices.'),
    ('furniture', 'Furniture & Home', 'Furniture collections, custom work and delivery.'),
    ('equipment', 'Equipment & Machinery', 'Construction, agricultural and industrial equipment.'),
    ('events', 'Events & Services', 'Venues, services, bookings and professional providers.'),
    ('marketplace', 'Retail & General Marketplace', 'Products, retail offers and general commerce.'),
]
BUSINESS_LABELS = {k: v for k, v, _ in BUSINESS_TYPES}

# Complete engines in this v1. Other choices are isolated shells that point out to a dedicated future site.
COMPLETE_ENGINES = {'vehicles', 'hotels', 'restaurants', 'property', 'marketplace'}
ENGINE_DATA = {
    'vehicles': {
        'hero': 'Find the right vehicle. Then act on it.',
        'sub': 'Every vehicle has its own digital profile, buying path, viewing flow and physical QR identity.',
        'categories': ['Cars', 'SUVs', 'Trucks', 'Vans', 'Buses', 'Motorcycles', 'Commercial'],
        'actions': [('PURCHASE', 'Buy this vehicle'), ('FINANCE', 'Request finance'), ('VIEWING', 'Book a viewing'), ('OFFER', 'Make an offer')],
        'item_label': 'vehicle',
        'cta': 'Sell a vehicle',
    },
    'hotels': {
        'hero': 'Choose your stay. Reserve the room.',
        'sub': 'Real room inventory, room numbers, stay dates and service requests are managed from one hotel operation.',
        'categories': ['Rooms', 'Suites', 'Family', 'Long Stay', 'Conference'],
        'actions': [('BOOKING', 'Book room'), ('SERVICE', 'Request service'), ('INQUIRY', 'Ask the hotel')],
        'item_label': 'room',
        'cta': 'Partner with the hotel',
    },
    'restaurants': {
        'hero': 'See what is being served. Then order or reserve.',
        'sub': 'Menus, tables, orders, reservations and catering requests stay inside this restaurant operation.',
        'categories': ['Breakfast', 'Lunch', 'Dinner', 'Drinks', 'Café', 'Catering'],
        'actions': [('ORDER', 'Order'), ('RESERVATION', 'Reserve a table'), ('CATERING', 'Request catering')],
        'item_label': 'menu item',
        'cta': 'Partner with the restaurant',
    },
    'property': {
        'hero': 'A property profile you can actually act on.',
        'sub': 'View properties, request viewings, send offers and submit rental interest without leaving this business.',
        'categories': ['For Sale', 'For Rent', 'Land', 'Residential', 'Commercial', 'Development'],
        'actions': [('VIEWING', 'Book viewing'), ('OFFER', 'Make an offer'), ('RENTAL', 'Request rental')],
        'item_label': 'property',
        'cta': 'List a property',
    },
    'marketplace': {
        'hero': 'A proper local place to buy and sell.',
        'sub': 'Products have profiles, customer actions, enquiries and seller intake — not just photos.',
        'categories': ['New Arrivals', 'Deals', 'Home', 'Business', 'Lifestyle'],
        'actions': [('PURCHASE', 'Buy / reserve'), ('INQUIRY', 'Ask seller')],
        'item_label': 'product',
        'cta': 'Sell a product',
    },
}

FALLBACK_ENGINE_LINKS = {
    'marine': '/sites/marine', 'electronics': '/sites/electronics', 'furniture': '/sites/furniture',
    'equipment': '/sites/equipment', 'events': '/sites/events'
}

DEMO = {
    'phone': '+254 700 123 456', 'whatsapp': '+254 711 456 789', 'email': 'hello@multibusiness.demo',
    'location': 'Westlands, Nairobi, Kenya', 'website': 'https://example.com'
}


def now():
    return datetime.utcnow().isoformat(timespec='seconds') + 'Z'


def slugify(value):
    return re.sub(r'[^a-z0-9]+', '-', (value or '').lower()).strip('-') or 'business'


def db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA busy_timeout=20000')
    try:
        conn.execute('PRAGMA journal_mode=WAL')
    except sqlite3.DatabaseError:
        pass
    conn.execute('PRAGMA synchronous=NORMAL')
    return conn


def write_tx(conn, callback, retries=5):
    last = None
    for attempt in range(retries):
        try:
            conn.execute('BEGIN IMMEDIATE')
            result = callback(conn)
            conn.commit()
            return result
        except sqlite3.OperationalError as exc:
            last = exc
            try: conn.rollback()
            except Exception: pass
            if 'locked' not in str(exc).lower() or attempt == retries - 1:
                raise
            time.sleep(0.25 * (attempt + 1))
    raise last


def ensure_columns(conn, table, columns):
    existing = {row['name'] for row in conn.execute(f'PRAGMA table_info({table})').fetchall()}
    for name, sqltype in columns.items():
        if name not in existing:
            conn.execute(f'ALTER TABLE {table} ADD COLUMN {name} {sqltype}')


def activity(conn, action, detail=''):
    conn.execute('INSERT INTO activity(action,detail,created_at) VALUES (?,?,?)', (action, detail, now()))


def log_error(exc):
    record = {
        'time': now(), 'path': request.path if request else None,
        'method': request.method if request else None, 'type': type(exc).__name__,
        'message': str(exc), 'traceback': traceback.format_exc()
    }
    try:
        ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
        with ERROR_LOG.open('a', encoding='utf-8') as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + '\n')
    except Exception:
        pass
    return record


def system_errors():
    if not ERROR_LOG.exists(): return []
    rows = []
    for line in ERROR_LOG.read_text(encoding='utf-8').splitlines()[-150:]:
        try: rows.append(json.loads(line))
        except Exception: pass
    return list(reversed(rows))


def init_db():
    conn = db()
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS business (
        id INTEGER PRIMARY KEY CHECK(id=1), name TEXT NOT NULL, slug TEXT, business_type TEXT NOT NULL,
        location TEXT, phone TEXT, whatsapp TEXT, email TEXT, website TEXT, socials TEXT, description TEXT,
        logo TEXT, cover_image TEXT, contact_person TEXT, status TEXT DEFAULT 'ACTIVE',
        till_number TEXT, paybill_number TEXT, bank_name TEXT, bank_account TEXT, payment_note TEXT,
        created_at TEXT, updated_at TEXT
    );
    CREATE TABLE IF NOT EXISTS staff (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, role TEXT, phone TEXT, email TEXT, status TEXT DEFAULT 'ACTIVE', created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS items (
        id INTEGER PRIMARY KEY AUTOINCREMENT, business_type TEXT NOT NULL, category TEXT, title TEXT NOT NULL,
        price TEXT, location TEXT, status TEXT DEFAULT 'AVAILABLE', condition TEXT, featured INTEGER DEFAULT 0,
        image TEXT, gallery TEXT, specs_json TEXT, description TEXT, seller_name TEXT, seller_phone TEXT, seller_whatsapp TEXT,
        created_at TEXT, updated_at TEXT
    );
    CREATE TABLE IF NOT EXISTS rooms (
        id INTEGER PRIMARY KEY AUTOINCREMENT, room_number TEXT UNIQUE, room_type TEXT, floor TEXT, price TEXT,
        status TEXT DEFAULT 'AVAILABLE', amenities TEXT, image TEXT, description TEXT, created_at TEXT, updated_at TEXT
    );
    CREATE TABLE IF NOT EXISTS operations (
        id INTEGER PRIMARY KEY AUTOINCREMENT, business_type TEXT NOT NULL, item_id INTEGER, room_id INTEGER, table_id INTEGER, operation_type TEXT NOT NULL,
        customer_name TEXT, phone TEXT, email TEXT, date_from TEXT, date_to TEXT, quantity INTEGER DEFAULT 1,
        notes TEXT, payment_method TEXT, payment_reference TEXT, amount TEXT, status TEXT DEFAULT 'PENDING', created_at TEXT, updated_at TEXT
    );
    CREATE TABLE IF NOT EXISTS seller_submissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, business_type TEXT NOT NULL, name TEXT, phone TEXT, whatsapp TEXT, email TEXT,
        title TEXT, payload_json TEXT, status TEXT DEFAULT 'PENDING', created_at TEXT, updated_at TEXT
    );
    CREATE TABLE IF NOT EXISTS enquiries (
        id INTEGER PRIMARY KEY AUTOINCREMENT, business_type TEXT NOT NULL, item_id INTEGER, name TEXT, phone TEXT,
        email TEXT, message TEXT, kind TEXT DEFAULT 'ENQUIRY', status TEXT DEFAULT 'NEW', created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS ratings (
        id INTEGER PRIMARY KEY AUTOINCREMENT, business_type TEXT NOT NULL, item_id INTEGER, name TEXT, rating INTEGER,
        comment TEXT, status TEXT DEFAULT 'VISIBLE', created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS qr_codes (
        id INTEGER PRIMARY KEY AUTOINCREMENT, business_type TEXT NOT NULL, code TEXT UNIQUE, item_id INTEGER,
        scan_count INTEGER DEFAULT 0, created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS activity (
        id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT, detail TEXT, created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS menu_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, category TEXT, price TEXT, description TEXT, image TEXT, status TEXT DEFAULT 'AVAILABLE', created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS restaurant_tables (
        id INTEGER PRIMARY KEY AUTOINCREMENT, table_number TEXT UNIQUE, seats INTEGER, status TEXT DEFAULT 'AVAILABLE', created_at TEXT
    );
    ''')
    ensure_columns(conn, 'business', {'slug':'TEXT','status':'TEXT','till_number':'TEXT','paybill_number':'TEXT','bank_name':'TEXT','bank_account':'TEXT','payment_note':'TEXT'})
    ensure_columns(conn, 'operations', {'room_id':'INTEGER','table_id':'INTEGER'})
    row = conn.execute('SELECT * FROM business WHERE id=1').fetchone()
    if not row:
        ts = now()
        conn.execute('''INSERT INTO business(id,name,slug,business_type,location,phone,whatsapp,email,website,socials,description,logo,cover_image,contact_person,status,created_at,updated_at)
                        VALUES (1,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                     ('Mavuno House', 'mavuno-house', 'vehicles', DEMO['location'], DEMO['phone'], DEMO['whatsapp'], DEMO['email'], DEMO['website'], '@mavunohouse',
                      'A commercial demonstration business. Replace this profile from /start.', 'M',
                      'https://images.unsplash.com/photo-1504215680853-026ed2a45def?auto=format&fit=crop&w=1800&q=88', 'Demo Contact', 'ACTIVE', ts, ts))
    seed_demo(conn, 'vehicles')
    conn.close()


def seed_demo(conn, only_type=None):
    count = conn.execute('SELECT COUNT(*) c FROM items').fetchone()['c']
    if count:
        return
    samples = [
        ('vehicles','SUVs','2023 Toyota Land Cruiser VX','KES 12,800,000','Nairobi','SECOND HAND','AVAILABLE','https://images.unsplash.com/photo-1492144534655-ae79c964c9d7?auto=format&fit=crop&w=1400&q=86',{'Year':'2023','Mileage':'38,500 km','Fuel':'Diesel','Transmission':'Automatic','Drive':'4WD','Engine':'3.3L','Colour':'Pearl White','Service history':'Available'},'Well maintained, locally available SUV with documented service history.'),
        ('vehicles','Cars','2022 Mercedes-Benz C200','KES 7,450,000','Nairobi','SECOND HAND','AVAILABLE','https://images.unsplash.com/photo-1555215695-3004980ad54e?auto=format&fit=crop&w=1400&q=86',{'Year':'2022','Mileage':'24,800 km','Fuel':'Petrol','Transmission':'Automatic','Engine':'1.5L Turbo','Colour':'Obsidian Black','Service history':'Available'},'Executive sedan prepared for immediate viewing.'),
        ('vehicles','Trucks','2019 Scania P410','KES 9,900,000','Mombasa','USED','AVAILABLE','https://images.unsplash.com/photo-1586191582151-f73872dfd0e5?auto=format&fit=crop&w=1400&q=86',{'Year':'2019','Mileage':'412,000 km','Fuel':'Diesel','Transmission':'Manual','Drive':'6x4','Payload':'25T'},'Heavy commercial truck ready for inspection.'),
        ('hotels','Rooms','Deluxe Garden Room','KES 18,500 / night','Nairobi','READY','AVAILABLE','https://images.unsplash.com/photo-1566665797739-1674de7a421a?auto=format&fit=crop&w=1400&q=86',{'Bed':'King','Guests':'2','Breakfast':'Included','WiFi':'Included'},'Quiet room facing the garden. Choose the actual room number during booking.'),
        ('hotels','Suites','Executive Suite','KES 32,000 / night','Nairobi','READY','AVAILABLE','https://images.unsplash.com/photo-1590490360182-c33d57733427?auto=format&fit=crop&w=1400&q=86',{'Bed':'King','Guests':'3','Lounge':'Private','Breakfast':'Included'},'Spacious suite with separate lounge.'),
        ('restaurants','Dinner','Grilled Beef Fillet','KES 1,950','Nairobi','FRESH','AVAILABLE','https://images.unsplash.com/photo-1544025162-d76694265947?auto=format&fit=crop&w=1400&q=86',{'Serving':'300g','Side':'Potatoes & vegetables'},'Char-grilled fillet with house sauce.'),
        ('restaurants','Café','Signature Cappuccino','KES 420','Nairobi','FRESH','AVAILABLE','https://images.unsplash.com/photo-1509042239860-f550ce710b93?auto=format&fit=crop&w=1400&q=86',{'Size':'Large','Milk':'Dairy / Oat'},'Freshly prepared barista coffee.'),
        ('property','For Sale','4 Bedroom Family Residence','KES 24,500,000','Karen, Nairobi','NEW','AVAILABLE','https://images.unsplash.com/photo-1600585154340-be6161a56a0c?auto=format&fit=crop&w=1400&q=86',{'Bedrooms':'4','Bathrooms':'4','Parking':'2','Tenure':'Freehold'},'Modern family home with garden and secure parking.'),
        ('property','For Rent','Westlands Two-Bedroom Apartment','KES 110,000 / month','Westlands, Nairobi','READY','AVAILABLE','https://images.unsplash.com/photo-1600607687920-4e2a09cf159d?auto=format&fit=crop&w=1400&q=86',{'Bedrooms':'2','Bathrooms':'2','Parking':'1','Lift':'Yes'},'Modern serviced apartment near business and retail districts.'),
        ('marketplace','Lifestyle','Leather Weekender Bag','KES 8,900','Nairobi','NEW','AVAILABLE','https://images.unsplash.com/photo-1553062407-98eeb64c6a62?auto=format&fit=crop&w=1400&q=86',{'Material':'Full grain leather','Capacity':'35L','Warranty':'1 year'},'Hand-finished travel bag built for daily and weekend use.'),
        ('marketplace','Home','Nordic Lounge Chair','KES 24,000','Nairobi','NEW','AVAILABLE','https://images.unsplash.com/photo-1555041469-a586c61ea9bc?auto=format&fit=crop&w=1400&q=86',{'Material':'Fabric','Colour':'Sand','Warranty':'2 years'},'Comfortable statement chair for modern interiors.'),
    ]
    for typ,cat,title,price,loc,cond,status,image,specs,desc in samples:
        if only_type and typ != only_type:
            continue
        conn.execute('INSERT INTO items(business_type,category,title,price,location,status,condition,featured,image,gallery,specs_json,description,seller_name,seller_phone,seller_whatsapp,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                     (typ,cat,title,price,loc,status,cond,1,image,json.dumps([image]),json.dumps(specs),desc,'Demo Sales Desk',DEMO['phone'],DEMO['whatsapp'],now(),now()))
    if only_type in (None, 'hotels'):
        for num,typ,price in [('101','Deluxe', '18500'),('102','Deluxe','18500'),('201','Executive','32000'),('202','Executive','32000')]:
            conn.execute('INSERT OR IGNORE INTO rooms(room_number,room_type,floor,price,status,amenities,description,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)',
                     (num, typ, num[0], price, 'AVAILABLE', 'WiFi, Breakfast, TV, Safe', 'Demo room inventory.', now(), now()))
    if only_type in (None, 'restaurants'):
        for n,seats in [('T1',2),('T2',4),('T3',6),('T4',8)]:
            conn.execute('INSERT OR IGNORE INTO restaurant_tables(table_number,seats,status,created_at) VALUES (?,?,?,?)',(n,seats,'AVAILABLE',now()))
    if conn.execute('SELECT COUNT(*) c FROM staff').fetchone()['c']==0:
        for name,role in [('Business Director','Owner / Director'),('Customer Care','Customer Care'),('Operations Lead','Operations'),('Sales Desk','Sales')]:
            conn.execute('INSERT INTO staff(name,role,phone,email,status,created_at) VALUES (?,?,?,?,?,?)',(name,role,DEMO['phone'],DEMO['email'],'ACTIVE',now()))


def business():
    conn=db(); row=conn.execute('SELECT * FROM business WHERE id=1').fetchone(); conn.close(); return dict(row)


def active_type():
    return business()['business_type']


def require_engine(typ=None):
    current=active_type()
    if typ and current != typ:
        abort(404)
    if current not in COMPLETE_ENGINES:
        abort(404)
    return current


def current_public_items(typ, limit=None):
    conn=db(); sql='SELECT * FROM items WHERE business_type=? AND status <> ? ORDER BY featured DESC, id DESC'; args=[typ,'ARCHIVED']
    if limit: sql += ' LIMIT ?'; args.append(limit)
    rows=[dict(r) for r in conn.execute(sql,args).fetchall()]; conn.close(); return rows


def item_or_404(item_id, typ):
    conn=db(); row=conn.execute('SELECT * FROM items WHERE id=? AND business_type=?',(item_id,typ)).fetchone(); conn.close()
    if not row: abort(404)
    return dict(row)


def specs(row):
    try: return json.loads(row.get('specs_json') or '{}')
    except Exception: return {}


def public_context(typ):
    biz=business(); engine=ENGINE_DATA[typ]
    return {'business':biz,'typ':typ,'label':BUSINESS_LABELS[typ],'engine':engine,'categories':engine['categories']}


def export_json():
    conn=db()
    payload={'business':[dict(conn.execute('SELECT * FROM business WHERE id=1').fetchone())],
             'staff':[dict(x) for x in conn.execute('SELECT * FROM staff').fetchall()],
             'items':[dict(x) for x in conn.execute('SELECT * FROM items').fetchall()],
             'rooms':[dict(x) for x in conn.execute('SELECT * FROM rooms').fetchall()],
             'operations':[dict(x) for x in conn.execute('SELECT * FROM operations').fetchall()],
             'seller_submissions':[dict(x) for x in conn.execute('SELECT * FROM seller_submissions').fetchall()],
             'enquiries':[dict(x) for x in conn.execute('SELECT * FROM enquiries').fetchall()],
             'ratings':[dict(x) for x in conn.execute('SELECT * FROM ratings').fetchall()],
             'qr_codes':[dict(x) for x in conn.execute('SELECT * FROM qr_codes').fetchall()],
             'activity':[dict(x) for x in conn.execute('SELECT * FROM activity ORDER BY id DESC LIMIT 500').fetchall()],
             'menu_items':[dict(x) for x in conn.execute('SELECT * FROM menu_items').fetchall()],
             'restaurant_tables':[dict(x) for x in conn.execute('SELECT * FROM restaurant_tables').fetchall()]}
    conn.close(); JSON_PATH.parent.mkdir(parents=True,exist_ok=True); JSON_PATH.write_text(json.dumps(payload,indent=2,ensure_ascii=False),encoding='utf-8'); return JSON_PATH


def backup_zip():
    BACKUP_DIR.mkdir(parents=True,exist_ok=True); export_json(); stamp=datetime.utcnow().strftime('%Y%m%d_%H%M%S'); out=BACKUP_DIR/f'multibusiness_{stamp}.zip'
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        z.write(JSON_PATH,arcname='business.json')
        if DB_PATH.exists(): z.write(DB_PATH,arcname='multibusiness.db')
    return out


@app.template_filter('fromjson')
def fromjson_filter(value):
    try: return json.loads(value or '[]')
    except Exception: return []

@app.context_processor
def inject():
    return {'business': business(), 'business_labels': BUSINESS_LABELS, 'complete_engines': COMPLETE_ENGINES}


@app.route('/')
def home():
    if business().get('status') != 'ACTIVE': return redirect(url_for('start'))
    typ=active_type()
    return render_template('site_home.html', **public_context(typ), items=current_public_items(typ,6)) if typ in COMPLETE_ENGINES else render_template('external_engine.html', **public_context(typ), external=FALLBACK_ENGINE_LINKS.get(typ,'/start'))


@app.route('/start', methods=['GET','POST'])
def start():
    if business().get('status') == 'ACTIVE':
        flash('This business is already registered. Use Authority → Settings → Reset business to create a different business world.','error')
        return redirect(url_for('authority'))
    if request.method=='POST':
        typ=request.form.get('business_type')
        if typ not in BUSINESS_LABELS:
            flash('Choose a business type to continue.','error'); return redirect(url_for('start'))
        # Do not let an operator silently morph a running business. This is a reset/new-instance step.
        conn=db()
        write_tx(conn, lambda c: c.execute('UPDATE business SET business_type=?, status=?, updated_at=? WHERE id=1',(typ,'SETUP',now())))
        conn.close()
        return redirect(url_for('start_details'))
    return render_template('start.html', business=business(), business_types=BUSINESS_TYPES)


@app.route('/start/details', methods=['GET','POST'])
def start_details():
    biz=business()
    if request.method=='POST':
        f=request.form; typ=biz['business_type']
        if typ not in BUSINESS_LABELS: return redirect(url_for('start'))
        values=(f.get('name','').strip() or 'My Business',slugify(f.get('name','') or 'my-business'),typ,f.get('location','').strip(),f.get('phone','').strip(),f.get('whatsapp','').strip(),f.get('email','').strip(),f.get('website','').strip(),f.get('socials','').strip(),f.get('description','').strip(),f.get('logo','M').strip() or 'M',f.get('cover_image','').strip() or 'https://images.unsplash.com/photo-1497366754035-f200968a6e72?auto=format&fit=crop&w=1800&q=88',f.get('contact_person','').strip(),f.get('till_number','').strip(),f.get('paybill_number','').strip(),f.get('bank_name','').strip(),f.get('bank_account','').strip(),f.get('payment_note','').strip(),now())
        try:
            conn=db()
            def tx(c):
                c.execute('''UPDATE business SET name=?,slug=?,business_type=?,location=?,phone=?,whatsapp=?,email=?,website=?,socials=?,description=?,logo=?,cover_image=?,contact_person=?,status='ACTIVE',till_number=?,paybill_number=?,bank_name=?,bank_account=?,payment_note=?,updated_at=? WHERE id=1''',values)
                activity(c,'Business registered',values[0]);
            write_tx(conn,tx)
            seed_demo(conn, typ)
            conn.commit()
            export_json(); conn.close(); return redirect(url_for('home'))
        except Exception as exc:
            log_error(exc); flash('Business setup could not be saved. Check Authority → System Errors.','error');
            try: conn.close()
            except Exception: pass
    return render_template('start_details.html', business=biz, business_types=BUSINESS_TYPES, typ=biz['business_type'])


@app.route('/authority')
def authority():
    typ=active_type(); biz=business(); conn=db()
    metrics={
        'items':conn.execute('SELECT COUNT(*) c FROM items WHERE business_type=? AND status <> ?',(typ,'ARCHIVED')).fetchone()['c'],
        'orders':conn.execute('SELECT COUNT(*) c FROM operations WHERE business_type=? AND operation_type IN ("PURCHASE","ORDER","BOOKING","RESERVATION","RENTAL","OFFER")',(typ,)).fetchone()['c'],
        'pending':conn.execute('SELECT COUNT(*) c FROM operations WHERE business_type=? AND status="PENDING"',(typ,)).fetchone()['c'],
        'enquiries':conn.execute('SELECT COUNT(*) c FROM enquiries WHERE business_type=?',(typ,)).fetchone()['c'],
        'ratings':conn.execute('SELECT COUNT(*) c FROM ratings WHERE business_type=?',(typ,)).fetchone()['c'],
        'qr':conn.execute('SELECT COUNT(*) c FROM qr_codes WHERE business_type=?',(typ,)).fetchone()['c'],
        'staff':conn.execute('SELECT COUNT(*) c FROM staff').fetchone()['c'],
    }
    activities=[dict(x) for x in conn.execute('SELECT * FROM activity ORDER BY id DESC LIMIT 12').fetchall()]
    conn.close(); return render_template('authority.html',typ=typ,label=BUSINESS_LABELS[typ],metrics=metrics,activities=activities,engine=ENGINE_DATA.get(typ),complete=typ in COMPLETE_ENGINES)


@app.route('/authority/items')
def authority_items():
    typ=active_type(); require_engine(typ); conn=db(); rows=[dict(x) for x in conn.execute('SELECT * FROM items WHERE business_type=? ORDER BY id DESC',(typ,)).fetchall()]; conn.close(); return render_template('authority_items.html',typ=typ,label=BUSINESS_LABELS[typ],items=rows,engine=ENGINE_DATA[typ])


@app.route('/authority/item/new', methods=['GET','POST'])
def authority_item_new():
    typ=require_engine();
    if request.method=='POST':
        f=request.form; specs_obj={k[5:]:v for k,v in f.items() if k.startswith('spec_') and v.strip()}
        conn=db()
        def tx(c):
            c.execute('INSERT INTO items(business_type,category,title,price,location,status,condition,featured,image,gallery,specs_json,description,seller_name,seller_phone,seller_whatsapp,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                      (typ,f.get('category'),f.get('title','Untitled'),f.get('price'),f.get('location',business()['location']),'AVAILABLE',f.get('condition','NEW'),1 if f.get('featured') else 0,f.get('image') or business()['cover_image'],json.dumps([f.get('image')] if f.get('image') else []),json.dumps(specs_obj),f.get('description',''),f.get('seller_name','Business'),f.get('seller_phone',business()['phone']),f.get('seller_whatsapp',business()['whatsapp']),now(),now()))
            activity(c,'Item added',f.get('title','Untitled'))
        try: write_tx(conn,tx); export_json(); flash('Live item added.','success')
        except Exception as exc: log_error(exc); flash('Could not add item.','error')
        finally: conn.close()
        return redirect(url_for('authority_items'))
    return render_template('authority_item_form.html',typ=typ,label=BUSINESS_LABELS[typ],engine=ENGINE_DATA[typ],item=None)


@app.route('/authority/item/<int:item_id>/edit', methods=['GET','POST'])
def authority_item_edit(item_id):
    typ=require_engine(); item=item_or_404(item_id,typ)
    if request.method=='POST':
        f=request.form; specs_obj={k[5:]:v for k,v in f.items() if k.startswith('spec_') and v.strip()}
        conn=db()
        def tx(c):
            c.execute('UPDATE items SET category=?,title=?,price=?,location=?,status=?,condition=?,featured=?,image=?,gallery=?,specs_json=?,description=?,seller_name=?,seller_phone=?,seller_whatsapp=?,updated_at=? WHERE id=? AND business_type=?',
                      (f.get('category'),f.get('title'),f.get('price'),f.get('location'),f.get('status'),f.get('condition'),1 if f.get('featured') else 0,f.get('image'),json.dumps([f.get('image')] if f.get('image') else []),json.dumps(specs_obj),f.get('description'),f.get('seller_name'),f.get('seller_phone'),f.get('seller_whatsapp'),now(),item_id,typ)); activity(c,'Item edited',f.get('title',''))
        try: write_tx(conn,tx); export_json(); flash('Item updated.','success')
        except Exception as exc: log_error(exc); flash('Could not update item.','error')
        finally: conn.close()
        return redirect(url_for('authority_items'))
    return render_template('authority_item_form.html',typ=typ,label=BUSINESS_LABELS[typ],engine=ENGINE_DATA[typ],item=item)


@app.route('/authority/operations')
def authority_operations():
    typ=active_type(); require_engine(typ); conn=db(); ops=[dict(x) for x in conn.execute('SELECT o.*, i.title item_title FROM operations o LEFT JOIN items i ON i.id=o.item_id WHERE o.business_type=? ORDER BY o.id DESC',(typ,)).fetchall()]; conn.close(); return render_template('authority_operations.html',typ=typ,label=BUSINESS_LABELS[typ],operations=ops,engine=ENGINE_DATA[typ])


@app.route('/authority/operations/<int:op_id>/<action>', methods=['POST'])
def authority_operation_action(op_id,action):
    typ=active_type(); require_engine(typ); status={'approve':'APPROVED','confirm':'CONFIRMED','complete':'COMPLETED','cancel':'CANCELLED','reject':'REJECTED'}.get(action)
    if not status: abort(404)
    conn=db()
    try:
        write_tx(conn,lambda c:(c.execute('UPDATE operations SET status=?,updated_at=? WHERE id=? AND business_type=?',(status,now(),op_id,typ)), activity(c,'Operation '+status.lower(),str(op_id))))
        export_json(); flash(f'Operation #{op_id} marked {status.lower()}.','success')
    except Exception as exc: log_error(exc); flash('Operation update failed.','error')
    finally: conn.close()
    return redirect(url_for('authority_operations'))


@app.route('/authority/rooms', methods=['GET','POST'])
def authority_rooms():
    require_engine('hotels')
    conn=db()
    if request.method=='POST':
        f=request.form
        try:
            write_tx(conn,lambda c:(c.execute('INSERT OR REPLACE INTO rooms(room_number,room_type,floor,price,status,amenities,description,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)',(f.get('room_number'),f.get('room_type'),f.get('floor'),f.get('price'),f.get('status','AVAILABLE'),f.get('amenities'),f.get('description',''),now(),now())),activity(c,'Room updated',f.get('room_number'))))
            export_json(); flash('Room inventory saved.','success')
        except Exception as exc: log_error(exc); flash('Room update failed.','error')
    rooms=[dict(x) for x in conn.execute('SELECT * FROM rooms ORDER BY room_number').fetchall()]; conn.close(); return render_template('authority_rooms.html',rooms=rooms)


@app.route('/authority/tables', methods=['GET','POST'])
def authority_tables():
    require_engine('restaurants'); conn=db()
    if request.method=='POST':
        f=request.form
        try: write_tx(conn,lambda c:(c.execute('INSERT OR REPLACE INTO restaurant_tables(table_number,seats,status,created_at) VALUES (?,?,?,?)',(f.get('table_number'),int(f.get('seats') or 2),f.get('status','AVAILABLE'),now())),activity(c,'Restaurant table updated',f.get('table_number','')))); export_json(); flash('Restaurant table saved.','success')
        except Exception as exc: log_error(exc); flash('Table update failed.','error')
    tables=[dict(x) for x in conn.execute('SELECT * FROM restaurant_tables ORDER BY table_number').fetchall()]; conn.close(); return render_template('authority_tables.html',tables=tables)

@app.route('/authority/team', methods=['GET','POST'])
def authority_team():
    conn=db()
    if request.method=='POST':
        f=request.form
        try: write_tx(conn,lambda c:(c.execute('INSERT INTO staff(name,role,phone,email,status,created_at) VALUES (?,?,?,?,?,?)',(f.get('name'),f.get('role'),f.get('phone'),f.get('email'), 'ACTIVE',now())),activity(c,'Team member added',f.get('name')))); export_json(); flash('Team member added.','success')
        except Exception as exc: log_error(exc); flash('Could not add team member.','error')
    staff=[dict(x) for x in conn.execute('SELECT * FROM staff ORDER BY id').fetchall()]; conn.close(); return render_template('authority_team.html',staff=staff)


@app.route('/authority/qr')
def authority_qr():
    typ=active_type(); require_engine(typ); conn=db(); rows=[dict(x) for x in conn.execute('SELECT q.*,i.title FROM qr_codes q LEFT JOIN items i ON i.id=q.item_id WHERE q.business_type=? ORDER BY q.id DESC',(typ,)).fetchall()]; items=[dict(x) for x in conn.execute('SELECT id,title FROM items WHERE business_type=? ORDER BY id DESC',(typ,)).fetchall()]; conn.close(); return render_template('authority_qr.html',rows=rows,items=items,label=BUSINESS_LABELS[typ])


@app.route('/authority/qr/create', methods=['POST'])
def authority_qr_create():
    typ=require_engine(); item_id=request.form.get('item_id'); item=item_or_404(int(item_id),typ); code=slugify(item['title'])[:35]+'-'+uuid.uuid4().hex[:7]
    conn=db()
    try: write_tx(conn,lambda c:(c.execute('INSERT INTO qr_codes(business_type,code,item_id,created_at) VALUES (?,?,?,?)',(typ,code,item['id'],now())),activity(c,'QR assigned',item['title']))); export_json(); flash('QR assigned to the item.','success')
    except Exception as exc: log_error(exc); flash('Could not assign QR.','error')
    finally: conn.close()
    return redirect(url_for('authority_qr'))


@app.route('/qr/<code>.png')
def qr_png(code):
    conn=db(); row=conn.execute('SELECT * FROM qr_codes WHERE code=?',(code,)).fetchone(); conn.close()
    if not row: abort(404)
    img=qrcode.make(request.url_root.rstrip('/') + url_for('qr_open',code=code)); out=io.BytesIO(); img.save(out,format='PNG'); out.seek(0); return send_file(out,mimetype='image/png')


@app.route('/qr/<code>')
def qr_open(code):
    conn=db(); row=conn.execute('SELECT * FROM qr_codes WHERE code=?',(code,)).fetchone()
    if not row: conn.close(); abort(404)
    conn.execute('UPDATE qr_codes SET scan_count=scan_count+1 WHERE code=?',(code,)); conn.commit(); item_id=row['item_id']; typ=row['business_type']; conn.close()
    if typ != active_type(): abort(404)
    return redirect(url_for('item_detail',item_id=item_id))


@app.route('/scan')
def scan(): return render_template('scan.html')


@app.route('/browse')
def browse():
    typ=require_engine(); q=(request.args.get('q') or '').strip(); category=request.args.get('category','')
    conn=db(); sql='SELECT * FROM items WHERE business_type=? AND status<>?'; args=[typ,'ARCHIVED']
    if q: sql+=' AND (title LIKE ? OR category LIKE ? OR description LIKE ?)'; like=f'%{q}%'; args += [like,like,like]
    if category: sql+=' AND category=?'; args.append(category)
    sql+=' ORDER BY featured DESC,id DESC'; items=[dict(x) for x in conn.execute(sql,args).fetchall()]; conn.close()
    return render_template('browse.html',**public_context(typ),items=items,q=q,category=category)


@app.route('/item/<int:item_id>')
def item_detail(item_id):
    typ=require_engine(); item=item_or_404(item_id,typ); item['specs']=specs(item); conn=db(); ratings=[dict(x) for x in conn.execute('SELECT * FROM ratings WHERE business_type=? AND item_id=? AND status="VISIBLE" ORDER BY id DESC',(typ,item_id)).fetchall()]; qr=conn.execute('SELECT * FROM qr_codes WHERE business_type=? AND item_id=? ORDER BY id DESC LIMIT 1',(typ,item_id)).fetchone(); conn.close(); return render_template('item_detail.html',**public_context(typ),item=item,ratings=ratings,qr=dict(qr) if qr else None)


@app.route('/act/<int:item_id>', methods=['GET','POST'])
def act(item_id):
    typ=require_engine(); item=item_or_404(item_id,typ); action=request.args.get('action') or request.form.get('action') or (ENGINE_DATA[typ]['actions'][0][0])
    allowed={k for k,_ in ENGINE_DATA[typ]['actions']}
    if action not in allowed: abort(404)
    if request.method=='POST':
        f=request.form; conn=db()
        try:
            amount=f.get('amount') or item['price'] or ''
            def tx(c):
                room_id = None
                table_id = None
                if typ == 'hotels' and action == 'BOOKING':
                    raw_room = f.get('room_id') or ''
                    room_id = int(raw_room) if raw_room.isdigit() else None
                    if not room_id: raise ValueError('Choose an available room')
                if typ == 'restaurants' and action == 'RESERVATION':
                    raw_table = f.get('table_id') or ''
                    table_id = int(raw_table) if raw_table.isdigit() else None
                    if not table_id: raise ValueError('Choose an available table')
                c.execute('INSERT INTO operations(business_type,item_id,room_id,table_id,operation_type,customer_name,phone,email,date_from,date_to,quantity,notes,payment_method,payment_reference,amount,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                          (typ,item_id,room_id,table_id,action,f.get('name'),f.get('phone'),f.get('email'),f.get('date_from'),f.get('date_to'),int(f.get('quantity') or 1),f.get('notes'),f.get('payment_method'),f.get('payment_reference'),amount,'PENDING',now(),now()))
                if room_id:
                    changed = c.execute('UPDATE rooms SET status="RESERVED", updated_at=? WHERE id=? AND status="AVAILABLE"',(now(),room_id)).rowcount
                    if not changed: raise ValueError('That room is no longer available')
                if table_id:
                    changed = c.execute('UPDATE restaurant_tables SET status="RESERVED" WHERE id=? AND status="AVAILABLE"',(table_id,)).rowcount
                    if not changed: raise ValueError('That table is no longer available')
                activity(c,'Customer '+action.lower(),item['title'])
            write_tx(conn,tx); export_json(); op_id=conn.execute('SELECT MAX(id) id FROM operations').fetchone()['id']
        except Exception as exc: log_error(exc); flash('Your request could not be recorded.','error'); conn.close(); return redirect(url_for('item_detail',item_id=item_id))
        conn.close(); return render_template('operation_received.html',**public_context(typ),item=item,action=action,op_id=op_id,payment=business())
    rooms=[]
    if typ=='hotels' and action=='BOOKING':
        conn2=db(); rooms=[dict(r) for r in conn2.execute('SELECT * FROM rooms WHERE status=\"AVAILABLE\" ORDER BY room_number').fetchall()]; conn2.close()
    return render_template('action_form.html',**public_context(typ),item=item,action=action,rooms=rooms)


@app.route('/sell', methods=['GET','POST'])
def sell():
    typ=require_engine()
    if request.method=='POST':
        f=request.form; conn=db()
        try:
            payload={k:v for k,v in f.items() if k not in {'name','phone','whatsapp','email','title'}}
            write_tx(conn,lambda c:(c.execute('INSERT INTO seller_submissions(business_type,name,phone,whatsapp,email,title,payload_json,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)',(typ,f.get('name'),f.get('phone'),f.get('whatsapp'),f.get('email'),f.get('title'),json.dumps(payload),'PENDING',now(),now())),activity(c,'Seller submission received',f.get('title','')))); export_json()
        except Exception as exc: log_error(exc); flash('Submission could not be received.','error'); conn.close(); return redirect(url_for('sell'))
        conn.close(); return render_template('submission_received.html',**public_context(typ))
    return render_template('sell.html',**public_context(typ))


@app.route('/contact', methods=['GET','POST'])
def contact():
    typ=require_engine()
    if request.method=='POST':
        f=request.form; conn=db()
        try:
            write_tx(conn,lambda c:(c.execute('INSERT INTO enquiries(business_type,item_id,name,phone,email,message,kind,created_at) VALUES (?,?,?,?,?,?,?,?)',(typ,None,f.get('name'),f.get('phone'),f.get('email'),f.get('message'),'CONTACT',now())),activity(c,'Contact enquiry received',f.get('name','')))); export_json(); flash('Message received by the business team.','success')
        except Exception as exc: log_error(exc); flash('Could not send the message.','error')
        finally: conn.close()
    return render_template('contact.html',**public_context(typ))


@app.route('/rate', methods=['POST'])
def rate():
    typ=active_type(); require_engine(typ); f=request.form; rating=max(1,min(5,int(f.get('rating') or 5))); conn=db()
    try: write_tx(conn,lambda c:c.execute('INSERT INTO ratings(business_type,item_id,name,rating,comment,created_at) VALUES (?,?,?,?,?,?)',(typ,f.get('item_id') or None,f.get('name'),rating,f.get('comment'),now()))); export_json(); flash('Thank you for the rating.','success')
    except Exception as exc: log_error(exc); flash('Rating could not be saved.','error')
    finally: conn.close()
    return redirect(request.referrer or url_for('home'))


@app.route('/authority/sellers')
def authority_sellers():
    typ=active_type(); require_engine(typ); conn=db(); rows=[dict(x) for x in conn.execute('SELECT * FROM seller_submissions WHERE business_type=? ORDER BY id DESC',(typ,)).fetchall()]; conn.close(); return render_template('authority_sellers.html',rows=rows,typ=typ,label=BUSINESS_LABELS[typ])


@app.route('/authority/seller/<int:sid>/<action>',methods=['POST'])
def authority_seller_action(sid,action):
    typ=active_type(); require_engine(typ); conn=db()
    try:
        row=conn.execute('SELECT * FROM seller_submissions WHERE id=? AND business_type=?',(sid,typ)).fetchone()
        if not row: abort(404)
        if action=='approve':
            payload=json.loads(row['payload_json'] or '{}');
            def tx(c):
                c.execute('UPDATE seller_submissions SET status="APPROVED",updated_at=? WHERE id=?',(now(),sid))
                c.execute('INSERT INTO items(business_type,category,title,price,location,status,condition,featured,image,gallery,specs_json,description,seller_name,seller_phone,seller_whatsapp,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                          (typ,payload.get('category','General'),row['title'] or 'Seller submission',payload.get('price','Contact seller'),payload.get('location',business()['location']),'AVAILABLE',payload.get('condition','PRE-OWNED'),0,payload.get('image') or business()['cover_image'],json.dumps([]),json.dumps(payload),payload.get('description','Seller submission approved.'),row['name'],row['phone'],row['whatsapp'],now(),now())); activity(c,'Seller listing approved',row['title'] or '')
        elif action=='reject':
            def tx(c): c.execute('UPDATE seller_submissions SET status="REJECTED",updated_at=? WHERE id=?',(now(),sid)); activity(c,'Seller listing rejected',row['title'] or '')
        else: abort(404)
        write_tx(conn,tx); export_json(); flash('Seller record updated.','success')
    except Exception as exc: log_error(exc); flash('Seller action failed.','error')
    finally: conn.close()
    return redirect(url_for('authority_sellers'))


@app.route('/authority/backup')
def authority_backup(): return render_template('authority_backup.html')
@app.route('/authority/backup/create',methods=['POST'])
def authority_backup_create():
    try: return send_file(backup_zip(),as_attachment=True,download_name='multibusiness_backup.zip')
    except Exception as exc: log_error(exc); flash('Backup could not be created.','error'); return redirect(url_for('authority_backup'))

@app.route('/authority/export')
def authority_export():
    try: export_json(); return send_file(JSON_PATH,as_attachment=True,download_name='business_data.json',mimetype='application/json')
    except Exception as exc: log_error(exc); flash('Export failed.','error'); return redirect(url_for('authority_backup'))

@app.route('/authority/restore',methods=['POST'])
def authority_restore():
    upload=request.files.get('backup');
    if not upload or not upload.filename: flash('Choose a JSON backup file.','error'); return redirect(url_for('authority_backup'))
    conn=db()
    try:
        payload=json.loads(upload.read().decode('utf-8')); b=(payload.get('business') or [{}])[0]
        if not b: raise ValueError('Backup contains no business profile')
        def tx(c):
            c.execute('DELETE FROM business WHERE id=1');
            keys=['id','name','slug','business_type','location','phone','whatsapp','email','website','socials','description','logo','cover_image','contact_person','status','till_number','paybill_number','bank_name','bank_account','payment_note','created_at','updated_at']
            vals=[b.get(k) for k in keys];
            c.execute('INSERT INTO business('+','.join(keys)+') VALUES ('+','.join('?'*len(keys))+')',vals)
            for table, keys2 in {'staff':['id','name','role','phone','email','status','created_at'],'items':['id','business_type','category','title','price','location','status','condition','featured','image','gallery','specs_json','description','seller_name','seller_phone','seller_whatsapp','created_at','updated_at'],'rooms':['id','room_number','room_type','floor','price','status','amenities','image','description','created_at','updated_at'],'operations':['id','business_type','item_id','room_id','table_id','operation_type','customer_name','phone','email','date_from','date_to','quantity','notes','payment_method','payment_reference','amount','status','created_at','updated_at'],'seller_submissions':['id','business_type','name','phone','whatsapp','email','title','payload_json','status','created_at','updated_at'],'enquiries':['id','business_type','item_id','name','phone','email','message','kind','status','created_at'],'ratings':['id','business_type','item_id','name','rating','comment','status','created_at'],'qr_codes':['id','business_type','code','item_id','scan_count','created_at'],'activity':['id','action','detail','created_at'],'menu_items':['id','title','category','price','description','image','status','created_at'],'restaurant_tables':['id','table_number','seats','status','created_at']}.items():
                if table not in payload: continue
                c.execute(f'DELETE FROM {table}')
                for row in payload[table]: c.execute(f'INSERT INTO {table}('+','.join(keys2)+') VALUES ('+','.join('?'*len(keys2))+')',[row.get(k) for k in keys2])
            activity(c,'Business restored','Full business data restore')
        write_tx(conn,tx); export_json(); flash('Business restored.','success')
    except Exception as exc: log_error(exc); flash('Restore failed. Authority → System Errors contains the technical record.','error')
    finally: conn.close()
    return redirect(url_for('authority_backup'))


@app.route('/authority/errors')
def authority_errors(): return render_template('authority_errors.html',errors=system_errors())

@app.route('/authority/care')
def authority_care():
    typ=active_type(); require_engine(typ); conn=db()
    enquiries=[dict(x) for x in conn.execute('SELECT e.*,i.title item_title FROM enquiries e LEFT JOIN items i ON i.id=e.item_id WHERE e.business_type=? ORDER BY e.id DESC',(typ,)).fetchall()]
    ratings=[dict(x) for x in conn.execute('SELECT * FROM ratings WHERE business_type=? ORDER BY id DESC',(typ,)).fetchall()]
    conn.close(); return render_template('authority_care.html',enquiries=enquiries,ratings=ratings,label=BUSINESS_LABELS[typ])

@app.route('/authority/settings',methods=['GET','POST'])
def authority_settings():
    biz=business()
    if request.method=='POST':
        f=request.form
        if f.get('action')=='reset':
            conn=db()
            try:
                def reset_tx(c):
                    for table in ('qr_codes','ratings','enquiries','seller_submissions','operations','rooms','items','staff','menu_items','restaurant_tables','activity'):
                        c.execute(f'DELETE FROM {table}')
                    c.execute("UPDATE business SET status='SETUP',name='New Business',slug='new-business',business_type='vehicles',location='',phone='',whatsapp='',email='',website='',socials='',description='',logo='M',cover_image='',contact_person='',till_number='',paybill_number='',bank_name='',bank_account='',payment_note='',updated_at=? WHERE id=1",(now(),))
                    activity(c,'Business reset','All previous business records cleared; ready for fresh /start setup')
                write_tx(conn,reset_tx); flash('Business reset. Start again from /start.','success')
            except Exception as exc: log_error(exc); flash('Reset failed.','error')
            finally: conn.close()
            return redirect(url_for('start'))
        flds=(f.get('name'),slugify(f.get('name') or 'business'),f.get('location'),f.get('phone'),f.get('whatsapp'),f.get('email'),f.get('website'),f.get('socials'),f.get('description'),f.get('logo'),f.get('cover_image'),f.get('contact_person'),f.get('till_number'),f.get('paybill_number'),f.get('bank_name'),f.get('bank_account'),f.get('payment_note'),now())
        conn=db()
        try: write_tx(conn,lambda c:(c.execute('UPDATE business SET name=?,slug=?,location=?,phone=?,whatsapp=?,email=?,website=?,socials=?,description=?,logo=?,cover_image=?,contact_person=?,till_number=?,paybill_number=?,bank_name=?,bank_account=?,payment_note=?,updated_at=? WHERE id=1',flds),activity(c,'Business settings updated',f.get('name','')))); export_json(); flash('Business settings saved.','success')
        except Exception as exc: log_error(exc); flash('Settings could not be saved.','error')
        finally: conn.close()
        return redirect(url_for('authority_settings'))
    return render_template('authority_settings.html',biz=biz,typ=active_type())


@app.route('/sites/<name>')
def external_engine(name):
    return render_template('external_engine.html',**public_context(active_type()), external=FALLBACK_ENGINE_LINKS.get(name,'#'))


@app.route('/health')
def health(): return jsonify(status='ok', version='4.0-independent-engines', business_type=active_type())
@app.route('/favicon.ico')
def favicon(): return ('',204)

@app.errorhandler(404)
def e404(exc):
    return render_template('error.html',code=404,message='This page does not belong to the selected business.') ,404

@app.errorhandler(500)
def e500(exc):
    log_error(exc); return render_template('error.html',code=500,message='Something went wrong inside this business. The technical record is available under Authority → System Errors.'),500

init_db()
if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.environ.get('PORT',5000)),debug=False)
