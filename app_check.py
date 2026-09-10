from __future__ import annotations

import io
import json
import os
import sqlite3
import time
import zipfile
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Any

from flask import Flask, abort, flash, g, redirect, render_template, request, send_file, session, url_for
try:
    import qrcode
except ImportError:
    qrcode = None

BASE = Path(__file__).resolve().parent
DATA = BASE / 'data'
DATA.mkdir(exist_ok=True)
DB_PATH = DATA / 'business.db'
BACKUPS = DATA / 'backups'
BACKUPS.mkdir(exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'multibusiness-ground-v1-change-me')
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
app.config['TEMPLATES_AUTO_RELOAD'] = True


VEHICLE_TYPES = [
    'City Car','Sedan','Compact Sedan','Executive Sedan','Luxury Sedan','Hatchback','Hot Hatch','Coupe','Sports Coupe','Convertible','Roadster','Grand Tourer','Supercar','Hypercar','Wagon / Estate','Crossover','Compact SUV','Mid-size SUV','Full-size SUV','Luxury SUV','Off-road SUV','7-Seater SUV','Pickup','Single Cab Pickup','Double Cab Pickup','Crew Cab Pickup','Light-Duty Pickup','Heavy-Duty Pickup','Chassis Cab','Flatbed Truck','Box Truck','Tipper Truck','Dump Truck','Tow Truck','Recovery Truck','Car Carrier','Container Truck','Refrigerated Truck','Fuel Tanker','Water Tanker','Chemical Tanker','Curtainsider Truck','Crane Truck','Mixer Truck','Garbage Truck','Fire Truck','Ambulance','Police Vehicle','Armoured Vehicle','Panel Van','Cargo Van','Mini Van','Passenger Van','Luxury Van','Minibus','School Bus','City Bus','Coach Bus','Tour Bus','Shuttle Bus','Articulated Bus','Electric Bus','Tractor Unit','Semi Trailer','Low Loader','Flatbed Trailer','Car Trailer','Utility Trailer','Motorcycle','Scooter','Moped','Adventure Motorcycle','Cruiser Motorcycle','Sport Motorcycle','Touring Motorcycle','Off-road Motorcycle','Dirt Bike','Enduro','ATV / Quad Bike','UTV / Side-by-Side','Tricycle','Tuk-tuk','Electric Vehicle','Electric Scooter','Golf Cart','Forklift','Telehandler','Tractor','Agricultural Machinery','Construction Vehicle','Mining Vehicle','Airport Ground Vehicle','Special Purpose Vehicle','Other Vehicle'
]
HOTEL_TYPES = [
    'Standard Room','Superior Room','Deluxe Room','Executive Room','Premium Room','Classic Room','Business Room','King Room','Queen Room','Twin Room','Double Room','Single Room','Triple Room','Family Room','Connecting Room','Accessible Room','Pool View Room','Garden View Room','City View Room','Ocean View Room','Mountain View Room','River View Room','Courtyard Room','Club Room','Club King Room','Club Twin Room','Studio Room','Junior Suite','Executive Suite','Premium Suite','Deluxe Suite','Presidential Suite','Royal Suite','Honeymoon Suite','Family Suite','Two-Bedroom Suite','Three-Bedroom Suite','Penthouse Suite','Apartment Suite','Serviced Apartment','Studio Apartment','One-Bedroom Apartment','Two-Bedroom Apartment','Three-Bedroom Apartment','Four-Bedroom Apartment','Villa','Pool Villa','Beach Villa','Garden Villa','Family Villa','Private Villa','Presidential Villa','Cottage','Luxury Cottage','Chalet','Lodge Room','Cabin','Safari Tent','Glamping Tent','Treehouse','Bungalow','Beach Bungalow','Overwater Bungalow','Guest House Room','Hostel Private Room','Dormitory Bed','Meeting Room','Boardroom','Conference Hall','Ballroom','Wedding Venue','Banquet Hall','Restaurant Venue','Rooftop Venue','Poolside Venue','Spa Suite','Day Use Room','Long Stay Room','Corporate Room','Transit Room','Staff Accommodation','Other Accommodation'
]
PROPERTY_TYPES = [
    'Residential House','Detached House','Semi-Detached House','Townhouse','Terraced House','Bungalow','Maisonette','Mansion','Villa','Luxury Villa','Gated Community Home','Apartment','Studio Apartment','Bedsitter','One-Bedroom Apartment','Two-Bedroom Apartment','Three-Bedroom Apartment','Four-Bedroom Apartment','Penthouse','Duplex','Serviced Apartment','Furnished Apartment','Student Apartment','Off-plan Apartment','Commercial Property','Office','Office Suite','Co-working Space','Retail Shop','Shop Space','Shopping Centre Unit','Showroom','Warehouse','Godown','Industrial Building','Factory','Workshop','Business Park','Hotel Property','Restaurant Property','Bar Property','School Property','Hospital Property','Church Property','Institutional Property','Medical Centre','Clinic Space','Salon Space','Gym Property','Event Venue','Conference Venue','Land','Residential Land','Commercial Land','Industrial Land','Agricultural Land','Beach Plot','Ranch','Farm','Plantation','Development Plot','Mixed-Use Plot','Roadside Plot','Corner Plot','Gated Estate Plot','Apartment Development Site','Office Building','Retail Building','Mixed-Use Building','Multi-Unit Property','Block of Flats','Apartment Block','Student Housing','Hostel','Serviced Residence','Guest House','Lodge','Resort Property','Beach House','Beachfront Property','Waterfront Property','Mountain Property','Rural Property','Urban Property','Investment Property','Income Property','Short-Term Rental','Long-Term Rental','Leasehold Property','Freehold Property','Foreclosure Property','Auction Property','Other Property'
]
TYPE_CATALOGS = {'vehicles': VEHICLE_TYPES, 'hotels': HOTEL_TYPES, 'property': PROPERTY_TYPES}

