"""Builds the customer / owner emails (HTML + plain text) and Telegram texts from an order."""
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone

from apps.orders.models import Order
from apps.storefront.models import SiteSettings

from .telegram import esc


def kes(amount) -> str:
    return f"KSh {int(amount):,}"


def when(dt) -> str:
    return timezone.localtime(dt).strftime("%d %b %Y, %H:%M") if dt else ""


def _wa_link(number: str) -> str:
    digits = "".join(c for c in (number or "") if c.isdigit())
    return f"https://wa.me/{digits}" if len(digits) >= 9 else ""


def build_context(order: Order, *, payment=None, txn=None) -> dict:
    site = SiteSettings.get_solo()
    frontend = settings.FRONTEND_URL.rstrip("/")
    items = [
        {
            "name": i.product_name,
            "size": i.size,
            "qty": i.quantity,
            "unit": kes(i.unit_price),
            "total": kes(i.line_total),
            "custom": ", ".join(f"{k}: {v}" for k, v in (i.customization or {}).items() if v),
        }
        for i in order.items.all()
    ]
    paid = order.amount_paid
    return {
        "order": order,
        "reference": order.reference,
        "customer_name": order.customer_name,
        "first_name": (order.customer_name or "there").split()[0],
        "items": items,
        "subtotal": kes(order.subtotal),
        "discount": kes(order.discount_total) if order.discount_total else "",
        "promo": order.promo_code_text,
        "total": kes(order.total),
        "paid": kes(paid),
        "balance": kes(order.balance_due),
        "is_paid": order.payment_status == Order.PaymentStatus.PAID,
        "delivery_method": order.get_delivery_method_display(),
        "is_collection": order.delivery_method == Order.DeliveryMethod.COLLECTION,
        "delivery_address": order.delivery_address,
        "notes": order.notes,
        "placed_at": when(order.created_at),
        "payment_amount": kes(payment.amount) if payment else "",
        "payment_receipt": (payment.reference if payment else "") or "",
        "payment_time": when(payment.paid_at) if payment else "",
        "payment_phone": txn.phone if txn else "",
        "confirmed_via": txn.confirmed_via if txn else "",
        "needs_review": bool(txn and txn.needs_review),
        "tracking_url": f"{frontend}/track?ref={order.reference}&t={order.tracking_token}",
        "returns_url": f"{frontend}/returns-exchanges",
        "shop_url": frontend,
        "admin_url": f"{settings.BACKEND_PUBLIC_URL.rstrip('/')}/admin/orders/order/{order.pk}/change/",
        "owner_email_subject_amount": kes(payment.amount) if payment else kes(order.total),
        "customer_email": order.email,
        "customer_phone": order.phone,
        "store": {
            "name": site.store_name,
            "phone": site.contact_phone,
            "whatsapp": site.whatsapp_number,
            "whatsapp_link": _wa_link(site.whatsapp_number),
            "email": settings.SUPPORT_EMAIL or site.contact_email,
            "address": site.address,
            "hours": site.opening_hours,
        },
    }


def _render(name: str, ctx: dict):
    return (
        render_to_string(f"notifications/{name}.txt", ctx),
        render_to_string(f"notifications/{name}.html", ctx),
    )


def send_email(*, subject: str, to: list[str], text: str, html: str, from_email: str, reply_to=None) -> None:
    msg = EmailMultiAlternatives(subject, text, from_email, to, reply_to=reply_to or None)
    msg.attach_alternative(html, "text/html")
    msg.send(fail_silently=False)


# ---- customer
def customer_email(order: Order, kind: str, ctx: dict) -> dict:
    ctx = {**ctx, "kind": kind}
    text, html = _render("customer_order", ctx)
    if kind == "payment":
        subject = f"Payment received · Order {order.reference} · {ctx['store']['name']}"
        sender = settings.PAYMENTS_FROM_EMAIL
    else:
        subject = f"We received your order {order.reference} · {ctx['store']['name']}"
        sender = settings.DEFAULT_FROM_EMAIL
    reply_to = [ctx["store"]["email"]] if ctx["store"]["email"] else None
    return dict(subject=subject, to=[order.email], text=text, html=html, from_email=sender, reply_to=reply_to)


# ---- owner
def owner_email(order: Order, kind: str, ctx: dict, to: list[str]) -> dict:
    ctx = {**ctx, "kind": kind}
    text, html = _render("owner_order", ctx)
    if kind == "payment":
        subject = f"Payment received: {ctx['payment_amount']} · Order {order.reference} ({order.customer_name})"
        sender = settings.PAYMENTS_FROM_EMAIL
    else:
        subject = f"New order {order.reference}: {ctx['total']} ({order.customer_name})"
        sender = settings.DEFAULT_FROM_EMAIL
    return dict(subject=subject, to=to, text=text, html=html, from_email=sender,
                reply_to=[order.email] if order.email else None)


# ---- Telegram text
def telegram_text(order: Order, kind: str, ctx: dict) -> str:
    lines = [
        ("✅ <b>Payment received</b>" if kind == "payment" else "🛒 <b>New order</b>") + f" · <code>{esc(order.reference)}</code>",
    ]
    if kind == "payment":
        lines.append(f"💰 <b>{esc(ctx['payment_amount'])}</b> via M-Pesa" + (f" · receipt <code>{esc(ctx['payment_receipt'])}</code>" if ctx["payment_receipt"] else ""))
        lines.append(f"Order is now: <b>{esc(order.get_payment_status_display())}</b>, {esc(order.get_status_display())}")
        if ctx["needs_review"]:
            lines.append("⚠️ Amount/receipt needs checking against the M-Pesa statement.")
    else:
        lines.append(f"Total: <b>{esc(ctx['total'])}</b> · {esc(ctx['delivery_method'])} · {esc(order.get_payment_status_display())}")
    lines.append("")
    lines.append(f"👤 {esc(order.customer_name)} · {esc(order.phone)}")
    if order.delivery_address:
        lines.append(f"📍 {esc(order.delivery_address)}")
    lines.append("")
    for i in ctx["items"][:12]:
        size = f" ({esc(i['size'])})" if i["size"] else ""
        extra = f" — {esc(i['custom'])}" if i["custom"] else ""
        lines.append(f"• {i['qty']} × {esc(i['name'])}{size}{extra} — {esc(i['total'])}")
    if len(ctx["items"]) > 12:
        lines.append(f"…and {len(ctx['items']) - 12} more")
    if ctx["discount"]:
        lines.append(f"Discount: {esc(ctx['discount'])} ({esc(ctx['promo'])})")
    if order.notes:
        lines.append(f"📝 {esc(order.notes[:300])}")
    lines.append("")
    lines.append(f'<a href="{esc(ctx["admin_url"])}">Open in admin</a>')
    return "\n".join(lines)
