from django.contrib import admin, messages

from .dispatch import retry
from .models import NotificationLog


@admin.register(NotificationLog)
class NotificationLogAdmin(admin.ModelAdmin):
    date_hierarchy = "created_at"
    list_display = ("created_at", "order", "event", "channel", "recipient", "status")
    list_filter = ("status", "channel", "event")
    search_fields = ("order__reference", "recipient", "subject", "error")
    list_select_related = ("order",)
    actions = ["resend"]

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="Retry sending (messages already sent are skipped)")
    def resend(self, request, queryset):
        for log in queryset.exclude(status=NotificationLog.Status.SENT):
            retry(log)
        failed = queryset.filter(status=NotificationLog.Status.FAILED).count()
        self.message_user(
            request, "Retried. " + (f"{failed} still failing: check the error column." if failed else "All sent."),
            messages.WARNING if failed else messages.SUCCESS,
        )
