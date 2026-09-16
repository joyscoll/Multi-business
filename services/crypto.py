import base64
import hashlib
import os
from cryptography.fernet import Fernet

def _fernet():
    key = os.getenv("PAYMENT_CREDENTIAL_ENCRYPTION_KEY")
    if not key:
        secret = os.getenv("SECRET_KEY", "dev-only-change-me")
        key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()).decode()
    return Fernet(key.encode())

def encrypt(value: str | None):
    if value is None:
        return None
    return _fernet().encrypt(value.encode()).decode()

def decrypt(value: str | None):
    if not value:
        return None
    return _fernet().decrypt(value.encode()).decode()
