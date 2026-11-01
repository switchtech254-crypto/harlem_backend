from django.contrib import admin, messages

from apps.core.admin_utils import export_as_csv

from .models import MpesaTransaction
from .services import reconcile


@admin.register(MpesaTransaction)
class MpesaTransactionAdmin(admin.ModelAdmin):
    date_hierarchy = "created_at"
    list_display = ("created_at", "order", "phone", "amount", "status", "mpesa_receipt", "confirmed_via", "needs_review")
    list_filter = ("status", "needs_review", "confirmed_via")
    search_fields = ("order__reference", "phone", "mpesa_receipt", "checkout_request_id", "merchant_request_id")
    list_select_related = ("order",)
    actions = ["requery", export_as_csv]

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False  # financial records are kept

    @admin.action(description="Ask M-Pesa for the latest status (use if a callback was missed)")
    def requery(self, request, queryset):
        changed = 0
        for txn in queryset:
            before = txn.status
            txn = reconcile(txn, force=True)
            changed += txn.status != before
        self.message_user(request, f"Checked {queryset.count()} transaction(s); {changed} changed.", messages.INFO)
