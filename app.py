from flask import Flask, render_template, request, redirect, url_for, jsonify, flash, send_file, abort
from pathlib import Path
from datetime import datetime
import json, sqlite3, shutil, os, zipfile, io, re
import qrcode

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / 'data' / 'multibusiness.db'
JSON_PATH = BASE_DIR / 'data' / 'business.json'
BACKUP_DIR = BASE_DIR / 'backups'

app = Flask(__name__)
app.secret_key = 'multibusiness-v1-demo-secret'
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 86400

BUSINESS_TYPES = [
    ('vehicles', 'Vehicles & Transport', 'Vehicles, fleet, trucks, motorcycles and commercial units'),
    ('hotels', 'Hotels & Lodges', 'Rooms, suites, stays, facilities and reservations'),
    ('restaurants', 'Restaurants, Bars & Cafés', 'Menus, dining, drinks, ambience and enquiries'),
    ('marine', 'Boats, Marine & Yachts', 'Boats, yachts, marine equipment and charter listings'),
    ('property', 'Real Estate & Property', 'Homes, land, rentals, commercial and development'),
    ('electronics', 'Electronics & Appliances', 'Phones, computers, appliances and technology'),
    ('furniture', 'Furniture & Home', 'Furniture, interiors and home collections'),
    ('equipment', 'Equipment & Machinery', 'Construction, agricultural and industrial equipment'),
    ('events', 'Events & Services', 'Event spaces, creative services and professional services'),
    ('marketplace', 'Retail & General Marketplace', 'A broad storefront for products and local commerce'),
]

SECTIONS = {
    'vehicles': ['Cars','SUVs','Trucks','Vans','Buses','Motorcycles','Commercial vehicles','Other vehicles'],
    'hotels': ['Rooms','Suites','Family stays','Long stay','Conference','Dining','Experiences'],
    'restaurants': ['Breakfast','Lunch','Dinner','Drinks','Café','Private dining','Catering'],
    'marine': ['Yachts','Boats','Fishing boats','Jet skis','Charter','Marine equipment'],
    'property': ['For sale','For rent','Land','Residential','Commercial','New developments'],
    'electronics': ['Phones','Laptops','TV & Audio','Appliances','Cameras','Accessories'],
    'furniture': ['Living room','Bedroom','Office','Outdoor','Decor','Made to order'],
    'equipment': ['Construction','Agriculture','Generators','Workshop','Commercial','Parts'],
    'events': ['Venues','Photography','Catering','Decor','Entertainment','Professional services'],
    'marketplace': ['Featured','New arrivals','Deals','Home','Business','Lifestyle'],
}

TYPE_CONTENT = {
    'vehicles': ('Move with confidence.', 'A visual marketplace for vehicles, fleet and transport assets.'),
    'hotels': ('Stay somewhere worth remembering.', 'Rooms, suites, dining and hospitality experiences presented beautifully.'),
    'restaurants': ('Good places. Great reasons to visit.', 'Menus, dining, drinks and experiences made easy to discover.'),
    'marine': ('Take the next journey offshore.', 'Boats, yachts, marine equipment and charter opportunities.'),
    'property': ('Find a place that feels right.', 'Property, land, rentals and developments presented for confident decisions.'),
    'electronics': ('Technology, clearly presented.', 'Shop phones, computers, appliances and everyday tech.'),
    'furniture': ('Make space feel like yours.', 'Furniture, interiors and home collections with a visual-first catalogue.'),
    'equipment': ('Serious equipment. Ready for work.', 'Machinery, generators, agricultural and commercial equipment.'),
    'events': ('Bring the next occasion together.', 'Venues and services for events, creative work and professional needs.'),
    'marketplace': ('Beautiful things deserve a better storefront.', 'A broad digital marketplace for products, offers and local commerce.'),
}

DEMO_CONTACTS = {
    'phone': '+254 700 123 456',
    'whatsapp': '+254 711 456 789',
    'email': 'hello@multibusiness.demo',
    'location': 'Nairobi, Kenya',
}


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


