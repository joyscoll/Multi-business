# REAL MART

Unified supermarket POS + online store + inventory + M-PESA + administration platform.

## What is included

- Single Flask backend and shared SQLAlchemy domain model.
- PostgreSQL-ready production configuration; SQLite fallback for local development.
- Public storefront: `/`, `/shop`, `/product/<slug>`, `/cart`, `/checkout`.
- Authenticated PWA POS: `/pos` with barcode/search, cash sales, M-PESA initiation surface, local PWA assets, and offline UI state.
- Admin dashboard: `/admin`, products/prices, pricing rules, users, audit log.
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
