import base64
from datetime import datetime, timedelta
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.orders.models import Order
from apps.payments import mpesa
from apps.payments.models import MpesaTransaction

SECRET = "s3cret-callback-token-123456"
CFG = dict(
    MPESA_ENABLED=True, MPESA_CONSUMER_KEY="key", MPESA_CONSUMER_SECRET="secret", MPESA_SHORTCODE="174379",
    MPESA_PASSKEY="passkey123", MPESA_PARTY_B="174379", MPESA_TRANSACTION_TYPE="CustomerPayBillOnline",
    MPESA_CALLBACK_BASE_URL="https://shop.example.com", MPESA_CALLBACK_SECRET=SECRET,
    MPESA_BASE_URL="https://sandbox.test", MPESA_MAX_ATTEMPTS_PER_ORDER=3,
)


class Resp:
    def __init__(self, data, status=200):
        self.data, self.status_code = data, status

    def json(self):
        return self.data


class FakeDaraja:
    """Stands in for Safaricom, answering with the documented response shapes."""

    def __init__(self):
        self.posts = []   # (path, payload)
        self.oauth_calls = 0
        self.push = {"MerchantRequestID": "29115-34620561-1", "CheckoutRequestID": "ws_CO_191220191020363925",
                     "ResponseCode": "0", "ResponseDescription": "Success. Request accepted for processing",
                     "CustomerMessage": "Success. Request accepted for processing"}
        self.query = {"errorCode": "500.001.1001", "errorMessage": "The transaction is being processed"}
        self.n = 0

    def get(self, url, params=None, auth=None, timeout=None):
        self.oauth_calls += 1
        assert auth == ("key", "secret") and params == {"grant_type": "client_credentials"}
        return Resp({"access_token": "tok-abc", "expires_in": "3599"})

    def post(self, url, json=None, headers=None, timeout=None):
        assert headers["Authorization"] == "Bearer tok-abc"
        path = url.replace("https://sandbox.test", "")
        self.posts.append((path, json))
        if path.endswith("processrequest"):
            self.n += 1
            body = dict(self.push)
            if "CheckoutRequestID" in body and self.n > 1:
                body["CheckoutRequestID"] = f"{body['CheckoutRequestID']}_{self.n}"
            return Resp(body)
        return Resp(self.query, 200 if "ResultCode" in self.query else 500)

    @property
    def stk_payloads(self):
        return [p for path, p in self.posts if path.endswith("processrequest")]


def make_order(total=5000, phone="+254712345678"):
    return Order.objects.create(customer_name="Amina", phone=phone, delivery_method="collection",
                                subtotal=total, total=total)


def callback(checkout="ws_CO_191220191020363925", code=0, amount=5000, receipt="NLJ7RT61SV", desc=None):
    body = {"MerchantRequestID": "29115-34620561-1", "CheckoutRequestID": checkout, "ResultCode": code,
            "ResultDesc": desc or ("The service request is processed successfully." if code == 0 else "Request cancelled by user.")}
    if code == 0:  # CallbackMetadata only exists on success
        body["CallbackMetadata"] = {"Item": [
            {"Name": "Amount", "Value": amount}, {"Name": "MpesaReceiptNumber", "Value": receipt},
            {"Name": "TransactionDate", "Value": 20260428102115}, {"Name": "PhoneNumber", "Value": 254712345678}]}
    return {"Body": {"stkCallback": body}}


@override_settings(**CFG)
class MpesaBase(TestCase):
    def setUp(self):
        cache.clear()
        self.fake = FakeDaraja()
        for target, fn in (("get", self.fake.get), ("post", self.fake.post)):
            p = mock.patch(f"apps.payments.mpesa.requests.{target}", side_effect=fn)
            p.start()
            self.addCleanup(p.stop)
        self.c = APIClient()
        self.order = make_order()

    def push(self, **over):
        data = {"reference": self.order.reference, "phone": "0712345678"}
        data.update(over)
        return self.c.post("/api/payments/mpesa/stk-push/", data, format="json")

    def cb(self, payload, secret=SECRET):
        return self.c.post(f"/api/payments/mpesa/callback/{secret}/", payload, format="json")


