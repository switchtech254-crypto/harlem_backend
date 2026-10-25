import secrets

from django.conf import settings
from django.db import models, transaction
from django.db.models import F, Q, Sum
from django.db.models.functions import Greatest
from django.utils import timezone

from apps.core.models import TimeStampedModel

_REF_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def generate_reference():
    stamp = timezone.localdate().strftime("%y%m%d")
    return f"HS-{stamp}-" + "".join(secrets.choice(_REF_ALPHABET) for _ in range(5))


class PromoError(Exception):
    pass


class InvalidTransition(Exception):
    pass


class PromoCode(TimeStampedModel):
    class DiscountType(models.TextChoices):
        PERCENT = "percent", "Percentage"
        FIXED = "fixed", "Fixed amount (KSh)"

    code = models.CharField(max_length=32, unique=True, help_text="Stored in upper case, e.g. HARLEM10.")
    description = models.CharField(max_length=200, blank=True)
    discount_type = models.CharField(max_length=10, choices=DiscountType.choices, default=DiscountType.PERCENT)
    value = models.PositiveIntegerField(help_text="Percent (1-100) or KSh amount.")
    max_discount = models.PositiveIntegerField(null=True, blank=True, help_text="Cap in KSh for percentage codes.")
    min_order_amount = models.PositiveIntegerField(default=0)
    first_purchase_only = models.BooleanField(default=False)
    usage_limit = models.PositiveIntegerField(null=True, blank=True, help_text="Blank = unlimited.")
    times_used = models.PositiveIntegerField(default=0, editable=False)
    valid_from = models.DateTimeField(null=True, blank=True)
    valid_until = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.code

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()
        super().save(*args, **kwargs)

    def discount_for(self, subtotal: int) -> int:
        if self.discount_type == self.DiscountType.PERCENT:
            amount = subtotal * min(self.value, 100) // 100
            if self.max_discount is not None:
                amount = min(amount, self.max_discount)
        else:
            amount = self.value
        return max(0, min(amount, subtotal))

    def validate_for(self, subtotal: int, phone: str = "", email: str = ""):
        now = timezone.now()
        if not self.is_active:
            raise PromoError("This promo code is not active.")
        if self.valid_from and now < self.valid_from:
            raise PromoError("This promo code is not valid yet.")
        if self.valid_until and now > self.valid_until:
            raise PromoError("This promo code has expired.")
        if self.usage_limit is not None and self.times_used >= self.usage_limit:
            raise PromoError("This promo code has been fully redeemed.")
        if subtotal < self.min_order_amount:
            raise PromoError(f"Orders must be at least KSh {self.min_order_amount:,} to use this code.")
        if self.first_purchase_only and (phone or email):
            who = Q()
            if phone:
                who |= Q(phone=phone)
            if email:
                who |= Q(email__iexact=email)
            if Order.objects.exclude(status=Order.Status.CANCELLED).filter(who).exists():
                raise PromoError("This code is only valid on a first purchase.")


