from django.contrib import admin
from django.shortcuts import redirect
from django.urls import reverse

from .models import Banner, Deal, HeroSlide, ServiceHighlight, SiteSettings, Testimonial


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return not SiteSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        obj = SiteSettings.get_solo()
        return redirect(reverse("admin:storefront_sitesettings_change", args=[obj.pk]))


@admin.register(HeroSlide)
class HeroSlideAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "sort_order", "is_active", "starts_at", "ends_at")
    list_editable = ("sort_order", "is_active")


@admin.register(Banner)
class BannerAdmin(admin.ModelAdmin):
    list_display = ("heading", "placement", "sort_order", "is_active", "starts_at", "ends_at")
    list_filter = ("placement", "is_active")
    list_editable = ("sort_order", "is_active")


@admin.register(ServiceHighlight)
class ServiceHighlightAdmin(admin.ModelAdmin):
    list_display = ("title", "text", "icon", "sort_order", "is_active")
    list_editable = ("sort_order", "is_active")


@admin.register(Testimonial)
class TestimonialAdmin(admin.ModelAdmin):
    list_display = ("author", "role", "sort_order", "is_active")
    list_editable = ("sort_order", "is_active")


@admin.register(Deal)
class DealAdmin(admin.ModelAdmin):
    list_display = ("product", "badge", "sold", "available", "ends_at", "sort_order", "is_active")
    list_editable = ("sold", "available", "sort_order", "is_active")
    raw_id_fields = ("product",)
