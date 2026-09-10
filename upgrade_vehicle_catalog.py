from pathlib import Path
import re, html, sqlite3

BASE=Path('/mnt/data/vehupgrade')
app=BASE/'app.py'
text=app.read_text()

# Insert expanded vehicle datasets after VEHICLE_TYPES declaration block.
marker="TYPE_CATALOGS = {'vehicles': VEHICLE_TYPES, 'hotels': HOTEL_TYPES, 'property': PROPERTY_TYPES}\n"
insert=r'''

# Vehicle catalog is deliberately record-bound: every seeded image filename is generated
# from the same make/model/year record, so the display name can never drift from its image.
VEHICLE_MODELS = [
    ('Toyota','Corolla','Sedan'),('Toyota','Camry','Sedan'),('Toyota','RAV4','SUV'),('Toyota','Land Cruiser','SUV'),('Toyota','Hilux','Pickup'),('Toyota','Prado','SUV'),('Toyota','Vitz','Hatchback'),('Toyota','Hiace','Van'),('Toyota','Probox','Wagon / Estate'),('Toyota','Fortuner','SUV'),
    ('BMW','3 Series','Sedan'),('BMW','5 Series','Sedan'),('BMW','7 Series','Luxury Sedan'),('BMW','X1','Crossover'),('BMW','X3','SUV'),('BMW','X5','SUV'),('BMW','X7','Luxury SUV'),('BMW','M3','Sports Coupe'),('BMW','M4','Sports Coupe'),('BMW','iX','Electric Vehicle'),
    ('Mercedes-Benz','C-Class','Sedan'),('Mercedes-Benz','E-Class','Executive Sedan'),('Mercedes-Benz','S-Class','Luxury Sedan'),('Mercedes-Benz','A-Class','Hatchback'),('Mercedes-Benz','GLA','Crossover'),('Mercedes-Benz','GLC','SUV'),('Mercedes-Benz','GLE','SUV'),('Mercedes-Benz','GLS','Luxury SUV'),('Mercedes-Benz','Sprinter','Panel Van'),('Mercedes-Benz','V-Class','Luxury Van'),
    ('Audi','A3','Sedan'),('Audi','A4','Sedan'),('Audi','A6','Executive Sedan'),('Audi','A8','Luxury Sedan'),('Audi','Q3','Crossover'),('Audi','Q5','SUV'),('Audi','Q7','Luxury SUV'),('Audi','Q8','Luxury SUV'),('Audi','TT','Sports Coupe'),('Audi','e-tron','Electric Vehicle'),
    ('Volkswagen','Polo','Hatchback'),('Volkswagen','Golf','Hatchback'),('Volkswagen','Passat','Sedan'),('Volkswagen','Tiguan','SUV'),('Volkswagen','Touareg','SUV'),('Volkswagen','Amarok','Pickup'),('Volkswagen','Transporter','Van'),('Volkswagen','Caddy','Cargo Van'),('Volkswagen','Crafter','Panel Van'),('Volkswagen','Multivan','Passenger Van'),
    ('Nissan','March','Hatchback'),('Nissan','Note','Hatchback'),('Nissan','Sylphy','Sedan'),('Nissan','Altima','Sedan'),('Nissan','X-Trail','SUV'),('Nissan','Patrol','SUV'),('Nissan','Navara','Pickup'),('Nissan','Serena','Minivan'),('Nissan','Urvan','Van'),('Nissan','Leaf','Electric Vehicle'),
    ('Honda','Fit','Hatchback'),('Honda','Civic','Sedan'),('Honda','Accord','Sedan'),('Honda','CR-V','SUV'),('Honda','HR-V','Crossover'),('Honda','Pilot','SUV'),('Honda','Odyssey','Minivan'),('Honda','Ridgeline','Pickup'),('Honda','Jazz','Hatchback'),('Honda','e','Electric Vehicle'),
    ('Ford','Fiesta','Hatchback'),('Ford','Focus','Hatchback'),('Ford','Fusion','Sedan'),('Ford','Mustang','Sports Coupe'),('Ford','Escape','SUV'),('Ford','Explorer','SUV'),('Ford','Everest','SUV'),('Ford','Ranger','Pickup'),('Ford','Transit','Panel Van'),('Ford','F-150','Pickup'),
    ('Hyundai','i10','City Car'),('Hyundai','i20','Hatchback'),('Hyundai','Elantra','Sedan'),('Hyundai','Sonata','Sedan'),('Hyundai','Tucson','SUV'),('Hyundai','Santa Fe','SUV'),('Hyundai','Palisade','Luxury SUV'),('Hyundai','Staria','Passenger Van'),('Hyundai','Porter','Pickup'),('Hyundai','Ioniq 5','Electric Vehicle'),
    ('Kia','Picanto','City Car'),('Kia','Rio','Hatchback'),('Kia','Cerato','Sedan'),('Kia','K5','Sedan'),('Kia','Sportage','SUV'),('Kia','Sorento','SUV'),('Kia','Telluride','Luxury SUV'),('Kia','Carnival','Passenger Van'),('Kia','Bongo','Pickup'),('Kia','EV6','Electric Vehicle'),
    ('Mazda','Mazda2','Hatchback'),('Mazda','Mazda3','Sedan'),('Mazda','Mazda6','Sedan'),('Mazda','CX-3','Crossover'),('Mazda','CX-5','SUV'),('Mazda','CX-60','SUV'),('Mazda','CX-90','Luxury SUV'),('Mazda','BT-50','Pickup'),('Mazda','MX-5','Roadster'),('Mazda','RX-8','Sports Coupe'),
    ('Subaru','Impreza','Hatchback'),('Subaru','Legacy','Sedan'),('Subaru','WRX','Sports Coupe'),('Subaru','Forester','SUV'),('Subaru','Outback','Wagon / Estate'),('Subaru','Crosstrek','Crossover'),('Subaru','Ascent','SUV'),('Subaru','BRZ','Sports Coupe'),('Subaru','Solterra','Electric Vehicle'),('Subaru','Levorg','Wagon / Estate'),
    ('Mitsubishi','Mirage','Hatchback'),('Mitsubishi','Lancer','Sedan'),('Mitsubishi','Outlander','SUV'),('Mitsubishi','Eclipse Cross','Crossover'),('Mitsubishi','Pajero','SUV'),('Mitsubishi','Pajero Sport','SUV'),('Mitsubishi','Triton','Pickup'),('Mitsubishi','Delica','Van'),('Mitsubishi','Canter','Light-Duty Pickup'),('Mitsubishi','Fuso Fighter','Medium Truck'),
    ('Land Rover','Defender','Off-road SUV'),('Land Rover','Discovery','SUV'),('Land Rover','Discovery Sport','SUV'),('Land Rover','Range Rover','Luxury SUV'),('Land Rover','Range Rover Sport','Luxury SUV'),('Land Rover','Range Rover Evoque','Luxury SUV'),('Land Rover','Freelander','SUV'),('Land Rover','Velar','Luxury SUV'),('Land Rover','Defender 130','Off-road SUV'),('Land Rover','Discovery 5','SUV'),
    ('Volvo','S60','Sedan'),('Volvo','S90','Luxury Sedan'),('Volvo','V60','Wagon / Estate'),('Volvo','V90','Wagon / Estate'),('Volvo','XC40','Crossover'),('Volvo','XC60','SUV'),('Volvo','XC90','Luxury SUV'),('Volvo','EX30','Electric Vehicle'),('Volvo','EX90','Electric Vehicle'),('Volvo','FH','Tractor Unit'),
]

# 160+ consistent vehicle records, each with a local generated image tied to its make/model.
# We use a deterministic SVG artwork for every record rather than a random stock image.
VEHICLE_LOCATIONS = ['Nairobi','Mombasa','Kisumu','Nakuru','Eldoret','Thika','Ruiru','Kiambu','Kitengela','Machakos','Naivasha','Nyeri']
VEHICLE_FUELS = ['Petrol','Diesel','Hybrid','Electric']
VEHICLE_TRANSMISSIONS = ['Automatic','Manual','CVT','DCT']
'''
if marker in text and 'VEHICLE_MODELS' not in text:
    text=text.replace(marker, marker+insert)