class DarajaFormatTests(MpesaBase):
    def test_password_is_base64_of_shortcode_passkey_timestamp(self):
        ts = "20260428102115"
        self.assertEqual(base64.b64decode(mpesa.make_password("174379", "pk", ts)).decode(), "174379pk20260428102115")

    def test_timestamp_is_east_africa_time(self):
        utc_evening = datetime(2026, 4, 28, 22, 30, 0, tzinfo=mpesa.ZoneInfo("UTC"))
        self.assertEqual(mpesa.timestamp(utc_evening.astimezone(mpesa.EAT)), "20260429013000")  # UTC+3

    def test_push_payload_matches_the_daraja_spec(self):
        r = self.push()
        self.assertEqual(r.status_code, 201, r.data)
        p = self.fake.stk_payloads[0]
        self.assertEqual(p["BusinessShortCode"], "174379")
        self.assertEqual(p["TransactionType"], "CustomerPayBillOnline")
        self.assertEqual((p["PartyA"], p["PhoneNumber"], p["PartyB"]), ("254712345678", "254712345678", "174379"))
        self.assertIsInstance(p["Amount"], int)
        self.assertEqual(p["Amount"], 5000)
        self.assertRegex(p["Timestamp"], r"^\d{14}$")
        self.assertEqual(base64.b64decode(p["Password"]).decode(), f"174379passkey123{p['Timestamp']}")
        self.assertEqual(p["CallBackURL"], f"https://shop.example.com/api/payments/mpesa/callback/{SECRET}/")
        self.assertLessEqual(len(p["AccountReference"]), 12)
        self.assertLessEqual(len(p["TransactionDesc"]), 13)

    def test_access_token_is_cached(self):
        self.push()
        MpesaTransaction.objects.update(status="failed")  # allow another attempt
        self.push(reference=self.order.reference)
        self.assertEqual(self.fake.oauth_calls, 1)