BUSINESS_TYPES = {
    'vehicles': {
        'name': 'Vehicles',
        'slug': 'vehicles',
        'tagline': 'Buy, sell, inspect and manage vehicles.',
        'accent': '#8b1e2d',
        'actions': ['Inventory', 'Customer enquiries', 'Viewing requests', 'Sales'],
    },
    'hotels': {
        'name': 'Hotels & Lodges',
        'slug': 'hotels',
        'tagline': 'Rooms, stays, bookings and guest service.',
        'accent': '#8b1e2d',
        'actions': ['Rooms', 'Bookings', 'Guests', 'Services'],
    },
    'property': {
        'name': 'Real Estate & Property',
        'slug': 'property',
        'tagline': 'Property discovery, viewings, offers and management.',
        'accent': '#8b1e2d',
        'actions': ['Listings', 'Viewings', 'Offers', 'Enquiries'],
    },
}


def now() -> str:
    return datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')


def get_db():
    if 'db' not in g:
        conn = sqlite3.connect(DB_PATH, timeout=12)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA busy_timeout=10000')
        conn.execute('PRAGMA journal_mode=WAL')
        g.db = conn
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def exec_retry(sql: str, params=(), *, commit=False, attempts=6):
    last = None
    for n in range(attempts):
        try:
            db = get_db()
            cur = db.execute(sql, params)
            if commit:
                db.commit()
            return cur
        except sqlite3.OperationalError as exc:
            last = exc
            if 'locked' not in str(exc).lower() or n == attempts - 1:
                raise
            time.sleep(0.18 * (n + 1))
    raise last


def business():
    row = get_db().execute('SELECT * FROM business WHERE id=1').fetchone()
    return row


def selected():
    return business()['business_type'] if business() else None


def authority_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not selected():
            return redirect(url_for('start'))
        if not session.get('authority'):
            return redirect(url_for('authority_login'))
        return fn(*args, **kwargs)
    return wrapper


