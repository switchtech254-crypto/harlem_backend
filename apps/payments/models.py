from django.db import models
from django.utils import timezone

from apps.core.models import TimeStampedModel


class MpesaTransaction(TimeStampedModel):
    """One M-Pesa Express (STK push) attempt. An order can have several (retries)."""

    class Status(models.TextChoices):
        PENDING = "pending", "Waiting for customer"
        SUCCESS = "success", "Paid"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled by customer"
        TIMEOUT = "timeout", "No response"

    order = models.ForeignKey("orders.Order", on_delete=models.PROTECT, related_name="mpesa_transactions")
    phone = models.CharField(max_length=20, help_text="Number that received the prompt (+2547...).")
    amount = models.PositiveIntegerField(help_text="KSh requested.")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)

    merchant_request_id = models.CharField(max_length=80, blank=True)
    checkout_request_id = models.CharField(max_length=80, null=True, blank=True, db_index=True)

    result_code = models.IntegerField(null=True, blank=True)
    result_desc = models.CharField(max_length=255, blank=True)
    mpesa_receipt = models.CharField(max_length=30, blank=True)
    transaction_date = models.DateTimeField(null=True, blank=True)
    confirmed_via = models.CharField(max_length=10, blank=True, help_text="callback or query")
    needs_review = models.BooleanField(
        default=False, help_text="Amount mismatch or missing receipt: check against the M-Pesa statement."
    )

    callback_payload = models.JSONField(null=True, blank=True)
    last_queried_at = models.DateTimeField(null=True, blank=True)
    payment = models.OneToOneField(
        "orders.Payment", null=True, blank=True, on_delete=models.SET_NULL, related_name="mpesa_transaction"
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["checkout_request_id"],
                condition=models.Q(checkout_request_id__isnull=False),
                name="unique_mpesa_checkout_request_id",
            )
        ]
        indexes = [models.Index(fields=["order", "status"])]

    def __str__(self):
        return f"{self.order.reference} · KSh {self.amount:,} · {self.get_status_display()}"

    @property
    def age_seconds(self) -> float:
        return (timezone.now() - self.created_at).total_seconds()
