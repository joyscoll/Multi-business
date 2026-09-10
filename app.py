from flask import Flask, render_template, request, redirect, url_for, jsonify, flash, send_file, abort, has_request_context
from pathlib import Path
from datetime import datetime
from collections import deque
import sqlite3, json, os, re, time, traceback, io, zipfile, shutil, uuid
import qrcode

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / 'data' / 'multibusiness.db'
JSON_PATH = BASE_DIR / 'data' / 'business.json'
BACKUP_DIR = BASE_DIR / 'backups'
ERROR_LOG = BASE_DIR / 'data' / 'system_errors.jsonl'
ERROR_MEMORY = deque(maxlen=100)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'multibusiness-v1-demo-secret')
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 86400

BUSINESS_TYPES = [
    ('vehicles','Vehicles & Transport','Cars, SUVs, trucks, vans, buses, motorcycles and fleet.'),
    ('hotels','Hotels & Lodges','Rooms, suites, stays, dining, facilities and reservations.'),
    ('restaurants','Restaurants, Bars & Cafés','Menus, dining, drinks, reservations, orders and catering.'),
    ('marine','Boats, Marine & Yachts','Boats, yachts, marine equipment, charter and water experiences.'),
    ('property','Real Estate & Property','Homes, land, rentals, commercial property and developments.'),
    ('electronics','Electronics & Appliances','Phones, computers, TVs, appliances, cameras and accessories.'),
    ('furniture','Furniture & Home','Living, bedroom, office, outdoor, decor and made-to-order.'),
    ('equipment','Equipment & Machinery','Construction, agricultural, generators, workshop and industrial.'),
    ('events','Events & Services','Venues, photography, catering, decor, entertainment and services.'),
    ('marketplace','Retail & General Marketplace','Products, offers, local retail and mixed-category commerce.'),
]
BUSINESS_LABELS = dict((x[0], x[1]) for x in BUSINESS_TYPES)
SECTIONS = {
    'vehicles':['Cars','SUVs','Trucks','Vans','Buses','Motorcycles','Commercial vehicles','Other vehicles'],
    'hotels':['Rooms','Suites','Family stays','Long stay','Conference','Dining','Experiences'],
    'restaurants':['Breakfast','Lunch','Dinner','Drinks','Café','Private dining','Catering'],
    'marine':['Yachts','Boats','Fishing boats','Jet skis','Charter','Marine equipment'],
    'property':['For sale','For rent','Land','Residential','Commercial','New developments'],
    'electronics':['Phones','Laptops','TV & Audio','Appliances','Cameras','Accessories'],
    'furniture':['Living room','Bedroom','Office','Outdoor','Decor','Made to order'],
    'equipment':['Construction','Agriculture','Generators','Workshop','Commercial','Parts'],
    'events':['Venues','Photography','Catering','Decor','Entertainment','Professional services'],
    'marketplace':['Featured','New arrivals','Deals','Home','Business','Lifestyle'],
}
TYPE_CONTENT = {
    'vehicles':('Move with confidence.','Browse, reserve, buy, finance and inspect every vehicle from one digital profile.'),
    'hotels':('Stay somewhere worth remembering.','Browse real rooms, choose a room number, book your stay and request services.'),
    'restaurants':('Good places. Great reasons to visit.','Explore the menu, reserve a table, place an order or request catering.'),
    'marine':('Take the next journey offshore.','Discover boats, yachts and charter options with enquiry and reservation workflows.'),
    'property':('Find a place that feels right.','Explore property, arrange a viewing, make an offer or request a rental.'),
    'electronics':('Technology, clearly presented.','Compare products, request a purchase, arrange delivery and contact the seller.'),
    'furniture':('Make space feel like yours.','Browse collections, request an item, customise it or arrange delivery.'),
    'equipment':('Serious equipment. Ready for work.','Review specifications, request a quote, reserve equipment or arrange inspection.'),
    'events':('Bring the next occasion together.','Browse venues and services, request dates, quotes and complete event enquiries.'),
    'marketplace':('A better place to buy and sell.','Browse products, contact sellers, place orders and submit your own listing.'),
}
DEMO_CONTACTS={'phone':'+254 700 123 456','whatsapp':'+254 711 456 789','email':'hello@multibusiness.demo','location':'Nairobi, Kenya'}

ENGINE_ACTIONS={
    'vehicles':[('PURCHASE','Start purchase'),('FINANCE','Request financing'),('VIEWING','Request viewing'),('OFFER','Make an offer')],
    'hotels':[('BOOKING','Book room'),('SERVICE','Request service'),('INQUIRY','Ask hotel')],
    'restaurants':[('ORDER','Place order'),('RESERVATION','Reserve table'),('CATERING','Request catering')],
    'marine':[('CHARTER','Request charter'),('PURCHASE','Request purchase'),('VIEWING','Arrange inspection')],
    'property':[('VIEWING','Book viewing'),('OFFER','Make offer'),('RENTAL','Request rental')],
    'electronics':[('PURCHASE','Buy / reserve'),('DELIVERY','Request delivery'),('INQUIRY','Ask seller')],
    'furniture':[('PURCHASE','Buy item'),('CUSTOM','Request custom'),('DELIVERY','Request delivery')],
    'equipment':[('QUOTE','Request quote'),('RESERVE','Reserve equipment'),('VIEWING','Arrange inspection')],
    'events':[('BOOKING','Request booking'),('QUOTE','Request quote'),('INQUIRY','Ask provider')],
    'marketplace':[('PURCHASE','Buy / reserve'),('INQUIRY','Ask seller')],
}


def now(): return datetime.utcnow().isoformat(timespec='seconds')+'Z'
def slugify(v): return re.sub(r'[^a-z0-9]+','-',v.lower()).strip('-')

def db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn=sqlite3.connect(DB_PATH, timeout=20, isolation_level=None)
    conn.row_factory=sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    conn.execute('PRAGMA busy_timeout = 20000')
    try: conn.execute('PRAGMA journal_mode = WAL')
    except sqlite3.DatabaseError: pass
    conn.execute('PRAGMA synchronous = NORMAL')
    return conn