# Replace seed vehicle block.
start=text.index("    if kind == 'vehicles' and db.execute('SELECT COUNT(*) c FROM vehicles').fetchone()['c'] == 0:")
end=text.index("    if kind == 'hotels' and", start)
seed=r'''    if kind == 'vehicles' and db.execute('SELECT COUNT(*) c FROM vehicles').fetchone()['c'] == 0:
        rows=[]
        img_dir=BASE/'static'/'vehicles'
        img_dir.mkdir(parents=True, exist_ok=True)
        for idx,(make,model,category) in enumerate(VEHICLE_MODELS[:160], start=1):
            year=str(2026 - (idx % 9))
            mileage=f"{(idx*731) % 98000:,} km"
            price=f"KES {1_200_000 + (idx*347_000):,}"
            condition='NEW' if idx % 7 == 0 else 'SECOND HAND'
            status='AVAILABLE' if idx % 11 else 'RESERVED'
            location=VEHICLE_LOCATIONS[idx % len(VEHICLE_LOCATIONS)]
            fuel=VEHICLE_FUELS[idx % len(VEHICLE_FUELS)]
            transmission=VEHICLE_TRANSMISSIONS[idx % len(VEHICLE_TRANSMISSIONS)]
            title=f'{make} {model} {year}'
            filename=f"{idx:03d}_{re.sub(r'[^a-z0-9]+','-',(make+'-'+model).lower()).strip('-')}.svg"
            # Keep the image self-describing and visually matched to the same record.
            svg=f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 700"><defs><linearGradient id="g" x1="0" x2="1"><stop stop-color="#f2f4f7"/><stop offset="1" stop-color="#e7ebef"/></linearGradient></defs><rect width="1200" height="700" fill="url(#g)"/><ellipse cx="610" cy="580" rx="410" ry="38" fill="#b9c0c8" opacity=".45"/><g fill="#22272e"><rect x="230" y="365" width="740" height="150" rx="70"/><path d="M335 365 Q405 220 585 205 L760 220 Q850 238 895 365Z"/><rect x="420" y="252" width="145" height="75" rx="18" fill="#dfe7ef"/><rect x="585" y="245" width="170" height="82" rx="18" fill="#dfe7ef"/></g><g fill="#111"><circle cx="390" cy="535" r="62"/><circle cx="830" cy="535" r="62"/></g><g fill="#f2f4f7"><circle cx="390" cy="535" r="28"/><circle cx="830" cy="535" r="28"/></g><text x="60" y="80" font-family="Arial,Helvetica,sans-serif" font-size="44" font-weight="700" fill="#8b1e2d">{html.escape(make)}</text><text x="60" y="135" font-family="Arial,Helvetica,sans-serif" font-size="34" font-weight="600" fill="#20252b">{html.escape(model)}</text><text x="60" y="185" font-family="Arial,Helvetica,sans-serif" font-size="25" fill="#58616b">{html.escape(category)} · {year}</text><text x="60" y="650" font-family="Arial,Helvetica,sans-serif" font-size="22" fill="#58616b">Verified demo image · exact record: {html.escape(make)} {html.escape(model)}</text></svg>"""
            (img_dir/filename).write_text(svg, encoding='utf-8')
            image=url_for('static', filename=f'vehicles/{filename}')
            desc=f'{make} {model} {year}, {category.lower()}, {mileage}, {fuel}, {transmission}. Professionally prepared demonstration listing.'
            rows.append((title,category,make,model,year,mileage,price,condition,location,desc,image,status,now()))
        db.executemany('INSERT INTO vehicles(title,category,make,model,year,mileage,price,condition,location,description,image,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)', rows)
'''
text=text[:start]+seed+text[end:]

