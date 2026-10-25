import django_filters as df
from django.db.models import Q

from .models import Product


class ProductFilter(df.FilterSet):
    category = df.CharFilter(field_name="category__slug")
    q = df.CharFilter(method="filter_q", help_text="Search name, description and category.")
    min_price = df.NumberFilter(field_name="effective_price", lookup_expr="gte")
    max_price = df.NumberFilter(field_name="effective_price", lookup_expr="lte")
    in_stock = df.BooleanFilter(method="filter_in_stock")
    on_sale = df.BooleanFilter(method="filter_on_sale")
    featured = df.BooleanFilter(field_name="is_featured")
    bestseller = df.BooleanFilter(field_name="is_bestseller")
    ordering = df.OrderingFilter(
        fields=(
            ("effective_price", "price"),
            ("name", "name"),
            ("created_at", "newest"),
            ("sort_order", "featured"),
        )
    )

    class Meta:
        model = Product
        fields: list[str] = []

    def filter_q(self, qs, name, value):
        for term in value.strip()[:150].split():
            qs = qs.filter(
                Q(name__icontains=term) | Q(description__icontains=term) | Q(category__name__icontains=term)
            )
        return qs

    def filter_in_stock(self, qs, name, value):
        available = Q(track_inventory=False) | Q(has_stock=True)
        return qs.filter(available) if value else qs.exclude(available)

    def filter_on_sale(self, qs, name, value):
        return qs.filter(sale_price__isnull=not value)