def ensure_db():
    db = get_db()
    db.executescript('''
    CREATE TABLE IF NOT EXISTS business (
        id INTEGER PRIMARY KEY CHECK(id=1),
        name TEXT NOT NULL DEFAULT '', business_type TEXT, description TEXT DEFAULT '',
        location TEXT DEFAULT '', phone TEXT DEFAULT '', whatsapp TEXT DEFAULT '',
        email TEXT DEFAULT '', website TEXT DEFAULT '', logo TEXT DEFAULT 'M',
        cover_image TEXT DEFAULT '', payment_destination TEXT DEFAULT '',
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS activity (
        id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT NOT NULL, detail TEXT DEFAULT '', created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS vehicles (
        id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, category TEXT DEFAULT '', make TEXT DEFAULT '', model TEXT DEFAULT '',
        year TEXT DEFAULT '', mileage TEXT DEFAULT '', price TEXT DEFAULT '', condition TEXT DEFAULT '',
        location TEXT DEFAULT '', description TEXT DEFAULT '', image TEXT DEFAULT '', status TEXT DEFAULT 'AVAILABLE',
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS rooms (
        id INTEGER PRIMARY KEY AUTOINCREMENT, room_number TEXT NOT NULL, room_type TEXT DEFAULT '', category TEXT DEFAULT '',
        price TEXT DEFAULT '', status TEXT DEFAULT 'AVAILABLE', details TEXT DEFAULT '', image TEXT DEFAULT '', created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS bookings (
        id INTEGER PRIMARY KEY AUTOINCREMENT, room_id INTEGER, guest_name TEXT NOT NULL, phone TEXT DEFAULT '',
        check_in TEXT DEFAULT '', check_out TEXT DEFAULT '', status TEXT DEFAULT 'PENDING', note TEXT DEFAULT '', created_at TEXT NOT NULL,
        FOREIGN KEY(room_id) REFERENCES rooms(id) ON DELETE SET NULL
    );
    CREATE TABLE IF NOT EXISTS properties (
        id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, category TEXT DEFAULT '',
        price TEXT DEFAULT '', location TEXT DEFAULT '', description TEXT DEFAULT '', image TEXT DEFAULT '',
        status TEXT DEFAULT 'AVAILABLE', created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS enquiries (
        id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, subject TEXT DEFAULT '', name TEXT NOT NULL,
        phone TEXT DEFAULT '', email TEXT DEFAULT '', message TEXT DEFAULT '', reference_id INTEGER, status TEXT DEFAULT 'NEW',
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS qr_codes (
        id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE NOT NULL, label TEXT DEFAULT '', target_path TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS admins (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, role TEXT DEFAULT 'Authority', username TEXT UNIQUE NOT NULL,
        created_at TEXT NOT NULL
    );
    ''')
    # Lightweight migrations for databases created by earlier ground builds.
    existing_vehicle_cols = {r['name'] for r in db.execute('PRAGMA table_info(vehicles)').fetchall()}
    if 'category' not in existing_vehicle_cols:
        db.execute("ALTER TABLE vehicles ADD COLUMN category TEXT DEFAULT ''")
    existing_room_cols = {r['name'] for r in db.execute('PRAGMA table_info(rooms)').fetchall()}
    if 'category' not in existing_room_cols:
        db.execute("ALTER TABLE rooms ADD COLUMN category TEXT DEFAULT ''")
    if db.execute('SELECT 1 FROM business WHERE id=1').fetchone() is None:
        ts = now()
        db.execute('INSERT INTO business(id,name,created_at,updated_at) VALUES(1,?,?,?)', ('Your Business', ts, ts))
        db.execute('INSERT INTO admins(name,role,username,created_at) VALUES(?,?,?,?)', ('Primary Authority', 'Owner', 'authority', ts))
        db.commit()


