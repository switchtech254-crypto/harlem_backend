from django.contrib import admin
from django.utils import timezone

from apps.core.admin_utils import export_as_csv

from .models import ContactMessage


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    date_hierarchy = "created_at"
    list_display = ("name", "kind", "phone", "email", "product", "status", "assigned_to", "created_at")
    list_filter = ("status", "kind", "assigned_to")
    list_editable = ("status", "assigned_to")
    search_fields = ("name", "phone", "email", "organisation", "subject", "message")
    readonly_fields = ("kind", "name", "phone", "email", "organisation", "subject", "message", "product",
                       "cart_snapshot", "created_at")
    actions = ["mark_in_progress", "mark_resolved", "mark_spam", export_as_csv]

    def has_add_permission(self, request):
        return False

    @admin.action(description="Mark as in progress (assign to me)")
    def mark_in_progress(self, request, qs):
        qs.update(status="in_progress", assigned_to=request.user, updated_at=timezone.now())

    @admin.action(description="Mark as resolved")
    def mark_resolved(self, request, qs):
        qs.update(status="resolved", updated_at=timezone.now())

    @admin.action(description="Mark as spam")
    def mark_spam(self, request, qs):
        qs.update(status="spam", updated_at=timezone.now())
