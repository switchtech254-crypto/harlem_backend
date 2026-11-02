from django.db import models

from apps.core.models import TimeStampedModel


class NotificationLog(TimeStampedModel):
    """One row per message we tried to send, so a failed email/Telegram is never silent.
    `dedupe_key` makes sending idempotent: a repeated payment callback cannot send a second email."""

    class Channel(models.TextChoices):
        EMAIL = "email", "Email"
        TELEGRAM = "telegram", "Telegram"

    class Status(models.TextChoices):
        PENDING = "pending", "Sending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    order = models.ForeignKey("orders.Order", on_delete=models.CASCADE, related_name="notifications")
    event = models.CharField(max_length=40, help_text="e.g. payment_customer, payment_owner, order_owner")
    channel = models.CharField(max_length=10, choices=Channel.choices)
    recipient = models.CharField(max_length=254)
    subject = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    error = models.TextField(blank=True)
    dedupe_key = models.CharField(max_length=160, unique=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_channel_display()} · {self.event} · {self.recipient} · {self.get_status_display()}"