class StkPushEndpointTests(MpesaBase):
    def test_creates_pending_transaction(self):
        r = self.push()
        self.assertEqual((r.data["status"], r.data["amount"]), ("pending", 5000))
        txn = MpesaTransaction.objects.get()
        self.assertEqual((txn.phone, txn.checkout_request_id), ("+254712345678", "ws_CO_191220191020363925"))

    def test_requires_matching_order_phone(self):
        self.assertEqual(self.push(phone="0799999999").status_code, 404)
        self.assertEqual(self.push(reference="HS-000000-AAAAA").status_code, 404)
        self.assertEqual(self.fake.stk_payloads, [])

    def test_can_charge_a_different_mpesa_number(self):
        self.assertEqual(self.push(pay_phone="0722000111").status_code, 201)
        self.assertEqual(self.fake.stk_payloads[0]["PhoneNumber"], "254722000111")

    def test_non_safaricom_number_rejected(self):
        order = make_order(phone="+251911223344")
        r = self.c.post("/api/payments/mpesa/stk-push/", {"reference": order.reference, "phone": "+251911223344"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_repeat_within_prompt_window_resumes_instead_of_double_charging(self):
        first = self.push()
        second = self.push()
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.data["resumed"])
        self.assertEqual(second.data["checkout_request_id"], first.data["checkout_request_id"])
        self.assertEqual(len(self.fake.stk_payloads), 1)

    def test_attempt_limit_per_order(self):
        for _ in range(3):
            self.assertEqual(self.push().status_code, 201)
            MpesaTransaction.objects.filter(status="pending").update(status="cancelled")
        self.assertEqual(self.push().status_code, 429)

    def test_paid_and_cancelled_orders_are_rejected(self):
        self.order.payments.create(method="cash", amount=5000)
        self.assertEqual(self.push().status_code, 400)
        order = make_order()
        order.change_status("cancelled")
        r = self.c.post("/api/payments/mpesa/stk-push/", {"reference": order.reference, "phone": "0712345678"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_only_the_balance_due_is_requested(self):
        self.order.payments.create(method="cash", amount=2000)
        self.push()
        self.assertEqual(self.fake.stk_payloads[0]["Amount"], 3000)

    def test_daraja_rejection_marks_failed(self):
        self.fake.push = {"requestId": "x", "errorCode": "400.002.02", "errorMessage": "Bad Request - Invalid PhoneNumber"}
        r = self.push()
        self.assertEqual(r.status_code, 502)
        self.assertIn("Invalid PhoneNumber", r.data["detail"])
        self.assertEqual(MpesaTransaction.objects.get().status, "failed")

    @override_settings(MPESA_ENABLED=False)
    def test_disabled_when_not_configured(self):
        self.assertEqual(self.push().status_code, 503)
        self.assertFalse(self.c.get("/api/settings/").data["mpesa_enabled"])

    def test_public_settings_expose_flag(self):
        self.assertTrue(self.c.get("/api/settings/").data["mpesa_enabled"])


class CallbackTests(MpesaBase):
    def setUp(self):
        super().setUp()
        self.push()

    def test_success_records_payment_and_confirms_order(self):
        r = self.cb(callback())
        self.assertEqual((r.status_code, r.data["ResultCode"]), (200, 0))
        txn = MpesaTransaction.objects.get()
        self.assertEqual((txn.status, txn.mpesa_receipt, txn.confirmed_via), ("success", "NLJ7RT61SV", "callback"))
        self.assertFalse(txn.needs_review)
        self.order.refresh_from_db()
        self.assertEqual((self.order.payment_status, self.order.status), ("paid", "confirmed"))
        pay = self.order.payments.get()
        self.assertEqual((pay.method, pay.amount, pay.reference), ("mpesa", 5000, "NLJ7RT61SV"))

    def test_duplicate_callback_is_idempotent(self):
        self.cb(callback())
        self.cb(callback())
        self.assertEqual(self.order.payments.count(), 1)

    def test_cancelled_by_customer(self):
        self.cb(callback(code=1032))
        txn = MpesaTransaction.objects.get()
        self.assertEqual((txn.status, txn.result_code), ("cancelled", 1032))
        self.assertEqual(self.order.payments.count(), 0)
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, "unpaid")

    def test_wrong_pin_and_timeout_codes(self):
        self.cb(callback(code=2001, desc="Wrong PIN"))
        self.assertEqual(MpesaTransaction.objects.get().status, "failed")
        MpesaTransaction.objects.all().delete()
        second = self.push().data["checkout_request_id"]  # Daraja issues a fresh id per attempt
        self.cb(callback(checkout=second, code=1037, desc="DS timeout"))
        self.assertEqual(MpesaTransaction.objects.get().status, "timeout")

    def test_wrong_secret_is_404_and_changes_nothing(self):
        self.assertEqual(self.cb(callback(), secret="not-the-secret").status_code, 404)
        self.assertEqual(MpesaTransaction.objects.get().status, "pending")

    def test_unknown_checkout_id_is_accepted_but_ignored(self):
        self.assertEqual(self.cb(callback(checkout="ws_CO_unknown")).status_code, 200)
        self.assertEqual(self.order.payments.count(), 0)

    def test_malformed_payloads_do_not_crash(self):
        for bad in ({}, {"Body": {}}, {"Body": {"stkCallback": {"CheckoutRequestID": "x", "ResultCode": "abc"}}}, []):
            self.assertEqual(self.cb(bad).status_code, 200)

    def test_amount_mismatch_still_records_real_money_and_flags_review(self):
        self.cb(callback(amount=4000))
        txn = MpesaTransaction.objects.get()
        self.assertTrue(txn.needs_review)
        self.assertEqual(self.order.payments.get().amount, 4000)
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, "partial")  # 1,000 still owed
        self.assertEqual(self.order.status, "pending")          # not auto-confirmed until fully paid

    def test_decimal_and_string_amounts_are_parsed(self):
        self.cb(callback(amount="5000.00"))
        self.assertEqual(self.order.payments.get().amount, 5000)
        self.assertFalse(MpesaTransaction.objects.get().needs_review)

    def test_late_success_after_timeout_is_honoured(self):
        MpesaTransaction.objects.update(status="timeout", result_desc="No response from M-Pesa.")
        self.cb(callback())
        self.assertEqual(MpesaTransaction.objects.get().status, "success")
        self.assertEqual(self.order.payments.count(), 1)

    def test_failure_callback_cannot_undo_a_success(self):
        self.cb(callback())
        self.cb(callback(code=1032))
        self.assertEqual(MpesaTransaction.objects.get().status, "success")


class StatusAndReconcileTests(MpesaBase):
    def setUp(self):
        super().setUp()
        self.checkout = self.push().data["checkout_request_id"]
        self.url = f"/api/payments/mpesa/status/{self.checkout}/"

    def test_pending_status(self):
        r = self.c.get(self.url)
        self.assertEqual((r.status_code, r.data["status"]), (200, "pending"))
        self.assertEqual(r.data["order"]["balance_due"], 5000)
        self.assertEqual(len([p for p, _ in self.fake.posts if "query" in p]), 0)  # too early to query

    def test_unknown_checkout_is_404(self):
        self.assertEqual(self.c.get("/api/payments/mpesa/status/ws_CO_nope/").status_code, 404)

    def test_lost_callback_is_recovered_by_query(self):
        MpesaTransaction.objects.update(created_at=timezone.now() - timedelta(seconds=40))
        self.fake.query = {"ResponseCode": "0", "ResultCode": "0", "ResultDesc": "The service request is processed successfully."}
        r = self.c.get(self.url)
        self.assertEqual(r.data["status"], "success")
        self.assertEqual(r.data["order"]["payment_status"], "paid")
        self.assertEqual(MpesaTransaction.objects.get().confirmed_via, "query")
        # the callback turns up late: the receipt number is filled in, no second payment
        self.cb(callback())
        txn = MpesaTransaction.objects.get()
        self.assertEqual(txn.mpesa_receipt, "NLJ7RT61SV")
        self.assertEqual(self.order.payments.count(), 1)
        self.assertEqual(self.order.payments.get().reference, "NLJ7RT61SV")

    def test_query_reports_cancellation(self):
        MpesaTransaction.objects.update(created_at=timezone.now() - timedelta(seconds=40))
        self.fake.query = {"ResponseCode": "0", "ResultCode": "1032", "ResultDesc": "Request cancelled by user"}
        self.assertEqual(self.c.get(self.url).data["status"], "cancelled")

    def test_still_processing_stays_pending_then_times_out(self):
        MpesaTransaction.objects.update(created_at=timezone.now() - timedelta(seconds=40))
        self.assertEqual(self.c.get(self.url).data["status"], "pending")
        MpesaTransaction.objects.update(created_at=timezone.now() - timedelta(seconds=400), last_queried_at=None)
        self.assertEqual(self.c.get(self.url).data["status"], "timeout")

    def test_query_is_rate_limited(self):
        MpesaTransaction.objects.update(created_at=timezone.now() - timedelta(seconds=40))
        self.c.get(self.url)
        self.c.get(self.url)
        self.assertEqual(len([p for p, _ in self.fake.posts if "query" in p]), 1)

    def test_management_command_settles_pending(self):
        from django.core.management import call_command
        MpesaTransaction.objects.update(created_at=timezone.now() - timedelta(seconds=60))
        self.fake.query = {"ResponseCode": "0", "ResultCode": "0", "ResultDesc": "ok"}
        call_command("mpesa_reconcile")
        self.assertEqual(MpesaTransaction.objects.get().status, "success")
