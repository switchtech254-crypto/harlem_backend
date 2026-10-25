from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.storefront.models import SiteSettings

from .models import Order
from .serializers import (
    CartQuoteSerializer, OrderCreateSerializer, OrderPublicSerializer, TrackSerializer, serialize_cart,
)
from .services import CartError, create_order, price_cart


class PublicView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []


class CartQuoteView(PublicView):
    """Price a localStorage cart on the server: validates sizes/stock and applies a promo code."""

    def post(self, request):
        ser = CartQuoteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        cart = price_cart(
            d["items"], promo_code=d.get("promo_code", ""), phone=d.get("phone", ""), email=d.get("email", "")
        )
        return Response(serialize_cart(cart, request))


class OrderCreateView(PublicView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "orders"

    def post(self, request):
        if not SiteSettings.get_solo().online_ordering_enabled:
            return Response(
                {"detail": "Online ordering isn't open yet. Please contact us to place your order."},
                status=status.HTTP_403_FORBIDDEN,
            )
        ser = OrderCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        customer = {
            "customer_name": d["customer_name"].strip(),
            "phone": d["phone"],
            "email": d.get("email", ""),
            "delivery_method": d["delivery_method"],
            "delivery_address": d.get("delivery_address", "").strip(),
            "notes": d.get("notes", "").strip(),
        }
        try:
            order = create_order(customer=customer, items=d["items"], promo_code=d.get("promo_code", ""))
        except CartError as exc:
            return Response({"detail": "Some items need attention.", "errors": exc.errors}, status=400)
        order = Order.objects.prefetch_related("items", "history").get(pk=order.pk)
        return Response(OrderPublicSerializer(order).data, status=status.HTTP_201_CREATED)


class OrderTrackView(PublicView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "track"

    def post(self, request):
        ser = TrackSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        order = (
            Order.objects.filter(reference__iexact=ser.validated_data["reference"].strip(),
                                 phone=ser.validated_data["phone"])
            .prefetch_related("items", "history")
            .first()
        )
        if not order:  # same answer for wrong ref or wrong phone
            return Response({"detail": "No order found for those details."}, status=404)
        return Response(OrderPublicSerializer(order).data)
