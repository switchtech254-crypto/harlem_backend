from datetime import timedelta

from django.conf import settings
from django.db import connection
from django.db.models import Count, F, Sum
from django.utils import timezone
from rest_framework.permissions import AllowAny, IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = []

    def get(self, request):
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
        return Response({"status": "ok"})


class DashboardView(APIView):
    """Staff-only snapshot for custom dashboards (session-authenticated staff)."""

    permission_classes = [IsAdminUser]

    def get(self, request):
        from apps.catalog.models import ProductVariant, Review
        from apps.contact.models import ContactMessage
        from apps.orders.models import Order, OrderItem

        since = timezone.now() - timedelta(days=30)
        live = Order.objects.exclude(status=Order.Status.CANCELLED)
        by_status = {r["status"]: r["n"] for r in Order.objects.values("status").annotate(n=Count("id"))}
        low = (
            ProductVariant.objects.filter(
                product__track_inventory=True,
                product__is_active=True,
                stock__lte=settings.LOW_STOCK_THRESHOLD,
            )
            .select_related("product")
            .order_by("stock")[:20]
        )
        top = (
            OrderItem.objects.filter(order__created_at__gte=since)
            .exclude(order__status=Order.Status.CANCELLED)
            .values("product_name")
            .annotate(units=Sum("quantity"), revenue=Sum(F("unit_price") * F("quantity")))
            .order_by("-units")[:5]
        )
        return Response(
            {
                "last_30_days": {
                    "orders": live.filter(created_at__gte=since).count(),
                    "revenue": live.filter(created_at__gte=since).aggregate(s=Sum("total"))["s"] or 0,
                },
                "orders_by_status": by_status,
                "new_contact_messages": ContactMessage.objects.filter(status="new").count(),
                "reviews_awaiting_approval": Review.objects.filter(is_approved=False).count(),
                "low_stock": [
                    {"product": v.product.name, "size": v.size, "stock": v.stock} for v in low
                ],
                "top_products": list(top),
            }
        )
