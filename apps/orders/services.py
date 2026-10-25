"""Server-authoritative cart pricing and order creation."""
import logging
from collections import defaultdict
from dataclasses import dataclass, field

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import F

from apps.catalog.models import Product, ProductVariant

from .models import Order, OrderItem, OrderStatusHistory, PromoCode, PromoError

logger = logging.getLogger(__name__)
MAX_LINES = 50


class CartError(Exception):
    def __init__(self, errors):
        self.errors = errors
        super().__init__("; ".join(e["message"] for e in errors))


@dataclass
class CartLine:
    product: Product
    variant: ProductVariant | None
    size: str
    quantity: int
    unit_price: int
    customization: dict

    @property
    def line_total(self):
        return self.unit_price * self.quantity


@dataclass
class PricedCart:
    lines: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    subtotal: int = 0
    discount: int = 0
    promo: PromoCode | None = None

    @property
    def total(self):
        return max(0, self.subtotal - self.discount)


def price_cart(items, *, promo_code="", phone="", email="", lock=False) -> PricedCart:
    """Validate items against the DB and price them. Never trusts client prices.
    `lock=True` (inside a transaction) row-locks variants and promo for safe checkout."""
    cart = PricedCart()
    merged: dict = {}
    for raw in items:
        key = (raw["id"], (raw.get("size") or "").strip())
        if key in merged:
            merged[key]["qty"] = min(99, merged[key]["qty"] + raw["qty"])
        else:
            merged[key] = {"qty": raw["qty"], "customization": raw.get("customization") or {}}

    products = {
        p.slug: p
        for p in Product.objects.filter(
            slug__in={k[0] for k in merged}, is_active=True, category__is_active=True
        ).prefetch_related("images")
    }
    vqs = ProductVariant.objects.filter(product_id__in=[p.pk for p in products.values()])
    if lock:
        vqs = vqs.select_for_update()
    by_product = defaultdict(list)
    for v in vqs:
        by_product[v.product_id].append(v)

    for (slug, size), data in merged.items():
        product = products.get(slug)
        if not product:
            cart.errors.append({"item": slug, "message": "This product is no longer available."})
            continue
        variants = by_product[product.pk]
        sized = [v for v in variants if v.size]
        variant = None
        if sized:
            variant = next((v for v in sized if v.size == size), None)
            if not variant:
                cart.errors.append({"item": slug, "message": f"Please choose a valid size for {product.name}."})
                continue
        elif variants:
            variant = variants[0]

        qty = data["qty"]
        label = f"{product.name} ({size})" if size else product.name
        if product.track_inventory:
            available = variant.stock if variant else 0
            if available <= 0:
                cart.errors.append({"item": slug, "message": f"{label} is out of stock."})
                continue
            if available < qty:
                cart.errors.append({"item": slug, "message": f"Only {available} left of {label}."})
                continue
        cart.lines.append(
            CartLine(product, variant, size if sized else "", qty, product.current_price, data["customization"])
        )

    cart.subtotal = sum(line.line_total for line in cart.lines)

    code = (promo_code or "").strip()
    if code and cart.lines:
        qs = PromoCode.objects.filter(code__iexact=code)
        if lock:
            qs = qs.select_for_update()
        promo = qs.first()
        if not promo:
            cart.errors.append({"item": "promo_code", "message": "That promo code isn't valid."})
        else:
            try:
                promo.validate_for(cart.subtotal, phone, email)
                cart.promo, cart.discount = promo, promo.discount_for(cart.subtotal)
            except PromoError as exc:
                cart.errors.append({"item": "promo_code", "message": str(exc)})
    return cart


@transaction.atomic
def create_order(*, customer: dict, items, promo_code="") -> Order:
    cart = price_cart(
        items, promo_code=promo_code, phone=customer["phone"], email=customer.get("email", ""), lock=True
    )
    if cart.errors or not cart.lines:
        raise CartError(cart.errors or [{"item": "items", "message": "Your cart is empty."}])

    order = Order.objects.create(
        **customer,
        promo_code=cart.promo,
        promo_code_text=cart.promo.code if cart.promo else "",
        subtotal=cart.subtotal,
        discount_total=cart.discount,
        total=cart.total,
        stock_reserved=True,
    )
    OrderItem.objects.bulk_create(
        [
            OrderItem(
                order=order, product=l.product, variant=l.variant, product_name=l.product.name,
                size=l.size, unit_price=l.unit_price, quantity=l.quantity, customization=l.customization,
            )
            for l in cart.lines
        ]
    )
    for l in cart.lines:
        if l.product.track_inventory and l.variant:
            updated = ProductVariant.objects.filter(pk=l.variant.pk, stock__gte=l.quantity).update(
                stock=F("stock") - l.quantity
            )
            if not updated:  # lost a race – roll the whole order back
                raise CartError([{"item": l.product.slug, "message": f"{l.product.name} just sold out."}])
    if cart.promo:
        PromoCode.objects.filter(pk=cart.promo.pk).update(times_used=F("times_used") + 1)
    OrderStatusHistory.objects.create(order=order, to_status=order.status, note="Order placed online")
    transaction.on_commit(lambda: notify_new_order(order.pk))
    return order


def notify_new_order(order_id):
    try:
        order = Order.objects.prefetch_related("items").get(pk=order_id)
        lines = "\n".join(
            f"- {i.quantity} × {i.product_name}{' (' + i.size + ')' if i.size else ''}: KSh {i.line_total:,}"
            for i in order.items.all()
        )
        body = (
            f"Order {order.reference}\nCustomer: {order.customer_name} ({order.phone})\n"
            f"{order.get_delivery_method_display()}: {order.delivery_address or '—'}\n\n{lines}\n\n"
            f"Discount: KSh {order.discount_total:,}\nTotal: KSh {order.total:,}\nNotes: {order.notes or '—'}"
        )
        if settings.STORE_NOTIFICATION_EMAILS:
            send_mail(f"New order {order.reference}", body, settings.DEFAULT_FROM_EMAIL,
                      settings.STORE_NOTIFICATION_EMAILS, fail_silently=True)
        if order.email:
            send_mail(
                f"We received your Harlem Store order {order.reference}",
                f"Hi {order.customer_name},\n\nThanks for your order. Our team will contact you to confirm "
                f"availability, delivery and payment.\n\n{body}",
                settings.DEFAULT_FROM_EMAIL, [order.email], fail_silently=True,
            )
    except Exception:  # never let email problems affect orders
        logger.exception("Failed to send order notification for %s", order_id)
