# REAL MART — production-oriented multi-mart retail base

## Surfaces

- `/` is the customer shopping site. It is a dense retail catalogue with search, categories, branch selection, basket and checkout. It does not link to POS or admin.
- `/supermarket` is a technical PWA installation entry. In standalone mode the app is named **REAL MART** and renders the same shopping experience; the technical route is not presented in the shopping UI.
- `/212324` is the hidden computer-only cashier terminal. It has its own login, PWA manifest, service-worker scope, product API, shift controls and sale APIs.
- `/fr%2` is the protected master control centre. It is not linked from the public shopping UI or the cashier terminal.

## Administrator credentials

Production requires `ADMIN_USERNAME` and `ADMIN_PASSWORD` in the Render environment. There is no default production administrator password. The first boot creates/updates the master owner account from those environment values.

## Important security boundary

The customer API never returns stock or cost data. Cashier product APIs require authenticated cashier access and are restricted to the cashier's assigned mart. POS and shopping service workers have separate scopes and no shared global service worker is used.

The QR endpoint `/app-qr.png` encodes `request.url_root`, so it represents the site hosting the application rather than a hard-coded Render or future `.com` address.

## Deployment

The supplied Render blueprint creates a PostgreSQL database and expects the master administrator credentials to be entered as secret environment variables. The normal start command initializes the database before Gunicorn starts.

For long-term production, use persistent PostgreSQL rather than SQLite and run database backups at the deployment/database layer. `scripts/backup_postgres.sh` and `scripts/restore_postgres.sh` are retained for controlled operations.
