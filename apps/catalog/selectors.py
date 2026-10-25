from datetime import timedelta

from django.db.models import Avg, Count, Exists, OuterRef, Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from .models import Product, ProductVariant


def product_queryset():
    """Public, annotated, prefetched product queryset (avoids N+1 in serializers)."""
    has_stock = ProductVariant.objects.filter(product=OuterRef("pk"), stock__gt=0)
    return (
        Product.objects.filter(is_active=True, category__is_active=True)
        .select_related("category")
        .prefetch_related("images", "variants")
        .annotate(
            effective_price=Coalesce("sale_price", "price"),
            has_stock=Exists(has_stock),
            rating=Avg("reviews__rating", filter=Q(reviews__is_approved=True)),
            review_count=Count("reviews", filter=Q(reviews__is_approved=True)),
        )
        .order_by("sort_order", "name")  # aggregates drop Meta.ordering, so set it explicitly
    )


def featured_products(limit=8):
    return list(product_queryset().filter(is_featured=True)[:limit])


def bestsellers(limit=8):
    """Pinned bestsellers first, then topped up with real sales from the last 90 days."""
    from apps.orders.models import Order, OrderItem

    chosen = list(product_queryset().filter(is_bestseller=True)[:limit])
    if len(chosen) < limit:
        since = timezone.now() - timedelta(days=90)
        top_ids = list(
            OrderItem.objects.filter(product__isnull=False, order__created_at__gte=since)
            .exclude(order__status=Order.Status.CANCELLED)
            .values("product_id")
            .annotate(units=Sum("quantity"))
            .order_by("-units")
            .values_list("product_id", flat=True)[: limit * 2]
        )
        taken = {p.pk for p in chosen}
        extra = {p.pk: p for p in product_queryset().filter(pk__in=top_ids).exclude(pk__in=taken)}
        for pk in top_ids:
            if pk in extra and len(chosen) < limit:
                chosen.append(extra[pk])
    return chosen
