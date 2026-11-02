import logging
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.orders.models import Order, Payment

from .mpesa import EAT, DarajaClient, MpesaError, daraja_phone
from .models import MpesaTransaction

logger = logging.getLogger(__name__)

PROMPT_VALID_SECONDS = 90  # an STK prompt stays on the phone for roughly this long
QUERY_AFTER_SECONDS = 20  # start asking Daraja ourselves if no callback has arrived by then
QUERY_MIN_GAP_SECONDS = 8
GIVE_UP_SECONDS = 180  # still unknown after this long -> "no response"

RESULT_MESSAGES = {
    0: "Payment received. Thank you!",
    1: "Your M-Pesa balance is too low for this payment.",
    17: "M-Pesa had an internal problem. Please try again.",
    1019: "The payment request expired. Please try again.",
    1025: "M-Pesa could not send the prompt. Please try again.",
    1032: "You cancelled the payment request.",
    1037: "We couldn't reach your phone. Please check it is on and has network, then try again.",
    2001: "The M-Pesa PIN you entered was wrong.",
}
CANCELLED_CODES = {1032}
TIMEOUT_CODES = {1037, 1019}


class PaymentError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def friendly_message(txn: MpesaTransaction) -> str:
    if txn.status == MpesaTransaction.Status.PENDING:
        return "Check your phone and enter your M-Pesa PIN to complete the payment."
    if txn.status == MpesaTransaction.Status.TIMEOUT and txn.result_code is None:
        return "We didn't get a response from M-Pesa. If money left your account we'll still confirm your order."
    return RESULT_MESSAGES.get(txn.result_code, txn.result_desc or "The payment didn't go through.")


# --------------------------------------------------------------------------- start a payment
def initiate_mpesa_payment(order: Order, *, pay_phone: str | None = None) -> tuple[MpesaTransaction, bool]:
    """Send an STK push for the order's outstanding balance. Returns (transaction, resumed).
    `resumed=True` means a prompt was sent moments ago and is still waiting (idempotent retries)."""
    if not settings.MPESA_ENABLED:
        raise PaymentError("M-Pesa payments are not available right now.", 503)
    try:
        phone = daraja_phone(pay_phone or order.phone)
    except MpesaError as exc:
        raise PaymentError(str(exc), 400) from None

    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)  # serialises concurrent attempts
        if order.status == Order.Status.CANCELLED:
            raise PaymentError("This order has been cancelled.", 400)
        due = order.balance_due
        if due <= 0:
            raise PaymentError("This order is already paid.", 400)

        recent = order.mpesa_transactions.filter(
            status=MpesaTransaction.Status.PENDING,
            created_at__gte=timezone.now() - timedelta(seconds=PROMPT_VALID_SECONDS),
        ).first()
        if recent:
            return recent, True
        if order.mpesa_transactions.count() >= settings.MPESA_MAX_ATTEMPTS_PER_ORDER:
            raise PaymentError("Too many payment attempts for this order. Please contact us.", 429)

        txn = MpesaTransaction.objects.create(order=order, phone=f"+{phone}", amount=due)

    # The network call happens outside the DB transaction/lock.
    try:
        data = DarajaClient().stk_push(
            phone=phone,
            amount=due,
            account_reference=order.reference.split("-", 1)[-1].replace("-", ""),
            description="Harlem Store",
        )
    except MpesaError as exc:
        txn.status = MpesaTransaction.Status.FAILED
        txn.result_desc = str(exc)[:255]
        txn.save(update_fields=["status", "result_desc", "updated_at"])
        raise PaymentError(f"We couldn't send the M-Pesa prompt: {exc}", 502) from None

    txn.merchant_request_id = data.get("MerchantRequestID", "")
    txn.checkout_request_id = data["CheckoutRequestID"]
    txn.save(update_fields=["merchant_request_id", "checkout_request_id", "updated_at"])
    return txn, False


# --------------------------------------------------------------------------- results
def _parse_metadata(body: dict) -> dict:
    items = (body.get("CallbackMetadata") or {}).get("Item") or []
    return {i.get("Name"): i.get("Value") for i in items if isinstance(i, dict)}


def _parse_date(value) -> datetime | None:
    try:
        return datetime.strptime(str(int(value)), "%Y%m%d%H%M%S").replace(tzinfo=EAT)
    except (TypeError, ValueError):
        return None


def _record_success(txn: MpesaTransaction, *, receipt: str, paid: int, paid_at, via: str):
    payment = Payment.objects.create(
        order=txn.order,
        method=Payment.Method.MPESA,
        status=Payment.Status.CONFIRMED,
        amount=paid,
        reference=receipt,
        paid_at=paid_at or timezone.now(),
    )
    txn.payment = payment
    # Email the customer + owner and ping Telegram once this transaction commits (never twice: deduped).
    from apps.notifications.dispatch import payment_received  # local import: avoids an import cycle

    transaction.on_commit(lambda pid=payment.pk: payment_received(pid))
    txn.status = MpesaTransaction.Status.SUCCESS
    txn.mpesa_receipt = receipt
    txn.confirmed_via = via
    txn.transaction_date = paid_at
    order = Order.objects.get(pk=txn.order_id)
    if order.payment_status == Order.PaymentStatus.PAID and order.status == Order.Status.PENDING:
        order.change_status(Order.Status.CONFIRMED, note=f"Paid via M-Pesa {receipt}".strip())


