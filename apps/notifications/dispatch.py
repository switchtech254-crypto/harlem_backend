"""Entry points called by the order / payment code. Everything here is best-effort and idempotent:
a failing email server or Telegram can never break checkout or a payment callback."""
import logging
import threading

from django.conf import settings
from django.db import close_old_connections, connection

from apps.orders.models import Order, Payment

from . import emails, telegram
from .models import NotificationLog

logger = logging.getLogger(__name__)


def _run(fn, *args):
    """Run off the request thread so Safaricom's callback / the customer's checkout is never slowed
    down by an SMTP server. (Tests run synchronously.)"""
    def target():
        try:
            fn(*args)
        except Exception:
            logger.exception("Notification dispatch failed")
        finally:
            connection.close()

    if settings.NOTIFICATIONS_ASYNC:
        threading.Thread(target=target, daemon=True, name="notifications").start()
    else:
        try:
            fn(*args)
        except Exception:
            logger.exception("Notification dispatch failed")


def deliver(*, key, order, event, channel, recipient, subject, send):
    """Send once. A key that already succeeded is skipped; a failed one is retried."""
    log, created = NotificationLog.objects.get_or_create(
        dedupe_key=key,
        defaults=dict(order=order, event=event, channel=channel, recipient=recipient, subject=subject[:255]),
    )
    if log.status == NotificationLog.Status.SENT:
        return log
    try:
        send()
        log.status, log.error = NotificationLog.Status.SENT, ""
    except Exception as exc:  # network, auth, rejected recipient...
        log.status, log.error = NotificationLog.Status.FAILED, str(exc)[:500]
        logger.warning("Notification %s to %s failed: %s", event, recipient, type(exc).__name__)
    log.save(update_fields=["status", "error", "updated_at"])
    return log


def _owner_recipients() -> list[str]:
    return list(settings.STORE_NOTIFICATION_EMAILS)


def _notify(order: Order, kind: str, ctx: dict, *, id_part: str):
    """kind: 'placed' (order created) or 'payment' (money received)."""
    # 1) customer email
    if order.email:
        mail = emails.customer_email(order, kind, ctx)
        deliver(key=f"{id_part}:email:customer", order=order, event=f"{kind}_customer", channel="email",
                recipient=order.email, subject=mail["subject"], send=lambda m=mail: emails.send_email(**m))
    # 2) owner email(s)
    for to in _owner_recipients():
        mail = emails.owner_email(order, kind, ctx, [to])
        deliver(key=f"{id_part}:email:owner:{to}", order=order, event=f"{kind}_owner", channel="email",
                recipient=to, subject=mail["subject"], send=lambda m=mail: emails.send_email(**m))
    # 3) Telegram
    if telegram.is_configured():
        text = emails.telegram_text(order, kind, ctx)
        for chat in telegram.chat_ids():
            deliver(key=f"{id_part}:telegram:{chat}", order=order, event=f"{kind}_telegram", channel="telegram",
                    recipient=f"telegram:{chat}", subject=text.split("\n")[0][:255],
                    send=lambda c=chat, t=text: telegram.send_message(c, t))


# ---- public hooks ---------------------------------------------------------------------------
def _order_placed(order_id: int):
    order = Order.objects.prefetch_related("items").get(pk=order_id)
    ctx = emails.build_context(order)
    _notify(order, "placed", ctx, id_part=f"order:{order.pk}:placed")


def _payment_received(payment_id: int):
    payment = Payment.objects.select_related("order").get(pk=payment_id)
    if payment.status != Payment.Status.CONFIRMED:
        return
    order = Order.objects.prefetch_related("items").get(pk=payment.order_id)
    txn = getattr(payment, "mpesa_transaction", None)
    ctx = emails.build_context(order, payment=payment, txn=txn)
    _notify(order, "payment", ctx, id_part=f"payment:{payment.pk}")


def order_placed(order_id: int):
    _run(_order_placed, order_id)


def payment_received(payment_id: int):
    _run(_payment_received, payment_id)


def retry(log: NotificationLog):
    """Re-run the whole event that `log` belongs to; messages that were already sent are skipped."""
    close_old_connections()
    parts = log.dedupe_key.split(":")
    if parts[0] == "order":
        _order_placed(int(parts[1]))
    elif parts[0] == "payment":
        _payment_received(int(parts[1]))
