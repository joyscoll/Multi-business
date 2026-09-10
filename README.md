# MultiBusiness v1 — Independent Business Engine

Flask mobile-first business platform. The platform starts at `/start` only when no active business is registered. A business operator chooses **one** business type, completes the identity, and that choice becomes the active business world.

## Architecture

- `/` = visitor home for the registered business
- `/start` = fresh business setup / new business world
- `/authority` = private operating and management portal for the active business
- QR codes open the current business and can deep-link directly to an item profile
- There is no cross-business browsing or shared marketplace screen
- To create another business world, use **Authority → Business settings → Reset business**, then return to `/start`

## Complete v1 engines

- Vehicles
- Hotels & Lodges
- Restaurants, Bars & Cafés
- Real Estate & Property
- Retail & General Marketplace

## Engine-specific operations

### Vehicles
Vehicle records, photos, specifications, buying requests, finance requests, viewing requests, offers, seller intake and QR identity.

### Hotels
Room inventory with actual room numbers, availability, guest booking requests, service requests and Authority room management.

### Restaurants
Menu-style product records, orders, table reservations and Authority table management.

### Property
Property records, viewing requests, offers and rental requests.

### Retail / Marketplace
Product records, purchase / reserve actions, enquiries and seller intake.

## Other selectable engines

Marine, Electronics, Furniture, Equipment and Events are selectable but intentionally isolated from the complete engines. They can later be replaced by dedicated products/sites without mixing their data into the active business.

## Technical

- Flask
- SQLite with WAL mode and busy-timeout / retry protection
- JSON business export
- ZIP backup containing JSON and SQLite database
- Restore interface in Authority
- QR generation using `qrcode`
- Responsive CSS with mobile bottom navigation
- Camera QR entry where the browser supports `BarcodeDetector`
- Public errors are clean; technical failures are recorded under Authority → System Errors

## Render

Start command:

```text
gunicorn app:app
```

Required packages are listed in `requirements.txt`.