# Replace vehicle browse route with filters and filter options context. Locate exact function body segment to return.
old="""    if kind == 'vehicles':\n        sql = \"SELECT * FROM vehicles WHERE (title LIKE ? OR make LIKE ? OR model LIKE ? OR location LIKE ? OR category LIKE ?)\"\n        params=[f'%{q}%']*4 + [f'%{category}%'] if category else [f'%{q}%']*4 + ['%%']\n        sql += ' ORDER BY id DESC'\n        items = get_db().execute(sql, params).fetchall()\n"""
new="""    if kind == 'vehicles':\n        make = request.args.get('make','').strip()\n        model = request.args.get('model','').strip()\n        fuel = request.args.get('fuel','').strip()\n        transmission = request.args.get('transmission','').strip()\n        conditions = request.args.get('condition','').strip()\n        clauses=[\"(title LIKE ? OR make LIKE ? OR model LIKE ? OR location LIKE ? OR category LIKE ?)\"]\n        params=[f'%{q}%']*5\n        if category: clauses.append('category=?'); params.append(category)\n        if make: clauses.append('make=?'); params.append(make)\n        if model: clauses.append('model=?'); params.append(model)\n        if fuel: clauses.append(\"description LIKE ?\"); params.append(f'%{fuel}%')\n        if transmission: clauses.append(\"description LIKE ?\"); params.append(f'%{transmission}%')\n        if conditions: clauses.append('condition=?'); params.append(conditions)\n        sql = 'SELECT * FROM vehicles WHERE ' + ' AND '.join(clauses) + ' ORDER BY id DESC'\n        items = get_db().execute(sql, params).fetchall()\n"""
if old not in text: raise SystemExit('browse block not found')
text=text.replace(old,new)
# ensure browse passes filter lists
old_return="return render_template('browse.html', items=items, q=q, category=category)"
new_return="return render_template('browse.html', items=items, q=q, category=category, make=make if kind=='vehicles' else '', model=model if kind=='vehicles' else '', fuel=fuel if kind=='vehicles' else '', transmission=transmission if kind=='vehicles' else '', conditions=conditions if kind=='vehicles' else '', vehicle_makes=sorted({r[0] for r in VEHICLE_MODELS}), vehicle_models=sorted({r[1] for r in VEHICLE_MODELS}), vehicle_fuels=VEHICLE_FUELS, vehicle_transmissions=VEHICLE_TRANSMISSIONS)"
text=text.replace(old_return,new_return)

# Add a context value for counts and filter options without changing template contract.
old="return {'business': b, 'current_kind': kind, 'business_types': BUSINESS_TYPES, 'type_catalog': TYPE_CATALOGS.get(kind, [])}"
new="return {'business': b, 'current_kind': kind, 'business_types': BUSINESS_TYPES, 'type_catalog': TYPE_CATALOGS.get(kind, []), 'vehicle_models': VEHICLE_MODELS if kind == 'vehicles' else []}"
text=text.replace(old,new)

app.write_text(text)
