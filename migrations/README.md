# Database migrations

Flask-Migrate/Alembic is included in `requirements.txt` and initialized in `app.py`.

The project uses `init_db.py` on first deployment to create a fresh schema immediately. Once the domain models are stable, generate and commit versioned migrations with:

```bash
flask --app app db migrate -m "describe change"
flask --app app db upgrade
```

Do not replace the authoritative Postgres database with SQLite in production.
