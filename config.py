import os
from pathlib import Path
from urllib.parse import urlparse, urlunparse

BASE_DIR = Path(__file__).resolve().parent


def normalize_db_url(url: str | None) -> str:
    url = url or f"sqlite:///{BASE_DIR / 'instance' / 'real_mart.db'}"
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
    SQLALCHEMY_DATABASE_URI = normalize_db_url(os.getenv("DATABASE_URL"))
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 280,
    }
    WTF_CSRF_TIME_LIMIT = None
    SESSION_COOKIE_SECURE = os.getenv("FLASK_ENV", "development") == "production"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    CURRENCY = os.getenv("CURRENCY", "KES")
    TIMEZONE = os.getenv("TIMEZONE", "Africa/Nairobi")
    BUSINESS_NAME = os.getenv("BUSINESS_NAME", "REAL MART")
    ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
    DARAJA_ENV = os.getenv("DARAJA_ENV", "sandbox")
    DARAJA_CONSUMER_KEY = os.getenv("DARAJA_CONSUMER_KEY", "")
    DARAJA_CONSUMER_SECRET = os.getenv("DARAJA_CONSUMER_SECRET", "")
    DARAJA_SHORTCODE = os.getenv("DARAJA_SHORTCODE", "")
    DARAJA_PASSKEY = os.getenv("DARAJA_PASSKEY", "")
    DARAJA_CALLBACK_URL = os.getenv("DARAJA_CALLBACK_URL", "")
    PAYMENT_CREDENTIAL_ENCRYPTION_KEY = os.getenv("PAYMENT_CREDENTIAL_ENCRYPTION_KEY", "")