def now():
    return datetime.utcnow().isoformat(timespec='seconds') + 'Z'


def slugify(value):
    return re.sub(r'[^a-z0-9]+', '-', value.lower()).strip('-')


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = db()
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS business (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        name TEXT NOT NULL,
        business_type TEXT NOT NULL,
        location TEXT,
        phone TEXT,
        whatsapp TEXT,
        email TEXT,
        website TEXT,
        socials TEXT,
        description TEXT,
        logo TEXT,
        cover_image TEXT,
        contact_person TEXT,
        created_at TEXT,
        updated_at TEXT
    );
    CREATE TABLE IF NOT EXISTS listings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        type TEXT NOT NULL,
        category TEXT,
        title TEXT NOT NULL,
        price TEXT,
        location TEXT,
        condition TEXT,
        status TEXT DEFAULT 'AVAILABLE',
        featured INTEGER DEFAULT 0,
        image TEXT,
        gallery TEXT,
        details_json TEXT,
        seller_name TEXT,
        seller_phone TEXT,
        seller_whatsapp TEXT,
        description TEXT,
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS enquiries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        listing_id INTEGER,
        name TEXT,
        phone TEXT,
        email TEXT,
        message TEXT,
        kind TEXT DEFAULT 'enquiry',
        created_at TEXT,
        FOREIGN KEY(listing_id) REFERENCES listings(id) ON DELETE SET NULL
    );
    CREATE TABLE IF NOT EXISTS qr_codes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE,
        listing_id INTEGER,
        created_at TEXT,
        FOREIGN KEY(listing_id) REFERENCES listings(id) ON DELETE SET NULL
    );
    CREATE TABLE IF NOT EXISTS seller_submissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        phone TEXT,
        whatsapp TEXT,
        listing_type TEXT,
        title TEXT,
        payload_json TEXT,
        status TEXT DEFAULT 'PENDING',
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS activity (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        action TEXT,
        detail TEXT,
        created_at TEXT
    );
    ''')
    existing = conn.execute('SELECT id FROM business WHERE id = 1').fetchone()
    if not existing:
        conn.execute('''INSERT INTO business
            (id,name,business_type,location,phone,whatsapp,email,website,socials,description,logo,cover_image,contact_person,created_at,updated_at)
            VALUES (1,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (
            'Mavuno Market House','vehicles',DEMO_CONTACTS['location'],DEMO_CONTACTS['phone'],DEMO_CONTACTS['whatsapp'],DEMO_CONTACTS['email'],
            'https://example.com','Instagram: @mavunomarket | Facebook: Mavuno Market House',
            'A polished demo marketplace for businesses that want a beautiful place to present products, receive enquiries and connect physical items to digital profiles.',
            'M','https://images.unsplash.com/photo-1492144534655-ae79c964c9d7?auto=format&fit=crop&w=1800&q=85',
            'Amina Mwangi', now(), now()))
        seed_demo_data(conn)
    conn.commit()
    conn.close()
    export_json()