def seed_demo_for(kind: str):
    db = get_db()
    if kind == 'vehicles' and db.execute('SELECT COUNT(*) c FROM vehicles').fetchone()['c'] == 0:
        rows = [
            ('2022 Toyota Harrier', 'SUV', 'Toyota', 'Harrier', '2022', '48,500 km', 'KES 5,950,000', 'SECOND HAND', 'Nairobi', 'Clean family SUV with service history.', 'https://images.unsplash.com/photo-1553440569-bcc63803a83d?auto=format&fit=crop&w=1000&q=80'),
            ('2023 Isuzu D-Max', 'Double Cab Pickup', 'Isuzu', 'D-Max', '2023', '31,200 km', 'KES 6,850,000', 'SECOND HAND', 'Mombasa', 'Work-ready pickup with one-owner history.', 'https://images.unsplash.com/photo-1551830820-330a71b99659?auto=format&fit=crop&w=1000&q=80'),
            ('2024 Toyota Hilux', 'Pickup', 'Toyota', 'Hilux', '2024', '8,900 km', 'KES 7,450,000', 'NEAR NEW', 'Nairobi', 'Commercial-grade pickup prepared for immediate delivery.', 'https://images.unsplash.com/photo-1511919884226-fd3cad34687c?auto=format&fit=crop&w=1000&q=80'),
        ]
        db.executemany('INSERT INTO vehicles(title,category,make,model,year,mileage,price,condition,location,description,image,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)', [r + (now(),) for r in rows])
    if kind == 'hotels' and db.execute('SELECT COUNT(*) c FROM rooms').fetchone()['c'] == 0:
        rows = [
            ('101','Deluxe King','Deluxe Room','KES 12,500 / night','AVAILABLE','King bed, breakfast, Wi-Fi, workspace','https://images.unsplash.com/photo-1566665797739-1674de7a421a?auto=format&fit=crop&w=1000&q=80'),
            ('204','Executive Suite','Executive Suite','KES 22,000 / night','AVAILABLE','Separate lounge, balcony, breakfast, airport transfer','https://images.unsplash.com/photo-1566073771259-6a8506099945?auto=format&fit=crop&w=1000&q=80'),
            ('305','Family Room','Family Room','KES 18,500 / night','MAINTENANCE','Two sleeping areas and family services','https://images.unsplash.com/photo-1582719478250-c89cae4dc85b?auto=format&fit=crop&w=1000&q=80'),
        ]
        db.executemany('INSERT INTO rooms(room_number,room_type,category,price,status,details,image,created_at) VALUES(?,?,?,?,?,?,?,?)', [r + (now(),) for r in rows])
    if kind == 'property' and db.execute('SELECT COUNT(*) c FROM properties').fetchone()['c'] == 0:
        rows = [
            ('4 Bedroom Family House','House','KES 28,000,000','Ruiru','Gated family home with parking and garden.','https://images.unsplash.com/photo-1600585154340-be6161a56a0c?auto=format&fit=crop&w=1000&q=80','AVAILABLE'),
            ('Modern Apartment 3BR','Apartment','KES 14,500,000','Kilimani','City apartment with lift, gym and backup power.','https://images.unsplash.com/photo-1505691938895-1758d7feb511?auto=format&fit=crop&w=1000&q=80','AVAILABLE'),
            ('Commercial Plot','Land','KES 32,000,000','Nairobi West','Prime road-front plot for commercial development.','https://images.unsplash.com/photo-1500382017468-9049fed747ef?auto=format&fit=crop&w=1000&q=80','AVAILABLE'),
        ]
        db.executemany('INSERT INTO properties(title,category,price,location,description,image,status,created_at) VALUES(?,?,?,?,?,?,?,?)', [r + (now(),) for r in rows])
    db.commit()


@app.context_processor
def inject():
    b = business()
    kind = b['business_type'] if b else None
    return {'business': b, 'current_kind': kind, 'business_types': BUSINESS_TYPES, 'type_catalog': TYPE_CATALOGS.get(kind, [])}


@app.before_request
def boot():
    ensure_db()
    b = business()
    if b and b['business_type']:
        seed_demo_for(b['business_type'])


@app.after_request
def no_store(response):
    response.headers['Cache-Control'] = 'no-store, max-age=0, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@app.route('/')
def home():
    b = business()
    if not b['business_type']:
        return redirect(url_for('start'))
    return redirect(url_for('public_home'))


@app.route('/start', methods=['GET', 'POST'])
def start():
    if request.method == 'POST':
        kind = request.form.get('business_type', '')
        if kind not in BUSINESS_TYPES:
            flash('Choose one business to enter.', 'error')
            return redirect(url_for('start'))
        # Starting a new world deliberately resets previous business records.
        db = get_db()
        with db:
            db.execute('DELETE FROM vehicles')
            db.execute('DELETE FROM rooms')
            db.execute('DELETE FROM bookings')
            db.execute('DELETE FROM properties')
            db.execute('DELETE FROM enquiries')
            db.execute('DELETE FROM qr_codes')
            db.execute('DELETE FROM activity')
            db.execute('UPDATE business SET name=?, business_type=?, description=?, location=?, phone=?, whatsapp=?, email=?, website=?, logo=?, cover_image=?, payment_destination=?, updated_at=? WHERE id=1',
                        (BUSINESS_TYPES[kind]['name'], kind, BUSINESS_TYPES[kind]['tagline'], '', '', '', '', '', BUSINESS_TYPES[kind]['name'][0], '', '', now()))
            db.execute('INSERT INTO activity(action,detail,created_at) VALUES(?,?,?)', ('Business world selected', BUSINESS_TYPES[kind]['name'], now()))
            db.execute('DELETE FROM admins')
            db.execute('INSERT INTO admins(name,role,username,created_at) VALUES(?,?,?,?)', ('Primary Authority','Owner','authority',now()))
        session.clear()
        return redirect(url_for('setup'))
    # This page is intentionally bare: only the choice and footer.
    return render_template('start.html')


