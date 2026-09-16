"""Production-safe first-boot database bootstrap."""
from sqlalchemy.exc import IntegrityError
from extensions import db
from seed import seed_defaults
from models import Business, Store


def bootstrap_database():
    db.create_all()
    try:
        seed_defaults()
    except IntegrityError:
        db.session.rollback()
        # Another worker may have raced the first boot. The next request can retry safely.


def database_summary():
    return {
        "dialect": db.engine.url.get_backend_name(),
        "database": str(db.engine.url.database or ""),
        "has_business": Business.query.first() is not None,
        "store_count": Store.query.count(),
    }
