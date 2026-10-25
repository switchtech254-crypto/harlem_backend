from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class ContactMessage(TimeStampedModel):
    class Kind(models.TextChoices):
        GENERAL = "general", "General enquiry"
        ORDER = "order", "Place / discuss an order"
        TEAM = "team", "Team / club kit"
        BRANDING = "branding", "Custom branding"
        PRODUCT = "product", "Product question"
        DELIVERY = "delivery", "Delivery"

    class Status(models.TextChoices):
        NEW = "new", "New"
        IN_PROGRESS = "in_progress", "In progress"
        RESOLVED = "resolved", "Resolved"
        SPAM = "spam", "Spam"

    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.GENERAL)
    name = models.CharField(max_length=120)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    organisation = models.CharField(max_length=120, blank=True, help_text="Club / school / company")
    subject = models.CharField(max_length=150, blank=True)
    message = models.TextField(max_length=3000)
    product = models.ForeignKey("catalog.Product", null=True, blank=True, on_delete=models.SET_NULL)
    cart_snapshot = models.JSONField(default=list, blank=True, help_text="Items the customer had in their cart.")

    status = models.CharField(max_length=12, choices=Status.choices, default=Status.NEW, db_index=True)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    internal_notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_kind_display()} from {self.name}"
