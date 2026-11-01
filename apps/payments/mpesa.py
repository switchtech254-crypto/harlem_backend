"""Thin client for Safaricom Daraja: OAuth, M-Pesa Express (STK push) and STK query.

Security notes
* An STK request body contains Base64(shortcode + passkey + timestamp), which reveals the passkey.
  Request bodies are therefore NEVER logged here.
* Timestamps must be East Africa Time, not the server's timezone.
"""
import base64
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)
EAT = ZoneInfo("Africa/Nairobi")
TOKEN_CACHE_KEY = "mpesa:access_token"
TIMEOUT = (5, 30)  # connect, read (seconds)
STILL_PROCESSING = "500.001.1001"  # Daraja's answer when an STK query arrives before the result exists


class MpesaError(Exception):
    def __init__(self, message, *, code=None):
        super().__init__(message)
        self.code = code


def timestamp(now: datetime | None = None) -> str:
    return (now or datetime.now(EAT)).strftime("%Y%m%d%H%M%S")


def make_password(shortcode: str, passkey: str, ts: str) -> str:
    return base64.b64encode(f"{shortcode}{passkey}{ts}".encode()).decode()


def daraja_phone(e164: str) -> str:
    """+254712345678 -> 254712345678 (Safaricom numbers only)."""
    digits = (e164 or "").lstrip("+")
    if not (digits.startswith("254") and len(digits) == 12 and digits.isdigit()):
        raise MpesaError("M-Pesa payments need a Safaricom number, e.g. 0712 345 678.")
    return digits


def callback_url() -> str:
    return f"{settings.MPESA_CALLBACK_BASE_URL}/api/payments/mpesa/callback/{settings.MPESA_CALLBACK_SECRET}/"


class DarajaClient:
    def __init__(self):
        if not settings.MPESA_ENABLED:
            raise MpesaError("M-Pesa is not configured.")
        self.base = settings.MPESA_BASE_URL.rstrip("/")

    # ---- auth
    def _token(self, *, refresh=False) -> str:
        if not refresh:
            cached = cache.get(TOKEN_CACHE_KEY)
            if cached:
                return cached
        try:
            r = requests.get(
                f"{self.base}/oauth/v1/generate",
                params={"grant_type": "client_credentials"},
                auth=(settings.MPESA_CONSUMER_KEY, settings.MPESA_CONSUMER_SECRET),
                timeout=TIMEOUT,
            )
            data = r.json()
        except (requests.RequestException, ValueError):
            logger.error("Daraja OAuth request failed (network or invalid response)")
            raise MpesaError("Could not reach M-Pesa. Please try again.") from None
        token = data.get("access_token") if isinstance(data, dict) else None
        if r.status_code != 200 or not token:
            logger.error("Daraja OAuth rejected: HTTP %s", r.status_code)
            raise MpesaError("M-Pesa authentication failed. Please contact the store.")
        ttl = max(60, int(float(data.get("expires_in", 3599))) - 120)
        cache.set(TOKEN_CACHE_KEY, token, ttl)
        return token

    def _post(self, path: str, payload: dict):
        """Returns (http_status, json_dict). The payload is never logged."""
        for attempt in (1, 2):
            token = self._token(refresh=attempt == 2)
            try:
                r = requests.post(
                    f"{self.base}{path}",
                    json=payload,
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=TIMEOUT,
                )
            except requests.RequestException:
                logger.error("Daraja request to %s failed (network)", path)
                raise MpesaError("Could not reach M-Pesa. Please try again.") from None
            if r.status_code == 401 and attempt == 1:
                cache.delete(TOKEN_CACHE_KEY)  # expired token: refresh once and retry
                continue
            try:
                data = r.json()
            except ValueError:
                data = {}
            return r.status_code, data if isinstance(data, dict) else {}
        raise MpesaError("M-Pesa authentication failed.")  # pragma: no cover

    def _auth_fields(self):
        ts = timestamp()
        return {
            "BusinessShortCode": settings.MPESA_SHORTCODE,
            "Password": make_password(settings.MPESA_SHORTCODE, settings.MPESA_PASSKEY, ts),
            "Timestamp": ts,
        }

    # ---- STK push
    def stk_push(self, *, phone: str, amount: int, account_reference: str, description: str) -> dict:
        payload = {
            **self._auth_fields(),
            "TransactionType": settings.MPESA_TRANSACTION_TYPE,
            "Amount": int(amount),
            "PartyA": phone,
            "PartyB": settings.MPESA_PARTY_B,
            "PhoneNumber": phone,
            "CallBackURL": callback_url(),
            "AccountReference": account_reference[:12],  # Daraja limit: 12
            "TransactionDesc": description[:13],  # Daraja limit: 13
        }
        status, data = self._post("/mpesa/stkpush/v1/processrequest", payload)
        if str(data.get("ResponseCode")) != "0" or not data.get("CheckoutRequestID"):
            code = data.get("errorCode") or data.get("ResponseCode")
            logger.warning("STK push rejected: HTTP %s code=%s", status, code)
            raise MpesaError(
                data.get("errorMessage") or data.get("ResponseDescription") or "M-Pesa rejected the request.",
                code=code,
            )
        return data

    # ---- STK query (fallback when the callback never arrives)
    def stk_query(self, checkout_request_id: str) -> dict | None:
        """Returns {"ResultCode": int, "ResultDesc": str}, or None while still processing/unknown."""
        status, data = self._post(
            "/mpesa/stkpushquery/v1/query", {**self._auth_fields(), "CheckoutRequestID": checkout_request_id}
        )
        if data.get("errorCode") == STILL_PROCESSING:
            return None
        try:
            return {"ResultCode": int(data["ResultCode"]), "ResultDesc": str(data.get("ResultDesc", ""))}
        except (KeyError, TypeError, ValueError):
            logger.info("STK query gave no result yet (HTTP %s)", status)
            return None
