from django.contrib import admin, messages
from django.utils.html import format_html

from apps.core.admin_utils import export_as_csv

from .models import InvalidTransition, Order, OrderItem, OrderStatusHistory, Payment, PromoCode


@admin.register(PromoCode)
class PromoCodeAdmin(admin.ModelAdmin):
    list_display = ("code", "discount_type", "value", "first_purchase_only", "times_used", "usage_limit",
                    "valid_until", "is_active")
    list_filter = ("is_active", "discount_type", "first_purchase_only")
    list_editable = ("is_active",)
    search_fields = ("code", "description")


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    fields = ("product", "variant", "product_name", "size", "unit_price", "quantity", "customization")
    autocomplete_fields = ()
    raw_id_fields = ("product", "variant")


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    fields = ("method", "status", "amount", "reference", "paid_at")


class HistoryInline(admin.TabularInline):
    model = OrderStatusHistory
    extra = 0
    can_delete = False
    fields = ("created_at", "from_status", "to_status", "note", "changed_by")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


def _status_action(new_status, label):
    @admin.action(description=label)
    def run(modeladmin, request, queryset):
        done = 0
        for order in queryset:
            try:
                order.change_status(new_status, user=request.user, note="Changed from admin")
                done += 1
            except InvalidTransition as exc:
                modeladmin.message_user(request, f"{order.reference}: {exc}", messages.WARNING)
        if done:
            modeladmin.message_user(request, f"{done} order(s) updated.", messages.SUCCESS)

    run.__name__ = f"mark_{new_status}"
    return run


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    date_hierarchy = "created_at"
    list_display = ("reference", "customer_name", "phone", "status_badge", "payment_status", "total",
                    "delivery_method", "created_at")
    list_filter = ("status", "payment_status", "delivery_method", "created_at")
    search_fields = ("reference", "customer_name", "phone", "email")
    readonly_fields = ("reference", "status", "payment_status", "subtotal", "total", "promo_code_text",
                       "stock_reserved", "created_at", "updated_at")
    fieldsets = (
        ("Order", {"fields": ("reference", "status", "payment_status", "created_at")}),
        ("Customer", {"fields": ("customer_name", "phone", "email")}),
        ("Fulfilment", {"fields": ("delivery_method", "delivery_address", "notes", "internal_notes")}),
        ("Totals", {"fields": ("promo_code", "promo_code_text", "subtotal", "discount_total", "total")}),
    )
    inlines = [OrderItemInline, PaymentInline, HistoryInline]
    actions = [
        _status_action(Order.Status.CONFIRMED, "Mark as confirmed"),
        _status_action(Order.Status.PROCESSING, "Mark as processing"),
        _status_action(Order.Status.READY, "Mark as ready for delivery / collection"),
        _status_action(Order.Status.COMPLETED, "Mark as completed"),
        _status_action(Order.Status.CANCELLED, "Cancel (returns stock)"),
        export_as_csv,
    ]

    COLORS = {"pending": "#b45309", "confirmed": "#1d4ed8", "processing": "#6d28d9",
              "ready": "#0f766e", "completed": "#15803d", "cancelled": "#b91c1c"}

    @admin.display(description="Status", ordering="status")
    def status_badge(self, obj):
        return format_html('<b style="color:{}">{}</b>', self.COLORS.get(obj.status, "#444"), obj.get_status_display())

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        form.instance.recalculate_totals()  # keeps manual/phone orders consistent
