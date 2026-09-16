import base64
from datetime import datetime
from requests import Session
from .base import PaymentProvider

class DarajaProvider(PaymentProvider):
    def __init__(self, consumer_key, consumer_secret, shortcode, passkey, environment="sandbox", callback_url=""):
        self.consumer_key = consumer_key; self.consumer_secret = consumer_secret
        self.shortcode = shortcode; self.passkey = passkey; self.callback_url = callback_url
        self.base = "https://api.safaricom.co.ke" if environment == "production" else "https://sandbox.safaricom.co.ke"
        self.session = Session()

    def access_token(self):
        r = self.session.get(f"{self.base}/oauth/v1/generate?grant_type=client_credentials", auth=(self.consumer_key, self.consumer_secret), timeout=30)
        r.raise_for_status(); return r.json()["access_token"]

    def initiate_payment(self, *, amount, phone_number, account_reference, transaction_desc, transaction_type="CustomerPayBillOnline", **_):
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        password = base64.b64encode(f"{self.shortcode}{self.passkey}{timestamp}".encode()).decode()
        token = self.access_token()
        payload = {"BusinessShortCode": self.shortcode, "Password": password, "Timestamp": timestamp,
                   "TransactionType": transaction_type, "Amount": int(round(float(amount))),
                   "PartyA": phone_number, "PartyB": self.shortcode, "PhoneNumber": phone_number,
                   "CallBackURL": self.callback_url, "AccountReference": account_reference,
                   "TransactionDesc": transaction_desc}
        r = self.session.post(f"{self.base}/mpesa/stkpush/v1/processrequest", json=payload,
                              headers={"Authorization": f"Bearer {token}"}, timeout=30)
        r.raise_for_status(); return r.json()

    def check_payment(self, *, checkout_request_id):
        if not checkout_request_id:
            raise ValueError("checkout_request_id is required")
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        password = base64.b64encode(f"{self.shortcode}{self.passkey}{timestamp}".encode()).decode()
        token = self.access_token()
        payload = {
            "BusinessShortCode": self.shortcode,
            "Password": password,
            "Timestamp": timestamp,
            "CheckoutRequestID": checkout_request_id,
        }
        r = self.session.post(
            f"{self.base}/mpesa/stkpushquery/v1/query",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        r.raise_for_status()
        return r.json()

    def handle_callback(self, payload):
        body = ((payload or {}).get("Body") or {}).get("stkCallback") or {}
        metadata = body.get("CallbackMetadata", {}).get("Item", []) or []
        values = {item.get("Name"): item.get("Value") for item in metadata}
        return {"result_code": body.get("ResultCode"), "result_desc": body.get("ResultDesc"),
                "merchant_request_id": body.get("MerchantRequestID"), "checkout_request_id": body.get("CheckoutRequestID"),
                "receipt": values.get("MpesaReceiptNumber"), "amount": values.get("Amount"), "phone_number": values.get("PhoneNumber")}