class Order(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        CONFIRMED = "confirmed", "Confirmed"
        PROCESSING = "processing", "Processing"
        READY = "ready", "Ready for delivery / collection"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    class DeliveryMethod(models.TextChoices):
        DELIVERY = "delivery", "Delivery"
        COLLECTION = "collection", "Collection"

    class PaymentStatus(models.TextChoices):
        UNPAID = "unpaid", "Unpaid"
        PARTIAL = "partial", "Partially paid"
        PAID = "paid", "Paid"

    TRANSITIONS = {
        Status.PENDING: {Status.CONFIRMED, Status.CANCELLED},
        Status.CONFIRMED: {Status.PROCESSING, Status.READY, Status.CANCELLED},
        Status.PROCESSING: {Status.READY, Status.CANCELLED},
        Status.READY: {Status.COMPLETED, Status.CANCELLED},
        Status.COMPLETED: set(),
        Status.CANCELLED: set(),
    }

    reference = models.CharField(max_length=20, unique=True, editable=False)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True)
    payment_status = models.CharField(max_length=10, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID)

    customer_name = models.CharField(max_length=120)
    phone = models.CharField(max_length=20, db_index=True)
    email = models.EmailField(blank=True)
    delivery_method = models.CharField(max_length=12, choices=DeliveryMethod.choices, default=DeliveryMethod.DELIVERY)
    delivery_address = models.CharField(max_length=300, blank=True)
    notes = models.TextField(blank=True, help_text="Customer notes.")
    internal_notes = models.TextField(blank=True, help_text="Staff only.")

    promo_code = models.ForeignKey(PromoCode, null=True, blank=True, on_delete=models.SET_NULL, related_name="orders")
    promo_code_text = models.CharField(max_length=32, blank=True, editable=False)
    subtotal = models.PositiveIntegerField(default=0)
    discount_total = models.PositiveIntegerField(default=0)
    total = models.PositiveIntegerField(default=0)
    stock_reserved = models.BooleanField(default=False, editable=False)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "-created_at"])]

    def __str__(self):
        return self.reference

    def save(self, *args, **kwargs):
        if not self.reference:
            ref = generate_reference()
            while Order.objects.filter(reference=ref).exists():
                ref = generate_reference()
            self.reference = ref
        super().save(*args, **kwargs)

    # ---- money
    def recalculate_totals(self):
        self.subtotal = sum(i.unit_price * i.quantity for i in self.items.all())
        self.total = max(0, self.subtotal - self.discount_total)
        self.save(update_fields=["subtotal", "total", "updated_at"])
        self.refresh_payment_status()

    @property
    def amount_paid(self):
        return self.payments.filter(status=Payment.Status.CONFIRMED).aggregate(s=Sum("amount"))["s"] or 0

    @property
    def balance_due(self):
        return max(0, self.total - self.amount_paid)

    def refresh_payment_status(self):
        paid = self.amount_paid
        if paid <= 0:
            new = self.PaymentStatus.UNPAID
        elif paid >= self.total:
            new = self.PaymentStatus.PAID
        else:
            new = self.PaymentStatus.PARTIAL
        if new != self.payment_status:
            self.payment_status = new
            self.save(update_fields=["payment_status", "updated_at"])

    # ---- workflow
    @transaction.atomic
    def change_status(self, new_status, *, user=None, note=""):
        if new_status == self.status:
            return
        if new_status not in self.TRANSITIONS[self.Status(self.status)]:
            raise InvalidTransition(
                f"Cannot move an order from '{self.get_status_display()}' to '{self.Status(new_status).label}'."
            )
        old = self.status
        if new_status == self.Status.CANCELLED:
            self._release_stock_and_promo()
        self.status = new_status
        self.save(update_fields=["status", "stock_reserved", "updated_at"])
        OrderStatusHistory.objects.create(
            order=self, from_status=old, to_status=new_status, note=note, changed_by=user
        )

    def _release_stock_and_promo(self):
        from apps.catalog.models import ProductVariant

        if self.stock_reserved:
            for item in self.items.select_related("product"):
                if item.variant_id and item.product_id and item.product.track_inventory:
                    ProductVariant.objects.filter(pk=item.variant_id).update(stock=F("stock") + item.quantity)
            self.stock_reserved = False
        if self.promo_code_id:
            PromoCode.objects.filter(pk=self.promo_code_id).update(times_used=Greatest(F("times_used") - 1, 0))


class OrderItem(models.Model):
    """Snapshot of what was sold – survives later product edits/deletes."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey("catalog.Product", null=True, blank=True, on_delete=models.SET_NULL)
    variant = models.ForeignKey("catalog.ProductVariant", null=True, blank=True, on_delete=models.SET_NULL)
    product_name = models.CharField(max_length=200, blank=True)
    size = models.CharField(max_length=20, blank=True)
    unit_price = models.PositiveIntegerField(default=0, help_text="KSh per item at time of order.")
    quantity = models.PositiveIntegerField(default=1)
    customization = models.JSONField(default=dict, blank=True, help_text="e.g. name / number / badge for jerseys.")

    @property
    def line_total(self):
        return self.unit_price * self.quantity

    def save(self, *args, **kwargs):
        if self.product_id:
            if not self.product_name:
                self.product_name = self.product.name
            if not self.unit_price:
                self.unit_price = self.product.current_price
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.quantity} × {self.product_name}"


class OrderStatusHistory(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="history")
    from_status = models.CharField(max_length=12, blank=True)
    to_status = models.CharField(max_length=12)
    note = models.CharField(max_length=300, blank=True)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        verbose_name_plural = "status history"


class Payment(TimeStampedModel):
    class Method(models.TextChoices):
        MPESA = "mpesa", "M-Pesa"
        CASH = "cash", "Cash"
        CARD = "card", "Card"
        BANK = "bank", "Bank transfer"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        CONFIRMED = "confirmed", "Confirmed"
        FAILED = "failed", "Failed"

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="payments")
    method = models.CharField(max_length=10, choices=Method.choices, default=Method.MPESA)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.CONFIRMED)
    amount = models.PositiveIntegerField(help_text="KSh")
    reference = models.CharField(max_length=60, blank=True, help_text="M-Pesa receipt / bank ref.")
    paid_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-paid_at"]

    def __str__(self):
        return f"{self.get_method_display()} KSh {self.amount:,} ({self.order.reference})"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.order.refresh_payment_status()

    def delete(self, *args, **kwargs):
        order = self.order
        super().delete(*args, **kwargs)
        order.refresh_payment_status()
