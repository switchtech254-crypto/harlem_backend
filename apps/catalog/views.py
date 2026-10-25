from django.db.models import Count, Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from .filters import ProductFilter
from .models import Category, Review
from .selectors import product_queryset
from .serializers import (
    CategorySerializer, ProductDetailSerializer, ProductListSerializer,
    ReviewCreateSerializer, ReviewSerializer,
)


class CategoryViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [AllowAny]
    authentication_classes: list = []
    serializer_class = CategorySerializer
    lookup_field = "slug"
    pagination_class = None
    filter_backends: list = []

    def get_queryset(self):
        return Category.objects.filter(is_active=True).annotate(
            product_count=Count("products", filter=Q(products__is_active=True))
        )


class ProductViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [AllowAny]
    authentication_classes: list = []
    lookup_field = "slug"
    filterset_class = ProductFilter

    def get_queryset(self):
        return product_queryset()

    def get_serializer_class(self):
        return ProductDetailSerializer if self.action == "retrieve" else ProductListSerializer

    def get_throttles(self):
        if self.action == "reviews" and self.request.method == "POST":
            self.throttle_scope = "reviews"
            return [ScopedRateThrottle()]
        return super().get_throttles()

    @action(detail=True, url_path="related")
    def related(self, request, slug=None):
        """Same-category products first, topped up from the rest (max 4)."""
        product = self.get_object()
        others = list(product_queryset().exclude(pk=product.pk))
        others.sort(key=lambda p: p.category_id != product.category_id)
        data = ProductListSerializer(others[:4], many=True, context={"request": request}).data
        return Response(data)

    @action(detail=True, methods=["get", "post"], url_path="reviews")
    def reviews(self, request, slug=None):
        product = self.get_object()
        if request.method == "POST":
            ser = ReviewCreateSerializer(data=request.data)
            ser.is_valid(raise_exception=True)
            ser.save(product=product, is_approved=False)
            return Response(
                {"detail": "Thanks! Your review will appear once it has been approved."},
                status=status.HTTP_201_CREATED,
            )
        qs = Review.objects.filter(product=product, is_approved=True)[:50]
        return Response(ReviewSerializer(qs, many=True).data)
