from django.db.models import Count, Q
from django.utils import timezone
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import Category
from apps.catalog.selectors import bestsellers, featured_products
from apps.catalog.serializers import CategorySerializer, ProductListSerializer

from .models import Banner, HeroSlide, ServiceHighlight, SiteSettings, Testimonial
from .serializers import (
    BannerSerializer, HeroSlideSerializer, ServiceSerializer, SiteSettingsSerializer, TestimonialSerializer,
)
from .services import serialize_deals


class PublicView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []


class SiteSettingsView(PublicView):
    def get(self, request):
        return Response(SiteSettingsSerializer(SiteSettings.get_solo()).data)


class DealsView(PublicView):
    def get(self, request):
        return Response({"server_time": timezone.now(), "results": serialize_deals(request)})


class HomepageView(PublicView):
    """One request returns everything HomeClient renders."""

    def get(self, request):
        ctx = {"request": request}
        banners = {}
        for b in Banner.objects.live():
            banners.setdefault(b.placement, b)  # first active per placement wins
        deals = serialize_deals(request)
        categories = Category.objects.filter(is_active=True).annotate(
            product_count=Count("products", filter=Q(products__is_active=True))
        )
        return Response(
            {
                "server_time": timezone.now(),
                "settings": SiteSettingsSerializer(SiteSettings.get_solo()).data,
                "hero_slides": HeroSlideSerializer(HeroSlide.objects.live().select_related("category"),
                                                   many=True, context=ctx).data,
                "banners": {k: BannerSerializer(v, context=ctx).data for k, v in banners.items()},
                "services": ServiceSerializer(ServiceHighlight.objects.filter(is_active=True), many=True).data,
                "featured_products": ProductListSerializer(featured_products(8), many=True, context=ctx).data,
                "categories": CategorySerializer(categories, many=True, context=ctx).data,
                "bestsellers": ProductListSerializer(bestsellers(8), many=True, context=ctx).data,
                "featured_deals": deals[:3],
                "deals": deals,
                "testimonials": TestimonialSerializer(Testimonial.objects.filter(is_active=True), many=True).data,
            }
        )