def log_system_error(error, endpoint=None):
    record={'time':now(),'endpoint':endpoint or (request.path if has_request_context() else None),'method':request.method if has_request_context() else None,'error_type':type(error).__name__,'message':str(error),'traceback':traceback.format_exc()}
    ERROR_MEMORY.appendleft(record)
    try:
        ERROR_LOG.parent.mkdir(parents=True,exist_ok=True)
        with ERROR_LOG.open('a',encoding='utf-8') as f: f.write(json.dumps(record,ensure_ascii=False)+'\n')
    except Exception: pass

def read_system_errors(limit=100):
    rows=list(ERROR_MEMORY)
    try:
        if ERROR_LOG.exists():
            disk=[]
            for line in ERROR_LOG.read_text(encoding='utf-8').splitlines()[-limit:]:
                try: disk.append(json.loads(line))
                except Exception: pass
            rows=disk[::-1]
    except Exception: pass
    return rows[:limit]

def execute_write(conn, sql, params=(), retries=5):
    last=None
    for attempt in range(retries):
        try:
            conn.execute('BEGIN IMMEDIATE'); cur=conn.execute(sql,params); conn.commit(); return cur
        except sqlite3.OperationalError as exc:
            last=exc
            try: conn.rollback()
            except Exception: pass
            if 'locked' not in str(exc).lower() or attempt==retries-1: raise
            time.sleep(0.2*(attempt+1))
    raise last

def activity(conn, action, detail):
    conn.execute('INSERT INTO activity(action,detail,created_at) VALUES (?,?,?)',(action,detail,now()))