def apply_result(checkout_request_id: str, result_code: int, result_desc: str, *,
                 body: dict | None = None, payload: dict | None = None, via: str) -> MpesaTransaction | None:
    """Single place where a Daraja result changes our records. Safe to call repeatedly."""
    S = MpesaTransaction.Status
    with transaction.atomic():
        txn = (
            MpesaTransaction.objects.select_for_update()
            .select_related("order")
            .filter(checkout_request_id=checkout_request_id)
            .first()
        )
        if txn is None:
            logger.warning("M-Pesa result for unknown CheckoutRequestID")
            return None

        if payload is not None:
            txn.callback_payload = payload

        # Late callback after we confirmed by query: just fill in the receipt.
        if txn.status == S.SUCCESS:
            if result_code == 0 and body is not None and not txn.mpesa_receipt:
                receipt = str(_parse_metadata(body).get("MpesaReceiptNumber") or "")
                txn.mpesa_receipt = receipt
                if txn.payment_id:
                    Payment.objects.filter(pk=txn.payment_id).update(reference=receipt)
            txn.save()
            return txn

        # Real money moved. Honour it even if we had already guessed "timeout"/"failed".
        if result_code == 0:
            if txn.payment_id:  # defensive: never double-credit
                return txn
            meta = _parse_metadata(body or {})
            receipt = str(meta.get("MpesaReceiptNumber") or "")
            needs_review = via == "callback" and not receipt
            try:
                amount = Decimal(str(meta["Amount"]))
                paid = int(amount.to_integral_value())
                if amount != txn.amount:
                    needs_review = True
                    logger.warning("M-Pesa amount mismatch on txn %s", txn.pk)
            except (KeyError, InvalidOperation):
                paid = txn.amount
                needs_review = needs_review or via == "callback"
            txn.result_code, txn.result_desc, txn.needs_review = 0, result_desc[:255], needs_review
            _record_success(txn, receipt=receipt, paid=paid, paid_at=_parse_date(meta.get("TransactionDate")), via=via)
            txn.save()
            return txn

        if txn.status not in (S.PENDING,):
            return txn  # already final; a failure result must not overwrite it
        txn.result_code, txn.result_desc = result_code, result_desc[:255]
        txn.status = (
            S.CANCELLED if result_code in CANCELLED_CODES else S.TIMEOUT if result_code in TIMEOUT_CODES else S.FAILED
        )
        txn.save()
        return txn


def handle_callback(payload: dict) -> MpesaTransaction | None:
    body = (payload.get("Body") or {}).get("stkCallback") if isinstance(payload, dict) else None
    if not isinstance(body, dict) or not body.get("CheckoutRequestID"):
        logger.warning("Malformed M-Pesa callback ignored")
        return None
    try:
        code = int(body.get("ResultCode"))
    except (TypeError, ValueError):
        logger.warning("M-Pesa callback without a numeric ResultCode ignored")
        return None
    return apply_result(
        body["CheckoutRequestID"], code, str(body.get("ResultDesc", "")), body=body, payload=payload, via="callback"
    )


# --------------------------------------------------------------------------- reconcile
def reconcile(txn: MpesaTransaction, *, force: bool = False) -> MpesaTransaction:
    """Ask Daraja what happened (used when the callback is late or lost)."""
    S = MpesaTransaction.Status
    if not txn.checkout_request_id:
        return txn
    if txn.status not in ((S.PENDING, S.TIMEOUT, S.FAILED) if force else (S.PENDING,)):
        return txn
    now = timezone.now()
    if not force and txn.last_queried_at and (now - txn.last_queried_at).total_seconds() < QUERY_MIN_GAP_SECONDS:
        return txn
    txn.last_queried_at = now
    txn.save(update_fields=["last_queried_at", "updated_at"])

    try:
        result = DarajaClient().stk_query(txn.checkout_request_id)
    except MpesaError:
        return txn  # try again next time
    if result is None:
        if not force and txn.status == S.PENDING and txn.age_seconds > GIVE_UP_SECONDS:
            txn.status = S.TIMEOUT
            txn.result_desc = "No response from M-Pesa."
            txn.save(update_fields=["status", "result_desc", "updated_at"])
        return txn
    updated = apply_result(txn.checkout_request_id, result["ResultCode"], result["ResultDesc"], via="query")
    return updated or txn


def reconcile_if_due(txn: MpesaTransaction) -> MpesaTransaction:
    if txn.status == MpesaTransaction.Status.PENDING and txn.age_seconds >= QUERY_AFTER_SECONDS:
        return reconcile(txn)
    return txn


def status_payload(txn: MpesaTransaction) -> dict:
    order = Order.objects.get(pk=txn.order_id)
    return {
        "checkout_request_id": txn.checkout_request_id,
        "status": txn.status,
        "message": friendly_message(txn),
        "receipt": txn.mpesa_receipt or None,
        "amount": txn.amount,
        "order": {
            "reference": order.reference,
            "status": order.status,
            "payment_status": order.payment_status,
            "balance_due": order.balance_due,
        },
    }