@app.route('/setup', methods=['GET', 'POST'])
def setup():
    b = business()
    if not b['business_type']:
        return redirect(url_for('start'))
    kind = b['business_type']
    if request.method == 'POST':
        form = request.form
        name = form.get('name', '').strip() or BUSINESS_TYPES[kind]['name']
        db = get_db()
        with db:
            db.execute('UPDATE business SET name=?,description=?,location=?,phone=?,whatsapp=?,email=?,website=?,logo=?,cover_image=?,payment_destination=?,updated_at=? WHERE id=1',
                       (name, form.get('description','').strip(), form.get('location','').strip(), form.get('phone','').strip(), form.get('whatsapp','').strip(), form.get('email','').strip(), form.get('website','').strip(), form.get('logo','M').strip()[:2] or 'M', form.get('cover_image','').strip(), form.get('payment_destination','').strip(), now()))
            db.execute('INSERT INTO activity(action,detail,created_at) VALUES(?,?,?)', ('Business setup completed', name, now()))
        return redirect(url_for('public_home'))
    return render_template('setup.html', type_info=BUSINESS_TYPES[kind])


@app.route('/quit')
def quit_business():
    session.clear()
    return redirect(url_for('start'))


@app.route('/site')
def public_home():
    b = business(); kind = b['business_type']
    if not kind: return redirect(url_for('start'))
    if kind == 'vehicles':
        items = get_db().execute("SELECT * FROM vehicles WHERE status!='SOLD' ORDER BY id DESC").fetchall()
    elif kind == 'hotels':
        items = get_db().execute("SELECT * FROM rooms WHERE status!='MAINTENANCE' ORDER BY room_number").fetchall()
    else:
        items = get_db().execute("SELECT * FROM properties ORDER BY id DESC").fetchall()
    return render_template('public_home.html', items=items)


@app.route('/browse')
def browse():
    b = business(); kind = b['business_type']
    if not kind: return redirect(url_for('start'))
    q = request.args.get('q','').strip()
    category = request.args.get('category','').strip()
    if kind == 'vehicles':
        sql = "SELECT * FROM vehicles WHERE (title LIKE ? OR make LIKE ? OR model LIKE ? OR location LIKE ? OR category LIKE ?)"
        params=[f'%{q}%']*4 + [f'%{category}%'] if category else [f'%{q}%']*4 + ['%%']
        sql += ' ORDER BY id DESC'
        items = get_db().execute(sql, params).fetchall()
    elif kind == 'hotels':
        sql = "SELECT * FROM rooms WHERE (room_number LIKE ? OR room_type LIKE ? OR details LIKE ? OR category LIKE ?)"
        params=[f'%{q}%']*3 + [f'%{category}%'] if category else [f'%{q}%']*3 + ['%%']
        sql += ' ORDER BY room_number'
        items=get_db().execute(sql,params).fetchall()
    else:
        sql="SELECT * FROM properties WHERE (title LIKE ? OR category LIKE ? OR location LIKE ?)"; like=f'%{q}%'; sql += ' ORDER BY id DESC'; items=get_db().execute(sql,(like,like,like)).fetchall()
    return render_template('browse.html', items=items, q=q, category=category)


@app.route('/item/<int:item_id>')
def item_detail(item_id):
    kind=selected(); db=get_db()
    if kind=='vehicles': item=db.execute('SELECT * FROM vehicles WHERE id=?',(item_id,)).fetchone()
    elif kind=='hotels': item=db.execute('SELECT * FROM rooms WHERE id=?',(item_id,)).fetchone()
    else: item=db.execute('SELECT * FROM properties WHERE id=?',(item_id,)).fetchone()
    if not item: abort(404)
    return render_template('item_detail.html', item=item)


