# REAL MART — Kenyan supermarket platform

## Customer storefront
- `/` — customer supermarket landing/store.
- `/shop` — searchable catalogue.
- `/cart` and `/checkout` — basket and online order checkout.
- `/order/<order_number>` — order/payment confirmation; M-PESA status updates automatically.
- `/supermarket` — installable customer PWA.

The starter catalogue is supermarket-oriented (bread, packaged milk, dairy, cereals, flour, rice, sugar, tea, cooking oil, canned food, snacks, beverages, baby care, personal care, household, fresh produce, meat, frozen food, pet supplies and stationery). Products are preloaded; staff manage availability/stock instead of manually building the catalogue.

## Merchant / agent workstation
- `/mypp` — agent login.
- `/mypp/on` — the one-screen Merchant Point workstation.
- `/mypp/manifest.webmanifest` and `/mypp/sw.js` — installable agent PWA.

The workstation remembers the last agent who logged in at the same mart and provides a sidebar for sales, catalogue search, held sales, day summary, online orders, cash drawer and shift controls. Sign out is at the bottom of the sidebar. The footer text is admin-editable.

`/212324` remains a compatibility redirect for older installations.

## Master admin
- `/admin/login` — master admin login.
- `/admin` — master control centre.
- `/admin/settings` — business identity and Safaricom Daraja configuration.

`/fr%2` remains as a legacy admin path for older bookmarks.

## M-PESA / Daraja
The platform supports Safaricom STK push initiation and callback reconciliation. Admins configure the active integration from `/admin/settings`; credentials are encrypted at rest. The online checkout sends the M-PESA prompt, then polls the payment record until it becomes `PAID` or `FAILED`.

For live service, set the Daraja environment to production and use a public HTTPS callback such as:
`https://YOUR-DOMAIN/api/payments/daraja/callback`

Safaricom's current developer platform is Daraja 3.0.

## Catalogue philosophy
The catalogue is designed as a preloaded master inventory rather than an empty system that requires an administrator to add every item. The included seed provides a realistic Kenyan supermarket starter catalogue with unique remote product-photo URLs so the same placeholder image is not intentionally reused for every item.

The database/query design uses indexed product/store relations and server-side limits, so the storefront can scale to very large catalogues. Do not fabricate hundreds of thousands of fake SKUs solely to create a large number; load additional real product identities through a deployment/import pipeline when a larger master catalogue is available.

## Deployment
`Procfile`, `render.yaml`, `requirements.txt` and database bootstrap are included. PostgreSQL is the intended production database. Configure `ADMIN_USERNAME` and `ADMIN_PASSWORD` in Render.
