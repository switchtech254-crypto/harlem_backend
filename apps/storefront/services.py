from django.utils import timezone

from apps.catalog.selectors import product_queryset
from apps.catalog.serializers import ProductListSerializer

from .models import Deal


def serialize_deals(request):
    """Live deals with their (annotated) products; deals whose product is hidden are skipped."""
    deals = list(Deal.objects.live())
    products = {p.pk: p for p in product_queryset().filter(pk__in=[d.product_id for d in deals])}
    fallback_end = timezone.localtime().replace(hour=23, minute=59, second=59, microsecond=0)
    out = []
    for d in deals:
        product = products.get(d.product_id)
        if not product:
            continue
        out.append(
            {
                "id": d.pk,
                "badge": d.badge,
                "sold": d.sold,
                "available": d.available,
                "percent_sold": d.percent_sold,
                "ends_at": d.ends_at or fallback_end,
                "product": ProductListSerializer(product, context={"request": request}).data,
            }
        )
    return out
