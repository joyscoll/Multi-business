import base64
import os
from cryptography.fernet import Fernet

def _fernet():
    key = os.getenv("PAYMENT_CREDENTIAL_ENCRYPTION_KEY")
    if not key:
        raise RuntimeError("PAYMENT_CREDENTIAL_ENCRYPTION_KEY must be configured before storing payment credentials")
    return Fernet(key.encode())

def encrypt(value: str | None):
    if value is None:
        return None
    return _fernet().encrypt(value.encode()).decode()

def decrypt(value: str | None):
    if not value:
        return None
    return _fernet().decrypt(value.encode()).decode()
