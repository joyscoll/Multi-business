# Denmart — V11

Canonical portals:
- Customer: `/`
- Merchant/POS: `/merchant` then `/merchant/on`
- Master admin: `/control` (login and dashboard in the same protected portal)

The admin login form includes CSRF protection and successful owner authentication redirects directly to `/control`. Legacy portal aliases are not part of the new UI.

The catalogue uses broad supermarket departments and a Kenyan-oriented starter assortment. Availability is admin-controlled: customers and POS only see enabled, in-stock store products.


## Security and recovery

- `/merchant` is a protected merchant login. `/merchant/on` requires both an authenticated staff account and the merchant portal session.
- `/logout` signs out the current authenticated portal and clears the session.
- `/control` is the master administrator login and dashboard.
- Admin **Backups & recovery** provides complete JSON and portable SQLite downloads plus protected restore actions. Restores replace the full database snapshot, including staff accounts and credentials, so the administrator must sign in again afterward.
- Admin **Settings & M-PESA** stores Daraja credentials encrypted at rest, supports PayBill or Till/Buy Goods transaction type, stores the public callback URL, and can test Daraja OAuth credentials without initiating a payment.

For live M-PESA operation, obtain and configure the business credentials in Safaricom Daraja 3.0, then use the protected Settings screen to enter the issued values and registered HTTPS callback. Safaricom describes Daraja 3.0 as its platform for integrating M-PESA APIs.

## Final reliability pass
- Merchant/POS has a browser-local IndexedDB store for cached product/barcode lookups, scan events, and offline CASH/CARD sale queues. The authoritative business database remains the server database.
- USB/Bluetooth barcode scanners that operate as keyboard wedges are supported: a rapid barcode followed by Enter is treated as a barcode lookup even when the search box is not focused.
- POS gives an audible success/failure cue for scan responses where the browser permits audio.
- Offline CASH/CARD sales are queued locally and reconciled to the server on reconnection with an idempotent client reference. M-PESA remains connection-required.
- M-PESA POS sales reserve stock while pending and release it if initiation/callback fails. Successful callbacks release the reservation and decrement stock once.
- Live Daraja initiation now refuses to run when the business has not saved a complete active integration and HTTPS callback URL.
- STK status reconciliation endpoint is available for delayed callbacks.

## Data model used by the final POS
The authoritative database remains PostgreSQL on Render (or SQLite for local development). The POS browser additionally maintains a small IndexedDB local store for fast barcode/search responses and offline CASH/CARD queues. Online orders and payments remain server-side records and are visible to the control centre. The browser cache is not treated as the accounting source of truth.

## Catalogue & delivery controls (v16)

- The seeded Denmart catalogue currently contains 362 supermarket products across 20 categories.
- Admin can create, edit, archive/delete products, change mart-specific cost/selling price/stock, toggle online/POS visibility, bulk import CSV and export the live catalogue.
- Every mart can be edited, activated/deactivated, or safely archived when transaction history prevents hard deletion.
- The online order flow remains lightweight: basket -> checkout/payment -> order confirmation -> optional bike-delivery request.
- Bike delivery uses configurable base + per-kilometre charges stored in business settings.
- Merchant/POS session UI now exposes network/shift state, a live session clock, mobile-safe navigation, and online-order fulfilment progression.

### Bulk catalogue CSV

Minimum headers: `name,selling_price`. Optional headers: `brand,sku,barcode,category,unit,pack_size,description,image_url,cost_price,stock_quantity,online,pos,enabled`.


## v17 catalogue + media upgrades

The clean starter catalogue now contains **1,300+ supermarket product identities/variants** spanning groceries, fresh food, household, beauty, baby, pet care, stationery and consumer electronics. The assortment is designed around common Kenyan supermarket departments; starter prices are placeholders and remain editable by the administrator. Existing live/admin-entered prices are preserved during a catalogue refresh.

Product photos now use a strict hierarchy: an administrator can upload an exact package/product photo (normalized to an 800×800 white square for consistent cards), an administrator can enter a verified image URL, and the storefront can attempt a high-confidence product-name/brand image lookup against Open Food Facts/Open Beauty Facts/Open Products Facts. It does not intentionally substitute unrelated stock photography for a missing SKU.

The public shop exposes a compact QR code for the `/shop` URL with Save/Share controls. Database recovery includes complete JSON and portable SQLite snapshots; restore creates the current schema before replacing it, including on an empty fresh deployment.

## Real Mart M-PESA phone gateway

The web application now includes a protected live payment monitor at `/control/payment-gateway`.

1. Open **Control → Payment monitor**.
2. Copy the generated HTTPS gateway URL.
3. Paste that single URL into the native Real Mart Android gateway app.
4. Assign **SIM 1** and **SIM 2** to the correct mart/branch.
5. Incoming M-PESA SMS messages are stored, displayed live, deduplicated, and can auto-match pending online Till payments and recent POS gateway payments.

The receiving API is:

`POST /api/payment-gateway/sms?key=<business-gateway-key>`

The Android gateway supplies the SIM slot, device ID, transaction ID, amount, customer text, and raw message. Unambiguous payment matches are settled automatically; ambiguous messages stay `UNMATCHED`.

SQLite backups use a real attachment response with `as_attachment=True` and are available from **Control → Backups**.