@app.route('/action/<int:item_id>', methods=['POST'])
def action(item_id):
    kind=selected(); form=request.form; db=get_db()
    name=form.get('name','').strip(); phone=form.get('phone','').strip(); message=form.get('message','').strip()
    if not name:
        flash('Please provide your name.', 'error'); return redirect(url_for('item_detail',item_id=item_id))
    action_name={'vehicles':'Purchase / viewing request','hotels':'Room booking request','property':'Viewing / offer request'}[kind]
    exec_retry('INSERT INTO enquiries(kind,subject,name,phone,email,message,reference_id,status,created_at) VALUES(?,?,?,?,?,?,?,?,?)',
               (action_name, form.get('subject','').strip(), name, phone, form.get('email','').strip(), message, item_id, 'NEW', now()), commit=True)
    flash('Your request has been received. The business can now continue with you directly.', 'success')
    return redirect(url_for('item_detail',item_id=item_id))


@app.route('/qr')
def business_qr():
    b=business();
    if not b['business_type']: return redirect(url_for('start'))
    return render_template('qr.html')


@app.route('/qr/item/<int:item_id>')
def item_qr(item_id):
    if not selected():
        return redirect(url_for('start'))
    kind = selected(); db = get_db()
    table = {'vehicles':'vehicles','hotels':'rooms','property':'properties'}[kind]
    if not db.execute(f'SELECT 1 FROM {table} WHERE id=?',(item_id,)).fetchone():
        abort(404)
    return render_template('qr.html', item_id=item_id, item_target=url_for('item_detail', item_id=item_id))

@app.route('/qr/image')
def qr_image():
    if qrcode is None: abort(503)
    target=request.args.get('target','/site')
    if not target.startswith('/'):
        target='/site'
    full=request.host_url.rstrip('/') + target
    image=qrcode.make(full)
    buf=io.BytesIO(); image.save(buf, format='PNG'); buf.seek(0)
    return send_file(buf,mimetype='image/png',download_name='business-qr.png')


@app.route('/authority/login', methods=['GET','POST'])
def authority_login():
    if not selected(): return redirect(url_for('start'))
    if request.method=='POST':
        username=request.form.get('username','').strip()
        if get_db().execute('SELECT 1 FROM admins WHERE username=?',(username,)).fetchone():
            session['authority']=username
            return redirect(url_for('authority'))
        flash('Use the demo authority username shown on this page.', 'error')
    return render_template('authority_login.html')


@app.route('/authority/logout')
def authority_logout():
    session.pop('authority',None); return redirect(url_for('public_home'))


@app.route('/authority')
@authority_required
def authority():
    kind=selected(); db=get_db(); metrics={}
    if kind=='vehicles':
        metrics={'inventory':db.execute('SELECT COUNT(*) c FROM vehicles').fetchone()['c'],'available':db.execute("SELECT COUNT(*) c FROM vehicles WHERE status='AVAILABLE'").fetchone()['c'],'enquiries':db.execute('SELECT COUNT(*) c FROM enquiries').fetchone()['c']}
        items=db.execute('SELECT * FROM vehicles ORDER BY id DESC').fetchall()
    elif kind=='hotels':
        metrics={'rooms':db.execute('SELECT COUNT(*) c FROM rooms').fetchone()['c'],'available':db.execute("SELECT COUNT(*) c FROM rooms WHERE status='AVAILABLE'").fetchone()['c'],'bookings':db.execute('SELECT COUNT(*) c FROM bookings').fetchone()['c'],'enquiries':db.execute('SELECT COUNT(*) c FROM enquiries').fetchone()['c']}
        items=db.execute('SELECT * FROM rooms ORDER BY room_number').fetchall()
    else:
        metrics={'listings':db.execute('SELECT COUNT(*) c FROM properties').fetchone()['c'],'available':db.execute("SELECT COUNT(*) c FROM properties WHERE status='AVAILABLE'").fetchone()['c'],'enquiries':db.execute('SELECT COUNT(*) c FROM enquiries').fetchone()['c']}
        items=db.execute('SELECT * FROM properties ORDER BY id DESC').fetchall()
    activity=db.execute('SELECT * FROM activity ORDER BY id DESC LIMIT 12').fetchall()
    return render_template('authority.html',metrics=metrics,items=items,activity=activity)