def init_db():
    conn=db()
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS business(id INTEGER PRIMARY KEY CHECK(id=1),name TEXT NOT NULL,business_type TEXT NOT NULL,location TEXT,phone TEXT,whatsapp TEXT,email TEXT,website TEXT,socials TEXT,description TEXT,logo TEXT,cover_image TEXT,contact_person TEXT,created_at TEXT,updated_at TEXT);
    CREATE TABLE IF NOT EXISTS listings(id INTEGER PRIMARY KEY AUTOINCREMENT,type TEXT NOT NULL,category TEXT,title TEXT NOT NULL,price TEXT,location TEXT,condition TEXT,status TEXT DEFAULT 'AVAILABLE',featured INTEGER DEFAULT 0,image TEXT,gallery TEXT,details_json TEXT,seller_name TEXT,seller_phone TEXT,seller_whatsapp TEXT,description TEXT,created_at TEXT);
    CREATE TABLE IF NOT EXISTS enquiries(id INTEGER PRIMARY KEY AUTOINCREMENT,listing_id INTEGER,name TEXT,phone TEXT,email TEXT,message TEXT,kind TEXT DEFAULT 'enquiry',created_at TEXT,FOREIGN KEY(listing_id) REFERENCES listings(id) ON DELETE SET NULL);
    CREATE TABLE IF NOT EXISTS qr_codes(id INTEGER PRIMARY KEY AUTOINCREMENT,code TEXT UNIQUE,listing_id INTEGER,scan_count INTEGER DEFAULT 0,created_at TEXT,FOREIGN KEY(listing_id) REFERENCES listings(id) ON DELETE SET NULL);
    CREATE TABLE IF NOT EXISTS seller_submissions(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,whatsapp TEXT,listing_type TEXT,title TEXT,payload_json TEXT,status TEXT DEFAULT 'PENDING',created_at TEXT);
    CREATE TABLE IF NOT EXISTS activity(id INTEGER PRIMARY KEY AUTOINCREMENT,action TEXT,detail TEXT,created_at TEXT);
    CREATE TABLE IF NOT EXISTS operations(id INTEGER PRIMARY KEY AUTOINCREMENT,listing_id INTEGER,business_type TEXT,operation_type TEXT,customer_name TEXT,phone TEXT,email TEXT,payload_json TEXT,status TEXT DEFAULT 'PENDING',created_at TEXT,FOREIGN KEY(listing_id) REFERENCES listings(id) ON DELETE SET NULL);
    CREATE TABLE IF NOT EXISTS hotel_rooms(id INTEGER PRIMARY KEY AUTOINCREMENT,listing_id INTEGER,room_number TEXT,room_type TEXT,status TEXT DEFAULT 'AVAILABLE',price TEXT,amenities TEXT,FOREIGN KEY(listing_id) REFERENCES listings(id) ON DELETE CASCADE);
    CREATE TABLE IF NOT EXISTS admin_users(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,role TEXT,phone TEXT,email TEXT,status TEXT DEFAULT 'ACTIVE');
    ''')
    # Add payment destination fields without breaking an existing v1 database.
    cols={r['name'] for r in conn.execute('PRAGMA table_info(business)').fetchall()}
    for col in ('till_number','paybill_number','bank_name','bank_account','payment_note'):
        if col not in cols:
            conn.execute(f'ALTER TABLE business ADD COLUMN {col} TEXT')
    if not conn.execute('SELECT 1 FROM business WHERE id=1').fetchone():
        conn.execute('INSERT INTO business(id,name,business_type,location,phone,whatsapp,email,website,socials,description,logo,cover_image,contact_person,created_at,updated_at) VALUES (1,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(
            'Mavuno Market House','vehicles',DEMO_CONTACTS['location'],DEMO_CONTACTS['phone'],DEMO_CONTACTS['whatsapp'],DEMO_CONTACTS['email'],'https://example.com','Instagram: @mavunomarket | Facebook: Mavuno Market House',
            'A digital selling space where products, services and physical items become interactive online experiences.','M','https://images.unsplash.com/photo-1492144534655-ae79c964c9d7?auto=format&fit=crop&w=1800&q=85','Amina Mwangi',now(),now()))
        conn.execute("UPDATE business SET till_number=?,paybill_number=?,bank_name=?,bank_account=?,payment_note=? WHERE id=1",('123456','400200','Demo Bank','0123456789',"Demo payment destination — replace with the business's real collection details."))
    if conn.execute('SELECT COUNT(*) n FROM listings').fetchone()['n']==0: seed_demo_data(conn)
    if conn.execute('SELECT COUNT(*) n FROM admin_users').fetchone()['n']==0:
        for row in [('Amina Mwangi','Business Admin',DEMO_CONTACTS['phone'],DEMO_CONTACTS['email']),('Brian Otieno','Listings Manager','+254 722 111 222','listings@multibusiness.demo'),('Faith Wanjiku','Customer Desk','+254 733 333 444','care@multibusiness.demo')]:
            conn.execute('INSERT INTO admin_users(name,role,phone,email) VALUES (?,?,?,?)',row)
    # Seed room numbers once the hotel template is first used.
    if conn.execute("SELECT COUNT(*) n FROM hotel_rooms").fetchone()['n']==0:
        hotel = conn.execute("SELECT id FROM listings WHERE type='hotels' LIMIT 1").fetchone()
        if hotel:
            for room,rt,price,amen in [('101','Deluxe Room','KES 15,000 / night','Breakfast, Wi-Fi, smart TV'),('102','Garden Suite','KES 21,000 / night','Breakfast, balcony, Wi-Fi, minibar'),('201','Family Suite','KES 28,000 / night','Two rooms, lounge, breakfast, Wi-Fi'),('305','Executive Suite','KES 36,000 / night','Lounge, city view, breakfast, airport pickup')]:
                conn.execute('INSERT INTO hotel_rooms(listing_id,room_number,room_type,status,price,amenities) VALUES (?,?,?,?,?,?)',(hotel['id'],room,rt,'AVAILABLE',price,amen))
    conn.commit(); conn.close(); export_json()

def seed_demo_data(conn):
    vehicles=[
    ('vehicles','Cars','Toyota Crown Athlete','KES 4,850,000','Nairobi','SECOND HAND','AVAILABLE',1,'https://images.unsplash.com/photo-1550355291-bbee04a92027?auto=format&fit=crop&w=1200&q=85',['https://images.unsplash.com/photo-1549317661-bd32c8ce0db2?auto=format&fit=crop&w=1200&q=85'],{'make':'Toyota','model':'Crown Athlete','year':'2022','mileage':'38,400 km','fuel':'Petrol','transmission':'Automatic','engine':'2.5L','drive':'RWD','body':'Sedan','colour':'Pearl White','service_history':'Full service history','ownership':'Verified local ownership','financing':'Available'},'Mavuno Auto Desk',DEMO_CONTACTS['phone'],DEMO_CONTACTS['whatsapp'],'Executive sedan with clean interior, strong service records and viewing available.'),
    ('vehicles','SUVs','Toyota Land Cruiser Prado TX','KES 8,950,000','Nairobi','SECOND HAND','AVAILABLE',1,'https://images.unsplash.com/photo-1519641471654-76ce0107ad1b?auto=format&fit=crop&w=1200&q=85',['https://images.unsplash.com/photo-1606664515524-ed2f786a0bd6?auto=format&fit=crop&w=1200&q=85'],{'make':'Toyota','model':'Land Cruiser Prado TX','year':'2021','mileage':'61,200 km','fuel':'Diesel','transmission':'Automatic','engine':'2.8L','drive':'4WD','body':'SUV','colour':'Graphite','service_history':'Dealer maintained','ownership':'Verified ownership','financing':'Available on request'},'Mavuno Auto Desk',DEMO_CONTACTS['phone'],DEMO_CONTACTS['whatsapp'],'Capable 4WD SUV prepared for city and long-distance travel.'),
    ('vehicles','Trucks','Isuzu NQR 75 Truck','KES 5,600,000','Nairobi','SECOND HAND','AVAILABLE',0,'https://images.unsplash.com/photo-1586191582151-f73872dfd183?auto=format&fit=crop&w=1200&q=85',[],{'make':'Isuzu','model':'NQR 75','year':'2020','mileage':'108,000 km','fuel':'Diesel','transmission':'Manual','engine':'5.2L','drive':'4x2','body':'Light Truck','colour':'White','service_history':'Fleet history available','ownership':'Commercial fleet','financing':'Ask dealer'},'Mavuno Commercial',DEMO_CONTACTS['phone'],DEMO_CONTACTS['whatsapp'],'Practical commercial truck ready for business use.'),
    ('vehicles','Vans','Toyota Hiace Shuttle','KES 6,250,000','Nakuru','SECOND HAND','AVAILABLE',0,'https://images.unsplash.com/photo-1609521263047-f8f205293f24?auto=format&fit=crop&w=1200&q=85',[],{'make':'Toyota','model':'Hiace Shuttle','year':'2022','mileage':'43,700 km','fuel':'Diesel','transmission':'Automatic','engine':'2.8L','drive':'RWD','body':'Passenger Van','colour':'Silver','service_history':'Complete','ownership':'Verified','financing':'Available'},'Mavuno Commercial',DEMO_CONTACTS['phone'],DEMO_CONTACTS['whatsapp'],'Clean passenger van suitable for school, hotel, corporate and shuttle operations.'),
    ('vehicles','Motorcycles','Honda CB500X','KES 890,000','Nairobi','SECOND HAND','AVAILABLE',0,'https://images.unsplash.com/photo-1558981806-ec527fa84c39?auto=format&fit=crop&w=1200&q=85',[],{'make':'Honda','model':'CB500X','year':'2023','mileage':'11,600 km','fuel':'Petrol','transmission':'Manual','engine':'471cc','drive':'Chain','body':'Adventure Motorcycle','colour':'Black','service_history':'Service records','ownership':'Private','financing':'Ask dealer'},'Mavuno Bikes',DEMO_CONTACTS['phone'],DEMO_CONTACTS['whatsapp'],'Adventure motorcycle with low mileage and a clean finish.')]
    for row in vehicles:
        conn.execute('INSERT INTO listings(type,category,title,price,location,condition,status,featured,image,gallery,details_json,seller_name,seller_phone,seller_whatsapp,description,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(*row[:9],json.dumps(row[9]),row[10],row[11],row[12],row[13],now()))
    generic=[
        ('property','For sale','3-Bedroom Garden Residence','KES 18,500,000','Karen','NEW','AVAILABLE',1,'https://images.unsplash.com/photo-1605146769289-440113cc3d00?auto=format&fit=crop&w=1200&q=85','Mavuno Property Desk','Beautiful family residence on a leafy compound.'),
        ('hotels','Rooms','Acacia Ridge Deluxe Suite','KES 15,000 / night','Nairobi','NEW','AVAILABLE',1,'https://images.unsplash.com/photo-1566665797739-1674de7a421a?auto=format&fit=crop&w=1200&q=85','Mavuno Hospitality','A calm premium suite with breakfast and high-speed Wi-Fi.'),
        ('restaurants','Dinner','Chef’s Signature Dining Experience','KES 4,500','Nairobi','NEW','AVAILABLE',0,'https://images.unsplash.com/photo-1414235077428-338989a2e8c0?auto=format&fit=crop&w=1200&q=85','Mavuno Table','An elegant dining experience built around seasonal ingredients.'),
        ('marketplace','Featured','Handcrafted Lounge Collection','KES 78,000','Nairobi','NEW','AVAILABLE',1,'https://images.unsplash.com/photo-1555041469-a586c61ea9bc?auto=format&fit=crop&w=1200&q=85','Mavuno Home','A refined living-room set designed for comfortable everyday use.'),
        ('electronics','Laptops','Pro Creator Laptop 14','KES 145,000','Nairobi','SECOND HAND','AVAILABLE',0,'https://images.unsplash.com/photo-1496181133206-80ce9b88a853?auto=format&fit=crop&w=1200&q=85','Mavuno Tech','Clean performance-focused laptop for business and creative work.')]
    for typ,cat,title,price,loc,cond,status,featured,img,seller,desc in generic:
        conn.execute('INSERT INTO listings(type,category,title,price,location,condition,status,featured,image,gallery,details_json,seller_name,seller_phone,seller_whatsapp,description,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(typ,cat,title,price,loc,cond,status,featured,img,json.dumps([]),json.dumps({'service':'Demo information'}),seller,DEMO_CONTACTS['phone'],DEMO_CONTACTS['whatsapp'],desc,now()))
    activity(conn,'Platform seeded','Demo marketplace content created for presentation')

def get_business():
    conn=db(); row=conn.execute('SELECT * FROM business WHERE id=1').fetchone(); conn.close(); return dict(row) if row else {}

def get_listings(typ=None,q=None,category=None,status=None):
    conn=db(); sql='SELECT * FROM listings WHERE 1=1'; params=[]
    if typ and typ!='all': sql+=' AND type=?'; params.append(typ)
    if q: sql+=' AND (title LIKE ? OR description LIKE ? OR category LIKE ? OR location LIKE ?)'; like='%'+q+'%'; params += [like]*4
    if category: sql+=' AND category=?'; params.append(category)
    if status: sql+=' AND status=?'; params.append(status)
    rows=[dict(r) for r in conn.execute(sql+' ORDER BY featured DESC,id DESC',params).fetchall()]; conn.close()
    for r in rows: r['gallery']=json.loads(r.get('gallery') or '[]'); r['details']=json.loads(r.get('details_json') or '{}')
    return rows

def get_listing(lid):
    conn=db(); row=conn.execute('SELECT * FROM listings WHERE id=?',(lid,)).fetchone(); conn.close()
    if not row:return None
    d=dict(row); d['gallery']=json.loads(d.get('gallery') or '[]'); d['details']=json.loads(d.get('details_json') or '{}'); return d

def get_rooms(listing_id=None):
    conn=db(); rows=[dict(x) for x in (conn.execute('SELECT * FROM hotel_rooms WHERE listing_id=? ORDER BY room_number',(listing_id,)) if listing_id is not None else conn.execute('SELECT * FROM hotel_rooms ORDER BY room_number')).fetchall()]; conn.close(); return rows

def export_json():
    conn=None
    try:
        conn=db(); payload={'version':'2.0','exported_at':now()}
        for table in ['business','listings','seller_submissions','enquiries','qr_codes','activity','operations','hotel_rooms','admin_users']:
            rows=conn.execute(f'SELECT * FROM {table}').fetchall(); payload[table]=[dict(x) for x in rows]
        tmp=JSON_PATH.with_suffix('.tmp'); tmp.write_text(json.dumps(payload,indent=2,ensure_ascii=False),encoding='utf-8'); tmp.replace(JSON_PATH); return True
    except Exception as exc: log_system_error(exc,'export_json'); return False
    finally:
        if conn:
            try: conn.close()
            except Exception: pass

def make_backup():
    BACKUP_DIR.mkdir(exist_ok=True); export_json(); stamp=datetime.now().strftime('%Y%m%d_%H%M%S'); path=BACKUP_DIR/f'multibusiness_backup_{stamp}.zip'
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
        if DB_PATH.exists(): z.write(DB_PATH,'data/multibusiness.db')
        if JSON_PATH.exists(): z.write(JSON_PATH,'data/business.json')
        if ERROR_LOG.exists(): z.write(ERROR_LOG,'data/system_errors.jsonl')
    return path

@app.context_processor
def inject_globals():
    b=get_business() or {}; typ=b.get('business_type','marketplace')
    return {'business':b,'business_types':BUSINESS_TYPES,'business_type_labels':BUSINESS_LABELS,'sections':SECTIONS,'type_content':TYPE_CONTENT,'engine_actions':ENGINE_ACTIONS.get(typ,ENGINE_ACTIONS['marketplace']),'active_type':typ}

@app.after_request
def cache_headers(response):
    if request.path.startswith('/static/'): response.headers['Cache-Control']='public,max-age=31536000,immutable'
    else: response.headers['Cache-Control']='no-store'
    return response

@app.route('/')
def index(): return render_template('index.html',business=get_business())

@app.route('/setup',methods=['GET','POST'])
def setup():
    b=get_business()
    if request.method=='POST':
        form=request.form; typ=form.get('business_type','marketplace').strip(); typ=typ if typ in SECTIONS else 'marketplace'
        values=(form.get('name','').strip() or 'Mavuno Market House',typ,form.get('location','').strip(),form.get('phone','').strip(),form.get('whatsapp','').strip(),form.get('email','').strip(),form.get('website','').strip(),form.get('socials','').strip(),form.get('description','').strip(),form.get('logo','M').strip() or 'M',form.get('cover_image','').strip(),form.get('contact_person','').strip(),form.get('till_number','').strip(),form.get('paybill_number','').strip(),form.get('bank_name','').strip(),form.get('bank_account','').strip(),form.get('payment_note','').strip(),now())
        conn=None
        try:
            conn=db(); execute_write(conn,'''UPDATE business SET name=?,business_type=?,location=?,phone=?,whatsapp=?,email=?,website=?,socials=?,description=?,logo=?,cover_image=?,contact_person=?,till_number=?,paybill_number=?,bank_name=?,bank_account=?,payment_note=?,updated_at=? WHERE id=1''',values)
            conn.execute('BEGIN IMMEDIATE'); activity(conn,'Business setup updated',f'{values[0]} · {BUSINESS_LABELS.get(typ,typ)}'); conn.commit(); export_json()
            flash('Business profile updated and the selected business engine is active.','success'); return redirect(url_for('site_home'))
        except Exception as exc:
            if conn:
                try: conn.rollback()
                except Exception: pass
            log_system_error(exc,'/setup'); flash('Setup could not be saved. The error has been recorded under System Errors.','error')
        finally:
            if conn:
                try: conn.close()
                except Exception: pass
    return render_template('setup.html',business=b)

@app.route('/site')
def site_home():
    b=get_business(); typ=b.get('business_type','marketplace'); listings=get_listings(typ=typ); headline,sub=TYPE_CONTENT.get(typ,TYPE_CONTENT['marketplace'])
    return render_template('site_home.html',typ=typ,listings=listings[:12],categories=SECTIONS.get(typ,[]),headline=headline,sub=sub)

@app.route('/browse')
def browse():
    typ=request.args.get('type') or get_business().get('business_type','marketplace'); q=request.args.get('q','').strip(); category=request.args.get('category','').strip(); status=request.args.get('status','').strip()
    listings=get_listings(typ=typ,q=q,category=category or None,status=status or None)
    return render_template('browse.html',listings=listings,typ=typ,q=q,category=category,status=status,categories=SECTIONS.get(typ,[]))

@app.route('/listing/<int:listing_id>')
def listing_detail(listing_id):
    item=get_listing(listing_id)
    if not item: abort(404)
    rooms=get_rooms(listing_id if item['type']=='hotels' else None) if item['type']=='hotels' else []
    return render_template('listing_detail.html',item=item,rooms=rooms,actions=ENGINE_ACTIONS.get(item['type'],ENGINE_ACTIONS['marketplace']))

@app.route('/action/<int:listing_id>',methods=['POST'])
def listing_action(listing_id):
    item=get_listing(listing_id)
    if not item: abort(404)
    form=request.form; action=form.get('operation_type','INQUIRY'); allowed={x[0] for x in ENGINE_ACTIONS.get(item['type'],ENGINE_ACTIONS['marketplace'])}
    if action not in allowed: action='INQUIRY'
    payload={k:v.strip() for k,v in form.items() if k not in ('operation_type',)}
    name=payload.get('name','Website visitor'); phone=payload.get('phone',''); email=payload.get('email','')
    conn=None
    try:
        conn=db();
        cur=execute_write(conn,'INSERT INTO operations(listing_id,business_type,operation_type,customer_name,phone,email,payload_json,status,created_at) VALUES (?,?,?,?,?,?,?,?,?)',(listing_id,item['type'],action,name,phone,email,json.dumps(payload), 'PENDING',now()))
        conn.execute('BEGIN IMMEDIATE'); activity(conn,action.replace('_',' ').title(),f'{item["title"]} · {name}'); conn.commit(); export_json()
        return render_template('operation_received.html',item=item,operation=action,reference=f'MB-{cur.lastrowid:05d}')
    except Exception as exc:
        if conn:
            try: conn.rollback()
            except Exception: pass
        log_system_error(exc,request.path); flash('Your request could not be recorded.','error'); return redirect(url_for('listing_detail',listing_id=listing_id))
    finally:
        if conn:
            try: conn.close()
            except Exception: pass

@app.route('/hotel/book/<int:listing_id>',methods=['POST'])
def hotel_book(listing_id):
    item=get_listing(listing_id)
    if not item or item['type']!='hotels': abort(404)
    room=form=request.form; room_no=form.get('room_number','')
    conn=db(); roomrow=conn.execute('SELECT * FROM hotel_rooms WHERE listing_id=? AND room_number=?',(listing_id,room_no)).fetchone(); conn.close()
    if not roomrow: flash('Choose a real available room number.','error'); return redirect(url_for('listing_detail',listing_id=listing_id))
    data={'room_number':room_no,'check_in':form.get('check_in',''),'check_out':form.get('check_out',''),'guests':form.get('guests','1'),'services':form.get('services',''),'special_request':form.get('special_request','')}
    with app.test_request_context(): pass
    # Reuse the operation endpoint through direct DB write.
    conn=None
    try:
        conn=db(); cur=execute_write(conn,'INSERT INTO operations(listing_id,business_type,operation_type,customer_name,phone,email,payload_json,status,created_at) VALUES (?,?,?,?,?,?,?,?,?)',(listing_id,'hotels','BOOKING',form.get('name','Guest'),form.get('phone',''),form.get('email',''),json.dumps(data),'PENDING',now()));
        conn.execute('BEGIN IMMEDIATE'); activity(conn,'Room booking requested',f'{item["title"]} · Room {room_no} · {form.get("name","Guest")}'); conn.commit(); export_json()
        return render_template('operation_received.html',item=item,operation='BOOKING',reference=f'BOOK-{cur.lastrowid:05d}')
    except Exception as exc:
        if conn:
            try: conn.rollback()
            except Exception: pass
        log_system_error(exc,'/hotel/book'); flash('The room booking could not be recorded.','error'); return redirect(url_for('listing_detail',listing_id=listing_id))
    finally:
        if conn:
            try: conn.close()
            except Exception: pass

@app.route('/sell',methods=['GET','POST'])
def sell():
    if request.method=='POST':
        fields={k:v.strip() for k,v in request.form.items()}; typ=get_business().get('business_type','marketplace')
        conn=None
        try:
            conn=db(); cur=execute_write(conn,'INSERT INTO seller_submissions(name,phone,whatsapp,listing_type,title,payload_json,status,created_at) VALUES (?,?,?,?,?,?,?,?)',(fields.get('name',''),fields.get('phone',''),fields.get('whatsapp',''),fields.get('listing_type',typ),fields.get('title',''),json.dumps(fields),'PENDING',now())); conn.execute('BEGIN IMMEDIATE'); activity(conn,'New seller submission',f'{fields.get("title","Untitled listing")} · {fields.get("name","")}'); conn.commit(); export_json(); return render_template('submission_received.html',reference=f'SELL-{cur.lastrowid:05d}')
        except Exception as exc:
            if conn:
                try: conn.rollback()
                except Exception: pass
            log_system_error(exc,'/sell'); flash('Seller submission could not be recorded.','error'); return redirect(url_for('sell'))
        finally:
            if conn:
                try: conn.close()
                except Exception: pass
    return render_template('sell.html',typ=get_business().get('business_type','marketplace'))

@app.route('/contact',methods=['GET','POST'])
def contact():
    if request.method=='POST':
        form=request.form; conn=None
        try:
            conn=db(); execute_write(conn,'INSERT INTO enquiries(name,phone,email,message,kind,created_at) VALUES (?,?,?,?,?,?)',(form.get('name',''),form.get('phone',''),form.get('email',''),form.get('message',''),'contact',now())); conn.execute('BEGIN IMMEDIATE'); activity(conn,'New enquiry',form.get('name','Visitor')); conn.commit(); export_json(); flash('Message received. The customer desk can follow up from the admin portal.','success')
        except Exception as exc:
            if conn:
                try: conn.rollback()
                except Exception: pass
            log_system_error(exc,'/contact'); flash('Message could not be recorded.','error')
        finally:
            if conn:
                try: conn.close()
                except Exception: pass
    return render_template('contact.html')

@app.route('/scan')
def scan_qr():
    return render_template('scan.html')

@app.route('/qr')
def qr_home():
    conn=db(); rows=[dict(x) for x in conn.execute('SELECT q.*,l.title FROM qr_codes q LEFT JOIN listings l ON l.id=q.listing_id ORDER BY q.id DESC').fetchall()]; listings=[dict(x) for x in conn.execute('SELECT id,title FROM listings ORDER BY id DESC').fetchall()]; conn.close(); return render_template('qr.html',qrs=rows,listings=listings)

@app.route('/qr/generate',methods=['POST'])
def qr_generate():
    listing_id=request.form.get('listing_id') or None; code='MB-'+datetime.now().strftime('%y%m%d%H%M%S')+'-'+os.urandom(2).hex().upper(); conn=None
    try:
        conn=db(); execute_write(conn,'INSERT INTO qr_codes(code,listing_id,scan_count,created_at) VALUES (?,?,0,?)',(code,listing_id,now())); conn.execute('BEGIN IMMEDIATE'); activity(conn,'QR generated',code); conn.commit(); export_json(); flash('QR generated. Put it on the physical item, room, vehicle or display.','success')
    except Exception as exc:
        if conn:
            try: conn.rollback()
            except Exception: pass
        log_system_error(exc,'/qr/generate'); flash('QR could not be generated.','error')
    finally:
        if conn:
            try: conn.close()
            except Exception: pass
    return redirect(url_for('qr_home'))

@app.route('/qr/<code>.png')
def qr_png(code):
    conn=db(); row=conn.execute('SELECT listing_id FROM qr_codes WHERE code=?',(code,)).fetchone(); conn.close();
    if not row: abort(404)
    target=url_for('qr_redirect',code=code,_external=True); img=qrcode.make(target); bio=io.BytesIO(); img.save(bio,format='PNG'); bio.seek(0); return send_file(bio,mimetype='image/png',download_name=f'{code}.png')

@app.route('/qr/<code>')
def qr_redirect(code):
    conn=db(); row=conn.execute('SELECT listing_id FROM qr_codes WHERE code=?',(code,)).fetchone()
    if not row: conn.close(); abort(404)
    conn.execute('UPDATE qr_codes SET scan_count=scan_count+1 WHERE code=?',(code,)); activity(conn,'QR scanned',code); conn.commit(); lid=row['listing_id']; conn.close()
    if not lid: return redirect(url_for('site_home'))
    return redirect(url_for('listing_detail',listing_id=lid))

@app.route('/admin')
def admin():
    b=get_business(); typ=b.get('business_type','marketplace'); conn=db(); metrics={
        'listings':conn.execute('SELECT COUNT(*) n FROM listings WHERE type=?',(typ,)).fetchone()['n'],
        'available':conn.execute("SELECT COUNT(*) n FROM listings WHERE type=? AND status='AVAILABLE'",(typ,)).fetchone()['n'],
        'sold':conn.execute("SELECT COUNT(*) n FROM listings WHERE type=? AND status='SOLD'",(typ,)).fetchone()['n'],
        'pending':conn.execute('SELECT COUNT(*) n FROM seller_submissions WHERE status=\'PENDING\'').fetchone()['n'],
        'operations':conn.execute('SELECT COUNT(*) n FROM operations WHERE business_type=?',(typ,)).fetchone()['n'],
        'qrs':conn.execute('SELECT COALESCE(SUM(scan_count),0) n FROM qr_codes q LEFT JOIN listings l ON l.id=q.listing_id WHERE l.type=?',(typ,)).fetchone()['n'],
        'enquiries':conn.execute('SELECT COUNT(*) n FROM enquiries').fetchone()['n'],
        'rooms':conn.execute("SELECT COUNT(*) n FROM hotel_rooms WHERE status='AVAILABLE'").fetchone()['n'],
    }
    activity_rows=[dict(x) for x in conn.execute('SELECT * FROM activity ORDER BY id DESC LIMIT 10').fetchall()]; submissions=[dict(x) for x in conn.execute('SELECT * FROM seller_submissions ORDER BY id DESC LIMIT 8').fetchall()]; admins=[dict(x) for x in conn.execute('SELECT * FROM admin_users ORDER BY id').fetchall()]; conn.close()
    return render_template('admin.html',metrics=metrics,activity=activity_rows,submissions=submissions,admins=admins,engine=typ)

@app.route('/admin/operations')
def admin_operations():
    typ=get_business().get('business_type','marketplace'); conn=db(); rows=[dict(x) for x in conn.execute('SELECT o.*,l.title listing_title FROM operations o LEFT JOIN listings l ON l.id=o.listing_id WHERE o.business_type=? ORDER BY o.id DESC',(typ,)).fetchall()]; conn.close(); return render_template('admin_operations.html',operations=rows,engine=typ)

@app.route('/admin/rooms')
def admin_rooms():
    conn=db(); rooms=[dict(x) for x in conn.execute('SELECT r.*,l.title listing_title FROM hotel_rooms r LEFT JOIN listings l ON l.id=r.listing_id ORDER BY r.room_number').fetchall()]; conn.close(); return render_template('admin_rooms.html',rooms=rooms)

@app.route('/admin/room/<int:room_id>',methods=['POST'])
def admin_room(room_id):
    status=request.form.get('status','AVAILABLE'); status=status if status in ('AVAILABLE','OCCUPIED','MAINTENANCE','HELD') else 'AVAILABLE'; conn=None
    try:
        conn=db(); execute_write(conn,'UPDATE hotel_rooms SET status=? WHERE id=?',(status,room_id)); conn.execute('BEGIN IMMEDIATE'); activity(conn,'Room status changed',f'Room {room_id} → {status}'); conn.commit(); export_json(); flash('Room status updated.','success')
    except Exception as exc:
        if conn:
            try: conn.rollback()
            except Exception: pass
        log_system_error(exc,'/admin/room'); flash('Room update failed.','error')
    finally:
        if conn:
            try: conn.close()
            except Exception: pass
    return redirect(url_for('admin_rooms'))

@app.route('/admin/listings')
def admin_listings():
    typ=get_business().get('business_type','marketplace'); return render_template('admin_listings.html',listings=get_listings(typ=typ),engine=typ)

@app.route('/admin/listing/add',methods=['GET','POST'])
def admin_listing_add():
    typ=get_business().get('business_type','marketplace')
    if request.method=='POST':
        f=request.form; conn=None
        try:
            details={k:f.get(k,'') for k in ['make','model','year','mileage','fuel','transmission','engine','room_type','amenities','service'] if f.get(k)}
            conn=db(); execute_write(conn,'INSERT INTO listings(type,category,title,price,location,condition,status,featured,image,gallery,details_json,seller_name,seller_phone,seller_whatsapp,description,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(typ,f.get('category','General'),f.get('title','Untitled'),f.get('price','Contact us'),f.get('location',get_business().get('location','')),f.get('condition','NEW'),f.get('status','AVAILABLE'),1 if f.get('featured') else 0,f.get('image','https://images.unsplash.com/photo-1492144534655-ae79c964c9d7?auto=format&fit=crop&w=1200&q=85'),json.dumps([]),json.dumps(details),f.get('seller_name',get_business().get('name','Business')),f.get('seller_phone',get_business().get('phone','')),f.get('seller_whatsapp',get_business().get('whatsapp','')),f.get('description',''),now())); conn.execute('BEGIN IMMEDIATE'); activity(conn,'Listing added',f.get('title','Untitled')); conn.commit(); export_json(); flash('Listing added to the active business engine.','success'); return redirect(url_for('admin_listings'))
        except Exception as exc:
            if conn:
                try: conn.rollback()
                except Exception: pass
            log_system_error(exc,'/admin/listing/add'); flash('Listing could not be saved.','error')
        finally:
            if conn:
                try: conn.close()
                except Exception: pass
    return render_template('admin_listing_add.html',engine=typ,categories=SECTIONS.get(typ,[]))

@app.route('/admin/listing/<int:listing_id>/edit',methods=['GET','POST'])
def admin_listing_edit(listing_id):
    item=get_listing(listing_id)
    if not item: abort(404)
    if request.method=='POST':
        f=request.form; details=item.get('details',{});
        for key in ['make','model','year','mileage','fuel','transmission','engine','room_type','amenities','service']:
            if f.get(key): details[key]=f.get(key)
        conn=None
        try:
            conn=db(); execute_write(conn,'UPDATE listings SET category=?,title=?,price=?,location=?,condition=?,status=?,featured=?,image=?,details_json=?,seller_name=?,seller_phone=?,seller_whatsapp=?,description=? WHERE id=?',(f.get('category',item['category']),f.get('title',item['title']),f.get('price',item['price']),f.get('location',item['location']),f.get('condition',item['condition']),f.get('status',item['status']),1 if f.get('featured') else 0,f.get('image',item['image']),json.dumps(details),f.get('seller_name',item['seller_name']),f.get('seller_phone',item['seller_phone']),f.get('seller_whatsapp',item['seller_whatsapp']),f.get('description',item['description']),listing_id)); conn.execute('BEGIN IMMEDIATE'); activity(conn,'Listing edited',f.get('title',item['title'])); conn.commit(); export_json(); flash('Listing updated live.','success'); return redirect(url_for('admin_listings'))
        except Exception as exc:
            if conn:
                try: conn.rollback()
                except Exception: pass
            log_system_error(exc,request.path); flash('Listing could not be updated.','error')
        finally:
            if conn:
                try: conn.close()
                except Exception: pass
    return render_template('admin_listing_edit.html',item=item,categories=SECTIONS.get(item['type'],[]),engine=item['type'])

@app.route('/admin/submission/<int:sid>/<action>',methods=['POST'])
def submission_action(sid,action):
    conn=None
    try:
        conn=db(); row=conn.execute('SELECT * FROM seller_submissions WHERE id=?',(sid,)).fetchone()
        if not row: return redirect(url_for('admin'))
        status='APPROVED' if action=='approve' else 'REJECTED'
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('UPDATE seller_submissions SET status=? WHERE id=?',(status,sid))
        if action=='approve':
            payload=json.loads(row['payload_json'] or '{}')
            conn.execute('INSERT INTO listings(type,category,title,price,location,condition,status,featured,image,gallery,details_json,seller_name,seller_phone,seller_whatsapp,description,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(row['listing_type'] or get_business().get('business_type','marketplace'),payload.get('category','General'),row['title'] or 'Seller listing',payload.get('price','Contact seller'),payload.get('location',get_business().get('location','')),payload.get('condition','PRE-OWNED'),'AVAILABLE',0,payload.get('image') or 'https://images.unsplash.com/photo-1492144534655-ae79c964c9d7?auto=format&fit=crop&w=1200&q=85',json.dumps([]),json.dumps(payload),row['name'],row['phone'],row['whatsapp'],payload.get('description','Submitted by seller.'),now()))
        activity(conn,'Seller submission '+status.lower(),row['title'] or 'Untitled listing')
        conn.commit(); export_json(); flash('Seller submission processed. Approved submissions are now live listings.','success')
    except Exception as exc:
        if conn:
            try: conn.rollback()
            except Exception: pass
        log_system_error(exc,request.path); flash('Seller submission could not be processed.','error')
    finally:
        if conn:
            try: conn.close()
            except Exception: pass
    return redirect(url_for('admin'))

@app.route('/admin/backup')
def admin_backup(): return render_template('backup.html')
@app.route('/admin/backup/create',methods=['POST'])
def create_backup():
    path=make_backup()
    return send_file(path,as_attachment=True,download_name=path.name)
@app.route('/admin/export.json')
def export_file(): export_json(); return send_file(JSON_PATH,as_attachment=True,download_name='multibusiness_business.json',mimetype='application/json')

@app.route('/admin/restore',methods=['POST'])
def restore():
    uploaded=request.files.get('backup')
    if not uploaded or not uploaded.filename:
        flash('Choose a JSON backup file to restore.','error'); return redirect(url_for('admin_backup'))
    conn=None
    try:
        payload=json.loads(uploaded.read().decode('utf-8'))
        business=(payload.get('business') or [{}])[0] if isinstance(payload.get('business'),list) else payload.get('business')
        if not business: raise ValueError('Backup has no business profile')
        typ=business.get('business_type','marketplace'); typ=typ if typ in SECTIONS else 'marketplace'
        conn=db(); conn.execute('BEGIN IMMEDIATE')
        conn.execute('UPDATE business SET name=?,business_type=?,location=?,phone=?,whatsapp=?,email=?,website=?,socials=?,description=?,logo=?,cover_image=?,contact_person=?,till_number=?,paybill_number=?,bank_name=?,bank_account=?,payment_note=?,updated_at=? WHERE id=1',(business.get('name','Mavuno Market House'),typ,business.get('location',''),business.get('phone',''),business.get('whatsapp',''),business.get('email',''),business.get('website',''),business.get('socials',''),business.get('description',''),business.get('logo','M'),business.get('cover_image',''),business.get('contact_person',''),business.get('till_number',''),business.get('paybill_number',''),business.get('bank_name',''),business.get('bank_account',''),business.get('payment_note',''),now()))
        # Replace operational collections present in the export.
        for table in ('hotel_rooms','operations','qr_codes','seller_submissions','enquiries','listings','admin_users'):
            if table in payload:
                conn.execute(f'DELETE FROM {table}')
        for row in payload.get('listings',[]):
            keys=['id','type','category','title','price','location','condition','status','featured','image','gallery','details_json','seller_name','seller_phone','seller_whatsapp','description','created_at']
            vals=[row.get(k) for k in keys]
            conn.execute('INSERT INTO listings(id,type,category,title,price,location,condition,status,featured,image,gallery,details_json,seller_name,seller_phone,seller_whatsapp,description,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',vals)
        for row in payload.get('hotel_rooms',[]):
            conn.execute('INSERT INTO hotel_rooms(id,listing_id,room_number,room_type,status,price,amenities) VALUES (?,?,?,?,?,?,?)',(row.get('id'),row.get('listing_id'),row.get('room_number'),row.get('room_type'),row.get('status','AVAILABLE'),row.get('price'),row.get('amenities')))
        for row in payload.get('operations',[]):
            conn.execute('INSERT INTO operations(id,listing_id,business_type,operation_type,customer_name,phone,email,payload_json,status,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)',(row.get('id'),row.get('listing_id'),row.get('business_type'),row.get('operation_type'),row.get('customer_name'),row.get('phone'),row.get('email'),row.get('payload_json','{}'),row.get('status','PENDING'),row.get('created_at',now())))
        for row in payload.get('qr_codes',[]):
            conn.execute('INSERT INTO qr_codes(id,code,listing_id,scan_count,created_at) VALUES (?,?,?,?,?)',(row.get('id'),row.get('code'),row.get('listing_id'),row.get('scan_count',0),row.get('created_at',now())))
        for row in payload.get('seller_submissions',[]):
            conn.execute('INSERT INTO seller_submissions(id,name,phone,whatsapp,listing_type,title,payload_json,status,created_at) VALUES (?,?,?,?,?,?,?,?,?)',(row.get('id'),row.get('name'),row.get('phone'),row.get('whatsapp'),row.get('listing_type'),row.get('title'),row.get('payload_json','{}'),row.get('status','PENDING'),row.get('created_at',now())))
        for row in payload.get('enquiries',[]):
            conn.execute('INSERT INTO enquiries(id,listing_id,name,phone,email,message,kind,created_at) VALUES (?,?,?,?,?,?,?,?)',(row.get('id'),row.get('listing_id'),row.get('name'),row.get('phone'),row.get('email'),row.get('message'),row.get('kind','enquiry'),row.get('created_at',now())))
        for row in payload.get('admin_users',[]):
            conn.execute('INSERT INTO admin_users(id,name,role,phone,email,status) VALUES (?,?,?,?,?,?)',(row.get('id'),row.get('name'),row.get('role'),row.get('phone'),row.get('email'),row.get('status','ACTIVE')))
        activity(conn,'Full restore','Business profile and operational data restored from JSON')
        conn.commit(); export_json(); flash('Full business data restored successfully.','success')
    except Exception as exc:
        if conn:
            try: conn.rollback()
            except Exception: pass
        log_system_error(exc,'/admin/restore'); flash('Restore failed. See System Errors for the recorded exception.','error')
    finally:
        if conn:
            try: conn.close()
            except Exception: pass
    return redirect(url_for('admin_backup'))

@app.route('/admin/errors')
def admin_errors(): return render_template('system_errors.html',errors=read_system_errors(100))
@app.route('/admin/team')
def admin_team():
    conn=db(); users=[dict(x) for x in conn.execute('SELECT * FROM admin_users ORDER BY id').fetchall()]; conn.close(); return render_template('admin_team.html',admins=users)
@app.route('/admin/team/add',methods=['POST'])
def admin_team_add():
    f=request.form; conn=None
    try:
        conn=db(); execute_write(conn,'INSERT INTO admin_users(name,role,phone,email,status) VALUES (?,?,?,?,?)',(f.get('name',''),f.get('role','Business Admin'),f.get('phone',''),f.get('email',''),'ACTIVE')); conn.execute('BEGIN IMMEDIATE'); activity(conn,'Admin added',f.get('name','')); conn.commit(); export_json(); flash('Business team member added.','success')
    except Exception as exc: log_system_error(exc,request.path); flash('Team member could not be added.','error')
    finally:
        if conn:
            try: conn.close()
            except Exception: pass
    return redirect(url_for('admin_team'))

@app.route('/health')
def health(): return jsonify({'status':'ok','app':'MultiBusiness v1','version':'2.0','time':now()})
@app.route('/favicon.ico')
def favicon(): return ('',204)

@app.errorhandler(404)
def not_found(e):
    if request.path.startswith('/static/'): return ('',404)
    return render_template('error.html',code=404,message='The page you are looking for is not available.'),404
@app.errorhandler(500)
def internal_error(e):
    log_system_error(e,request.path); return render_template('error.html',code=500,message='Something went wrong. The administrator can review System Errors.'),500

init_db()
if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.environ.get('PORT',5000)),debug=True)
