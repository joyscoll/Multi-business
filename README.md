# REAL MART V8

Kenya-first supermarket platform with three focused workspaces sharing catalogue, stock, prices, orders and M-PESA payment state.

## Customer store
- `/` — clean online storefront
- `/shop` — complete catalogue/search
- `/cart` — basket
- `/checkout` — customer checkout
- `/order/<order_number>` — order/payment status

The home page deliberately promotes everyday Kenyan basket items first (sugar, packaged fresh milk, yoghurt, bread, maize meal, rice, cooking oil, eggs, tea and coffee). Products without an exact verified photograph use a restrained brand-initial tile instead of a reused/wrong image.

## Merchant Point
- `/merchant` — cashier/agent sign-in
- `/merchant/on` — single-screen till workspace
- `/merchant/manifest.webmanifest` and `/merchant/sw.js` — installable PWA

## Master control
- `/control` — secure master-admin sign-in and dashboard
- `/control/products` — catalogue visibility and price control
- `/control/stores` — marts/branches
- `/control/users` — staff and access
- `/control/pricing` — pricing rules
- `/control/settings` — business identity and Safaricom Daraja settings
- `/control/expenses` — expenses
- `/control/audit` — audit trail
- `/control/system-errors` — protected error records
- `/control/security` — security overview
- `/control/backups` — business export/recovery tools

## Operational model
The catalogue is seeded as a realistic starter master list. StoreProduct availability controls determine whether an item can be sold online and/or at POS. Admins therefore disable stock they do not carry rather than manually constructing the whole supermarket.

The schema is designed for a much larger catalogue and controlled imports when a genuine supplier/product feed is available; the application does not invent hundreds of thousands of fake SKUs.

## Deployment
Render can run:

    gunicorn app:app

or the included `render.yaml` / `Procfile`, which initialize the database before starting Gunicorn.

Set `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `DATABASE_URL`, `SECRET_KEY`, and the Daraja configuration values in the Render environment as appropriate for the deployment.

## Important
This V8 build intentionally uses only the canonical routes above.