@app.route('/authority/edit/<int:item_id>', methods=['GET','POST'])
@authority_required
def authority_edit(item_id):
    kind=selected(); db=get_db()
    table={'vehicles':'vehicles','hotels':'rooms','property':'properties'}[kind]
    if request.method=='POST':
        f=request.form
        if kind=='vehicles':
            db.execute('UPDATE vehicles SET title=?,category=?,make=?,model=?,year=?,mileage=?,price=?,condition=?,location=?,description=?,image=?,status=? WHERE id=?',(f.get('title'),f.get('category'),f.get('make'),f.get('model'),f.get('year'),f.get('mileage'),f.get('price'),f.get('condition'),f.get('location'),f.get('description'),f.get('image'),f.get('status'),item_id))
        elif kind=='hotels':
            db.execute('UPDATE rooms SET room_number=?,room_type=?,category=?,price=?,status=?,details=?,image=? WHERE id=?',(f.get('room_number'),f.get('room_type'),f.get('category'),f.get('price'),f.get('status'),f.get('details'),f.get('image'),item_id))
        else:
            db.execute('UPDATE properties SET title=?,category=?,price=?,location=?,description=?,image=?,status=? WHERE id=?',(f.get('title'),f.get('category'),f.get('price'),f.get('location'),f.get('description'),f.get('image'),f.get('status'),item_id))
        db.commit(); db.execute('INSERT INTO activity(action,detail,created_at) VALUES(?,?,?)',('Record updated',f.get('title') or f.get('room_number') or f.get('property',''),now())); db.commit(); return redirect(url_for('authority'))
    item=db.execute(f'SELECT * FROM {table} WHERE id=?',(item_id,)).fetchone()
    if not item: abort(404)
    return render_template('authority_edit.html',item=item)


@app.route('/authority/enquiries')
@authority_required
def authority_enquiries():
    return render_template('authority_enquiries.html', enquiries=get_db().execute('SELECT * FROM enquiries ORDER BY id DESC').fetchall())


@app.route('/authority/qr')
@authority_required
def authority_qr():
    b=business(); return render_template('authority_qr.html')


@app.route('/authority/backup', methods=['GET','POST'])
@authority_required
def authority_backup():
    if request.method=='POST':
        db=get_db(); payload={}
        for table in ['business','vehicles','rooms','bookings','properties','enquiries','qr_codes','admins','activity']:
            payload[table]=[dict(r) for r in db.execute(f'SELECT * FROM {table}').fetchall()]
        blob=json.dumps(payload,indent=2).encode()
        path=BACKUPS / f'backup-{datetime.utcnow().strftime("%Y%m%d-%H%M%S")}.json'
        path.write_bytes(blob)
        zpath=BACKUPS / f'backup-{datetime.utcnow().strftime("%Y%m%d-%H%M%S")}.zip'
        with zipfile.ZipFile(zpath,'w',zipfile.ZIP_DEFLATED) as z: z.writestr('business.json',blob)
        flash('Backup created.', 'success'); return redirect(url_for('authority_backup'))
    files=sorted(BACKUPS.glob('*'),reverse=True)
    return render_template('authority_backup.html',files=files)


@app.route('/backup/download/<path:name>')
@authority_required
def backup_download(name):
    p=(BACKUPS/name).resolve()
    if not str(p).startswith(str(BACKUPS.resolve())) or not p.exists(): abort(404)
    return send_file(p,as_attachment=True)


@app.errorhandler(404)
def not_found(_):
    if request.path.startswith('/authority') and not selected(): return redirect(url_for('start'))
    return render_template('error.html',code=404,message='That page is not available inside this business.'),404


@app.errorhandler(500)
def server_error(_):
    # Keep technical traces away from public users. The System record remains intentionally silent in v1.
    try:
        exec_retry('INSERT INTO activity(action,detail,created_at) VALUES(?,?,?)', ('System error','An internal operation failed. Check server logs.',now()), commit=True)
    except Exception:
        pass
    return render_template('error.html',code=500,message='Something went wrong. Please try again.'),500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT',5000)), debug=False)
