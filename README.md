# MultiBusiness v1

Flask-based mobile-first multi-business selling platform.

## Run locally

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000`.

## Main routes

- `/` opening/signature screen
- `/setup` business onboarding
- `/site` public storefront
- `/browse` public catalogue
- `/sell` seller submission area
- `/qr` QR management
- `/admin` private admin portal
- `/admin/backup` backup/export/restore area
- `/health` deployment health check

## Data

SQLite lives in `data/multibusiness.db`. A JSON export is maintained at `data/business.json`. Full backups are generated in `backups/` as ZIP files.

## Notes

Visitors and sellers do not need authentication in v1. The public pages are intended to be presentation-ready while the architecture stays modular for future business templates and role/authentication layers.
