# REAL MART

Unified supermarket POS + online store + inventory + M-PESA + administration platform.

## What is included

- Single Flask backend and shared SQLAlchemy domain model.
- PostgreSQL-ready production configuration; SQLite fallback for local development.
- Public commerce service: `/`, `/shop`, `/product/<slug>`, `/cart`, `/checkout`, order confirmation and customer QR sharing.
- Multi-mart install page: `/supermarket` plus per-mart app manifests. Each active Store can have its own online catalogue, prices and stock.
- Protected cashier PWA/till: `/otcOmc` with barcode/search, cash/M-PESA/card surfaces, receipt printing, shift control and offline-safe shell.
- Protected master admin: `/fr%2` (with a compatibility `/admin` route) for business-wide sales, branches, catalogue, pricing, users, audit and export.
- Inventory ledger and store-specific product/pricing records.
- Shared sale/order/payment model architecture.
- Daraja adapter with OAuth and STK Push initiation plus callback parsing. Provider results are treated as PENDING until a verified callback changes payment state to PAID/FAILED.
- Flask-Migrate/Alembic migration structure.

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python init_db.py
flask --app app run --debug
```

Default local admin comes from `ADMIN_EMAIL` and `ADMIN_PASSWORD` in `.env`.

## Render

Render uses `pip install -r requirements.txt` for the build and Gunicorn for production in this project. `Procfile` and `render.yaml` are included. The first boot runs `init_db.py` so a fresh Postgres database is created automatically. Flask-Migrate is included for subsequent schema evolution; add and commit migrations as the model evolves. Configure production secrets in Render Environment Variables instead of committing `.env`.

Required production variables at minimum:

- `SECRET_KEY`
- `DATABASE_URL` (automatically wired by `render.yaml` when using the Blueprint)
- `PAYMENT_CREDENTIAL_ENCRYPTION_KEY` for database-stored integration credentials if that settings UI is enabled
- Daraja values: `DARAJA_ENV`, `DARAJA_CONSUMER_KEY`, `DARAJA_CONSUMER_SECRET`, `DARAJA_SHORTCODE`, `DARAJA_PASSKEY`, `DARAJA_CALLBACK_URL`

For Render, the `render.yaml` creates the web service and a Postgres database. You can deploy from the repo root using the Blueprint workflow or create a Python web service manually.

## Important production hardening before live trading

1. Complete offline queue processing with `client_operation_id` idempotency and server-side reconciliation; the included endpoint deliberately does not auto-commit offline envelopes yet.
2. Add business/store administration screens, catalogue CSV/XLSX import, supplier receiving workflows, returns/refunds, delivery assignment, backup/export/restore jobs, and tax configuration.
3. Store Daraja credentials using the encrypted `PaymentIntegration` model only; do not expose secrets to browser JavaScript.
4. Add a production-grade object-storage adapter for product images and receipts.
5. Add tests for payments, inventory, pricing limits, authorization, concurrency and duplicate callbacks before taking live payments.

## Project structure

```text
real-mart/
  app.py
  config.py
  models.py
  extensions.py
  routes/
  services/
    pricing.py
    audit.py
    crypto.py
    payments/
  templates/
  static/
  migrations/
  requirements.txt
  Procfile
  render.yaml
```

## Route philosophy

The public root is the customer-facing `.com` experience. `/supermarket` is the install/discovery layer for multiple marts. `/otcOmc` is intentionally non-obvious and reserved for authenticated cashier operations. `/fr%2` is the master control centre and is not linked from the public navigation.

## Deployment URL model

The customer storefront is always the service root `/`. The hostname can be a Render URL such as `https://choices-6ej4.onrender.com/` today and a custom `.com` later; no code should hard-code `.com`.

The application uses relative paths:

- `/` — customer shopping/storefront
- `/supermarket` — multi-mart discovery and mobile install page
- `/otcOmc` — protected cashier till/PWA
- `/fr%2` — protected master administration

For production, attach a persistent Render Postgres database through `DATABASE_URL`. SQLite is only a fallback for local development; it is not a persistent production store on Render.
