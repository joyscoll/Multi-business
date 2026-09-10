# MultiBusiness v1 — Ground Build

This build starts from a blank business-selection doorway.

## Entry flow
- `/start` is the only pre-selection screen. It exposes three choices: Vehicles, Hotels & Lodges, and Real Estate & Property.
- Selecting a business creates an independent business world.
- `/` redirects to that world's public home once selected.
- `/quit` returns to the business selection screen and clears business operational records so the next selection is a fresh world.
- `/authority` is the private management portal for the selected business.
- `/qr` and `/authority/qr` provide the business QR entry point.

## Independent engines
Vehicles, Hotels and Property use different operational tables, wording and authority metrics. No vehicle marketplace is rendered inside Hotels or Property.

## Run locally
```bash
pip install -r requirements.txt
python app.py
```
For Render, the Procfile runs Gunicorn.
