from django.contrib import admin
from django.db.models import Sum
from django.utils.html import format_html

from apps.core.admin_utils import export_as_csv

from .models import Category, Product, ProductImage, ProductVariant, Review


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "sort_order", "is_active")
    list_editable = ("sort_order", "is_active")
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name", "slug")


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1
    fields = ("image", "alt_text", "sort_order")


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 0
    fields = ("size", "sku", "stock", "sort_order")


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "thumb", "name", "category", "price", "sale_price", "stock_total",
        "is_active", "is_featured", "is_bestseller",
    )
    list_display_links = ("thumb", "name")
    list_editable = ("price", "sale_price", "is_active", "is_featured", "is_bestseller")
    list_filter = ("category", "is_active", "is_featured", "is_bestseller", "track_inventory")
    list_select_related = ("category",)
    search_fields = ("name", "slug", "description", "variants__sku")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [ProductImageInline, ProductVariantInline]
    actions = ["activate", "deactivate", export_as_csv]
    fieldsets = (
        (None, {"fields": ("name", "slug", "category", "description")}),
        ("Pricing", {"fields": ("price", "sale_price")}),
        ("Merchandising", {"fields": ("badge", "is_active", "is_featured", "is_bestseller", "sort_order")}),
        ("Inventory", {"fields": ("track_inventory",)}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("images").annotate(_stock=Sum("variants__stock"))

    @admin.display(description="", ordering=None)
    def thumb(self, obj):
        img = next(iter(obj.images.all()), None)
        return format_html('<img src="{}" height="44" style="border-radius:4px">', img.image.url) if img else "—"

    @admin.display(description="Stock", ordering="_stock")
    def stock_total(self, obj):
        return "∞" if not obj.track_inventory else (obj._stock or 0)

    @admin.action(description="Mark selected as active")
    def activate(self, request, qs):
        qs.update(is_active=True)

    @admin.action(description="Mark selected as inactive")
    def deactivate(self, request, qs):
        qs.update(is_active=False)


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ("product", "rating", "name", "is_approved", "created_at")
    list_filter = ("is_approved", "rating")
    list_editable = ("is_approved",)
    search_fields = ("product__name", "name", "comment")
    actions = ["approve"]

    @admin.action(description="Approve selected reviews")
    def approve(self, request, qs):
        qs.update(is_approved=True)