def seed_demo_data(conn):
    vehicles = [
        ('vehicles','Cars','Toyota Crown Athlete','KES 4,850,000','Nairobi','SECOND HAND','AVAILABLE',1,
         'https://images.unsplash.com/photo-1550355291-bbee04a92027?auto=format&fit=crop&w=1200&q=85',
         ['https://images.unsplash.com/photo-1549317661-bd32c8ce0db2?auto=format&fit=crop&w=1200&q=85','https://images.unsplash.com/photo-1511919884226-fd3cad34687c?auto=format&fit=crop&w=1200&q=85'],
         {'make':'Toyota','model':'Crown Athlete','year':'2022','mileage':'38,400 km','fuel':'Petrol','transmission':'Automatic','engine':'2.5L','drive':'RWD','body':'Sedan','colour':'Pearl White','service_history':'Full service history','ownership':'Local private ownership','availability':'Available for viewing','financing':'Financing available'},
         'Mavuno Auto Desk',DEMO_CONTACTS['phone'],DEMO_CONTACTS['whatsapp'],'Executive sedan in excellent condition with clean interior, smart safety features and complete service records.'),
        ('vehicles','SUVs','Toyota Land Cruiser Prado TX','KES 8,950,000','Nairobi','SECOND HAND','AVAILABLE',1,
         'https://images.unsplash.com/photo-1519641471654-76ce0107ad1b?auto=format&fit=crop&w=1200&q=85',
         ['https://images.unsplash.com/photo-1606664515524-ed2f786a0bd6?auto=format&fit=crop&w=1200&q=85'],
         {'make':'Toyota','model':'Land Cruiser Prado TX','year':'2021','mileage':'61,200 km','fuel':'Diesel','transmission':'Automatic','engine':'2.8L','drive':'4WD','body':'SUV','colour':'Graphite','service_history':'Dealer maintained','ownership':'Verified ownership','availability':'Available for viewing','financing':'Available on request'},
         'Mavuno Auto Desk',DEMO_CONTACTS['phone'],DEMO_CONTACTS['whatsapp'],'Capable 4WD SUV prepared for both city driving and long-distance travel.'),
        ('vehicles','Trucks','Isuzu NQR 75 Truck','KES 5,600,000','Nairobi','SECOND HAND','AVAILABLE',0,
         'https://images.unsplash.com/photo-1586191582151-f73872dfd183?auto=format&fit=crop&w=1200&q=85',
         ['https://images.unsplash.com/photo-1615906655593-ad0386982a0f?auto=format&fit=crop&w=1200&q=85'],
         {'make':'Isuzu','model':'NQR 75','year':'2020','mileage':'108,000 km','fuel':'Diesel','transmission':'Manual','engine':'5.2L','drive':'4x2','body':'Light Truck','colour':'White','service_history':'Fleet history available','ownership':'Commercial fleet','availability':'Available','financing':'Ask dealer'},
         'Mavuno Commercial',DEMO_CONTACTS['phone'],DEMO_CONTACTS['whatsapp'],'Reliable commercial truck with practical loading capacity for business use.'),
        ('vehicles','Vans','Toyota Hiace Shuttle','KES 6,250,000','Nakuru','SECOND HAND','AVAILABLE',0,
         'https://images.unsplash.com/photo-1609521263047-f8f205293f24?auto=format&fit=crop&w=1200&q=85',
         ['https://images.unsplash.com/photo-1619767886558-efdc259cde1a?auto=format&fit=crop&w=1200&q=85'],
         {'make':'Toyota','model':'Hiace Shuttle','year':'2022','mileage':'43,700 km','fuel':'Diesel','transmission':'Automatic','engine':'2.8L','drive':'RWD','body':'Passenger Van','colour':'Silver','service_history':'Complete','ownership':'Verified','availability':'Available','financing':'Available'},
         'Mavuno Commercial',DEMO_CONTACTS['phone'],DEMO_CONTACTS['whatsapp'],'Clean passenger van suitable for school, hotel, corporate and shuttle operations.'),
        ('vehicles','Motorcycles','Honda CB500X','KES 890,000','Nairobi','SECOND HAND','AVAILABLE',0,
         'https://images.unsplash.com/photo-1558981806-ec527fa84c39?auto=format&fit=crop&w=1200&q=85',
         ['https://images.unsplash.com/photo-1558980664-10ea2b4ad2af?auto=format&fit=crop&w=1200&q=85'],
         {'make':'Honda','model':'CB500X','year':'2023','mileage':'11,600 km','fuel':'Petrol','transmission':'Manual','engine':'471cc','drive':'Chain','body':'Adventure Motorcycle','colour':'Black','service_history':'Service records','ownership':'Private','availability':'Available','financing':'Ask dealer'},
         'Mavuno Bikes',DEMO_CONTACTS['phone'],DEMO_CONTACTS['whatsapp'],'Adventure motorcycle with low mileage and a clean, well-kept finish.'),
    ]
    for row in vehicles:
        conn.execute('''INSERT INTO listings
        (type,category,title,price,location,condition,status,featured,image,gallery,details_json,seller_name,seller_phone,seller_whatsapp,description,created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (*row[:9], json.dumps(row[9]), row[10],row[11],row[12],row[13],now()))
    generic = [
        ('property','For sale','3-Bedroom Garden Residence','KES 18,500,000','Karen','NEW','AVAILABLE',1,'https://images.unsplash.com/photo-1605146769289-440113cc3d00?auto=format&fit=crop&w=1200&q=85',{},'Mavuno Property Desk','Beautiful family residence on a leafy compound.'),
        ('hotels','Rooms','Acacia Ridge Deluxe Suite','KES 15,000 / night','Nairobi','NEW','AVAILABLE',1,'https://images.unsplash.com/photo-1566665797739-1674de7a421a?auto=format&fit=crop&w=1200&q=85',{},'Mavuno Hospitality','A calm, premium suite with breakfast and high-speed Wi-Fi.'),
        ('restaurants','Dinner','Chef’s Signature Dining Experience','KES 4,500','Nairobi','NEW','AVAILABLE',0,'https://images.unsplash.com/photo-1414235077428-338989a2e8c0?auto=format&fit=crop&w=1200&q=85',{},'Mavuno Table','An elegant dining experience built around seasonal ingredients.'),
        ('marketplace','Featured','Handcrafted Lounge Collection','KES 78,000','Nairobi','NEW','AVAILABLE',1,'https://images.unsplash.com/photo-1555041469-a586c61ea9bc?auto=format&fit=crop&w=1200&q=85',{},'Mavuno Home','A refined living-room set designed for comfortable everyday use.'),
        ('electronics','Laptops','Pro Creator Laptop 14','KES 145,000','Nairobi','SECOND HAND','AVAILABLE',0,'https://images.unsplash.com/photo-1496181133206-80ce9b88a853?auto=format&fit=crop&w=1200&q=85',{},'Mavuno Tech','Clean, performance-focused laptop for business and creative work.'),
    ]
    for typ, cat, title, price, loc, cond, status, featured, image, details, seller, desc in generic:
        conn.execute('''INSERT INTO listings
            (type,category,title,price,location,condition,status,featured,image,gallery,details_json,seller_name,seller_phone,seller_whatsapp,description,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (typ,cat,title,price,loc,cond,status,featured,image,json.dumps([]),json.dumps(details),seller,DEMO_CONTACTS['phone'],DEMO_CONTACTS['whatsapp'],desc,now()))
    conn.execute("INSERT INTO activity(action,detail,created_at) VALUES (?,?,?)", ('Platform seeded','Demo listings created for presentation',now()))


def get_business():
    conn = db(); row = conn.execute('SELECT * FROM business WHERE id=1').fetchone(); conn.close()
    return dict(row) if row else None


def get_listings(typ=None, q=None, category=None, min_price=None, max_price=None):
    conn = db()
    sql = 'SELECT * FROM listings WHERE 1=1'
    params = []
    if typ:
        sql += ' AND type=?'; params.append(typ)
    if q:
        sql += ' AND (title LIKE ? OR description LIKE ? OR category LIKE ? OR location LIKE ?)'; like=f'%{q}%'; params += [like,like,like,like]
    if category:
        sql += ' AND category=?'; params.append(category)
    rows = [dict(r) for r in conn.execute(sql + ' ORDER BY featured DESC, id DESC', params).fetchall()]
    conn.close()
    for r in rows:
        r['gallery'] = json.loads(r['gallery'] or '[]')
        r['details'] = json.loads(r['details_json'] or '{}')
    return rows


def get_listing(listing_id):
    conn=db(); r=conn.execute('SELECT * FROM listings WHERE id=?',(listing_id,)).fetchone(); conn.close()
    if not r: return None
    d=dict(r); d['gallery']=json.loads(d['gallery'] or '[]'); d['details']=json.loads(d['details_json'] or '{}'); return d


def export_json():
    try:
        conn=db()
        business=conn.execute('SELECT * FROM business WHERE id=1').fetchone()
        listings=conn.execute('SELECT * FROM listings').fetchall()
        sellers=conn.execute('SELECT * FROM seller_submissions').fetchall()
        enquiries=conn.execute('SELECT * FROM enquiries').fetchall()
        qrs=conn.execute('SELECT * FROM qr_codes').fetchall()
        payload={
            'version':'1.0', 'exported_at':now(),
            'business': dict(business) if business else None,
            'listings':[dict(x) for x in listings], 'seller_submissions':[dict(x) for x in sellers],
            'enquiries':[dict(x) for x in enquiries], 'qr_codes':[dict(x) for x in qrs]
        }
        JSON_PATH.write_text(json.dumps(payload, indent=2), encoding='utf-8')
        conn.close()
    except Exception:
        pass


def make_backup():
    BACKUP_DIR.mkdir(exist_ok=True)
    export_json()
    stamp=datetime.now().strftime('%Y%m%d_%H%M%S')
    backup=BACKUP_DIR/f'multibusiness_backup_{stamp}.zip'
    with zipfile.ZipFile(backup,'w',zipfile.ZIP_DEFLATED) as z:
        z.write(DB_PATH, arcname='data/multibusiness.db')
        z.write(JSON_PATH, arcname='data/business.json')
    return backup


@app.context_processor
def inject_globals():
    b=get_business() or {}
    business_type_labels={key: label for key, label, _ in BUSINESS_TYPES}
    return {
        'business': b,
        'business_types': BUSINESS_TYPES,
        'business_type_labels': business_type_labels,
        'sections': SECTIONS,
        'get_listings': get_listings,
        'type_content': TYPE_CONTENT,
    }


@app.after_request
def add_cache_headers(response):
    if request.path.startswith('/static/'):
        response.headers['Cache-Control']='public, max-age=31536000, immutable'
    else:
        response.headers['Cache-Control']='no-store'
    return response


@app.route('/')
def index():
    return render_template('index.html', business=get_business())


@app.route('/setup', methods=['GET','POST'])
def setup():
    b=get_business() or {}
    if request.method=='GET' and request.args.get('type'):
        b = dict(b); b['business_type'] = request.args.get('type')
    if request.method=='POST':
        form=request.form
        conn=db()
        conn.execute('''UPDATE business SET name=?, business_type=?, location=?, phone=?, whatsapp=?, email=?, website=?, socials=?, description=?, logo=?, cover_image=?, contact_person=?, updated_at=? WHERE id=1''',(
            form.get('name','Mavuno Market House').strip(), form.get('business_type','marketplace'), form.get('location','').strip(),form.get('phone','').strip(),form.get('whatsapp','').strip(),form.get('email','').strip(),form.get('website','').strip(),form.get('socials','').strip(),form.get('description','').strip(),form.get('logo','M').strip(),form.get('cover_image','').strip(),form.get('contact_person','').strip(),now()))
        conn.execute('INSERT INTO activity(action,detail,created_at) VALUES (?,?,?)',('Business setup updated',form.get('name','')))
        conn.commit(); conn.close(); export_json()
        return redirect(url_for('site_home'))
    return render_template('setup.html', business=b)


@app.route('/site')
def site_home():
    b=get_business(); typ=b['business_type']; listings=get_listings(typ=typ)
    # Keep the public site populated even before a business has its own catalogue.
    if not listings:
        listings=get_listings()
    return render_template('site_home.html', typ=typ, listings=listings[:12], categories=SECTIONS.get(typ,[]))


@app.route('/browse')
def browse():
    typ=request.args.get('type') or get_business()['business_type']
    q=request.args.get('q','').strip(); category=request.args.get('category','').strip()
    listings=get_listings(typ=typ if typ!='all' else None,q=q,category=category or None)
    return render_template('browse.html', listings=listings, typ=typ, q=q, category=category, categories=SECTIONS.get(typ,[]))


@app.route('/listing/<int:listing_id>')
def listing_detail(listing_id):
    item=get_listing(listing_id)
    if not item: abort(404)
    return render_template('listing_detail.html', item=item)


@app.route('/sell', methods=['GET','POST'])
def sell():
    if request.method=='POST':
        fields={k:v.strip() for k,v in request.form.items() if k not in ('photos',)}
        conn=db(); conn.execute('''INSERT INTO seller_submissions(name,phone,whatsapp,listing_type,title,payload_json,status,created_at) VALUES (?,?,?,?,?,?,?,?)''',(
            fields.get('name',''),fields.get('phone',''),fields.get('whatsapp',''),fields.get('listing_type',get_business()['business_type']),fields.get('title',''),json.dumps(fields), 'PENDING', now()))
        conn.execute('INSERT INTO activity(action,detail,created_at) VALUES (?,?,?)',('New seller submission',fields.get('title','Untitled listing')))
        conn.commit(); conn.close(); export_json()
        return render_template('submission_received.html')
    return render_template('sell.html', typ=get_business()['business_type'])


@app.route('/contact', methods=['GET','POST'])
def contact():
    if request.method=='POST':
        form=request.form
        conn=db(); conn.execute('INSERT INTO enquiries(name,phone,email,message,kind,created_at) VALUES (?,?,?,?,?,?)',(
            form.get('name',''),form.get('phone',''),form.get('email',''),form.get('message',''),'contact',now()))
        conn.execute('INSERT INTO activity(action,detail,created_at) VALUES (?,?,?)',('New enquiry',form.get('name',''))); conn.commit(); conn.close(); export_json();
        flash('Message received. The business can follow up from the admin portal.','success')
        return redirect(url_for('contact'))
    return render_template('contact.html')


@app.route('/qr')
def qr_home():
    conn=db(); rows=conn.execute('''SELECT q.*, l.title FROM qr_codes q LEFT JOIN listings l ON l.id=q.listing_id ORDER BY q.id DESC''').fetchall(); conn.close()
    return render_template('qr.html', qrs=[dict(r) for r in rows])


@app.route('/qr/generate', methods=['POST'])
def qr_generate():
    listing_id=request.form.get('listing_id')
    code='MB-' + datetime.now().strftime('%y%m%d%H%M%S') + '-' + os.urandom(2).hex().upper()
    conn=db(); conn.execute('INSERT INTO qr_codes(code,listing_id,created_at) VALUES (?,?,?)',(code,listing_id or None,now())); conn.execute('INSERT INTO activity(action,detail,created_at) VALUES (?,?,?)',('QR generated',code)); conn.commit(); conn.close(); export_json()
    return redirect(url_for('qr_home'))


@app.route('/qr/<code>.png')
def qr_png(code):
    conn=db(); row=conn.execute('SELECT listing_id FROM qr_codes WHERE code=?',(code,)).fetchone(); conn.close()
    if not row: abort(404)
    target=url_for('qr_redirect', code=code, _external=True)
    img=qrcode.make(target)
    bio=io.BytesIO(); img.save(bio, format='PNG'); bio.seek(0)
    return send_file(bio,mimetype='image/png',download_name=f'{code}.png')


@app.route('/qr/<code>')
def qr_redirect(code):
    conn=db(); row=conn.execute('SELECT listing_id FROM qr_codes WHERE code=?',(code,)).fetchone(); conn.close()
    if not row or not row['listing_id']: abort(404)
    return redirect(url_for('listing_detail',listing_id=row['listing_id']))


@app.route('/admin')
def admin():
    conn=db()
    metrics={
        'vehicles':conn.execute("SELECT COUNT(*) n FROM listings WHERE type='vehicles'").fetchone()['n'],
        'available':conn.execute("SELECT COUNT(*) n FROM listings WHERE status='AVAILABLE'").fetchone()['n'],
        'sold':conn.execute("SELECT COUNT(*) n FROM listings WHERE status='SOLD'").fetchone()['n'],
        'pending':conn.execute("SELECT COUNT(*) n FROM seller_submissions WHERE status='PENDING'").fetchone()['n'],
        'submissions':conn.execute('SELECT COUNT(*) n FROM seller_submissions').fetchone()['n'],
        'qrs':conn.execute('SELECT COUNT(*) n FROM qr_codes').fetchone()['n'],
        'enquiries':conn.execute('SELECT COUNT(*) n FROM enquiries').fetchone()['n'],
        'viewings':conn.execute("SELECT COUNT(*) n FROM enquiries WHERE kind='viewing'").fetchone()['n'],
    }
    activity=[dict(x) for x in conn.execute('SELECT * FROM activity ORDER BY id DESC LIMIT 8').fetchall()]
    submissions=[dict(x) for x in conn.execute('SELECT * FROM seller_submissions ORDER BY id DESC LIMIT 8').fetchall()]
    conn.close()
    return render_template('admin.html', metrics=metrics, activity=activity, submissions=submissions)


@app.route('/admin/listings')
def admin_listings():
    listings=get_listings()
    return render_template('admin_listings.html', listings=listings)


@app.route('/admin/submission/<int:sid>/<action>', methods=['POST'])
def submission_action(sid,action):
    status='APPROVED' if action=='approve' else 'REJECTED'
    conn=db(); row=conn.execute('SELECT * FROM seller_submissions WHERE id=?',(sid,)).fetchone()
    if row: conn.execute('UPDATE seller_submissions SET status=? WHERE id=?',(status,sid)); conn.execute('INSERT INTO activity(action,detail,created_at) VALUES (?,?,?)',('Seller submission '+status.lower(),row['title'])); conn.commit()
    conn.close(); export_json(); return redirect(url_for('admin'))


@app.route('/admin/backup')
def admin_backup():
    return render_template('backup.html')


@app.route('/admin/backup/create', methods=['POST'])
def create_backup():
    path=make_backup(); return send_file(path,as_attachment=True,download_name=path.name)


@app.route('/admin/export.json')
def export_file():
    export_json(); return send_file(JSON_PATH,as_attachment=True,download_name='multibusiness_business.json',mimetype='application/json')


@app.route('/admin/restore', methods=['POST'])
def restore():
    uploaded=request.files.get('backup')
    if not uploaded or not uploaded.filename:
        flash('Choose a JSON backup file to restore.','error'); return redirect(url_for('admin_backup'))
    try:
        payload=json.loads(uploaded.read().decode('utf-8'))
        b=payload.get('business')
        if b:
            conn=db(); conn.execute('''UPDATE business SET name=?,business_type=?,location=?,phone=?,whatsapp=?,email=?,website=?,socials=?,description=?,logo=?,cover_image=?,contact_person=?,updated_at=? WHERE id=1''', (b.get('name'),b.get('business_type'),b.get('location'),b.get('phone'),b.get('whatsapp'),b.get('email'),b.get('website'),b.get('socials'),b.get('description'),b.get('logo'),b.get('cover_image'),b.get('contact_person'),now()))
            conn.execute('INSERT INTO activity(action,detail,created_at) VALUES (?,?,?)',('Business restore','JSON backup imported'))
            conn.commit(); conn.close(); export_json()
            flash('Business profile restored successfully.','success')
        else:
            flash('The backup file did not contain a business profile.','error')
    except Exception as exc:
        flash(f'Restore failed: {exc}','error')
    return redirect(url_for('admin_backup'))


@app.route('/favicon.ico')
def favicon():
    return ('', 204)


@app.route('/health')
def health():
    return jsonify({'status':'ok','app':'MultiBusiness v1','time':now()})


@app.errorhandler(404)
def not_found(e):
    return render_template('error.html', code=404, message='The page you are looking for is not available.'),404


if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT',5000)), debug=True)
else:
    init_db()
