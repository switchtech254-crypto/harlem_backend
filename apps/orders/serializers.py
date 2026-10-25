from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.core.utils import file_url, normalize_phone

from .models import Order, OrderItem
from .services import MAX_LINES


class CartItemSerializer(serializers.Serializer):
    """Mirrors the storefront cart item: { id, size?, qty }."""

    id = serializers.CharField(max_length=100)
    size = serializers.CharField(max_length=20, required=False, allow_blank=True, allow_null=True)
    qty = serializers.IntegerField(min_value=1, max_value=99)
    customization = serializers.DictField(
        child=serializers.CharField(max_length=100, allow_blank=True), required=False
    )

    def validate_customization(self, value):
        if len(value) > 10:
            raise serializers.ValidationError("Too many customization fields.")
        return value


class CartQuoteSerializer(serializers.Serializer):
    items = CartItemSerializer(many=True, allow_empty=True, max_length=MAX_LINES)
    promo_code = serializers.CharField(max_length=32, required=False, allow_blank=True)
    phone = serializers.CharField(max_length=32, required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)

    def validate_phone(self, value):
        if not value:
            return ""
        try:
            return normalize_phone(value)
        except DjangoValidationError as e:
            raise serializers.ValidationError(e.messages)


class OrderCreateSerializer(CartQuoteSerializer):
    items = CartItemSerializer(many=True, allow_empty=False, max_length=MAX_LINES)
    customer_name = serializers.CharField(max_length=120)
    phone = serializers.CharField(max_length=32)
    delivery_method = serializers.ChoiceField(choices=Order.DeliveryMethod.choices, default="delivery")
    delivery_address = serializers.CharField(max_length=300, required=False, allow_blank=True)
    notes = serializers.CharField(max_length=1000, required=False, allow_blank=True)

    def validate(self, attrs):
        if attrs["delivery_method"] == "delivery" and not attrs.get("delivery_address", "").strip():
            raise serializers.ValidationError({"delivery_address": "Enter a delivery address."})
        return attrs


class TrackSerializer(serializers.Serializer):
    reference = serializers.CharField(max_length=20)
    phone = serializers.CharField(max_length=32)

    def validate_phone(self, value):
        try:
            return normalize_phone(value)
        except DjangoValidationError as e:
            raise serializers.ValidationError(e.messages)


def serialize_cart(cart, request):
    return {
        "lines": [
            {
                "id": l.product.slug,
                "name": l.product.name,
                "size": l.size or None,
                "qty": l.quantity,
                "unit_price": l.unit_price,
                "line_total": l.line_total,
                "image": file_url(request, l.product.images.all()[0].image) if l.product.images.all() else None,
            }
            for l in cart.lines
        ],
        "subtotal": cart.subtotal,
        "discount": cart.discount,
        "total": cart.total,
        "promo_code": cart.promo.code if cart.promo else None,
        "errors": cart.errors,
        "valid": not cart.errors and bool(cart.lines),
    }


class OrderItemPublicSerializer(serializers.ModelSerializer):
    line_total = serializers.IntegerField(read_only=True)

    class Meta:
        model = OrderItem
        fields = ["product_name", "size", "quantity", "unit_price", "line_total", "customization"]


class OrderPublicSerializer(serializers.ModelSerializer):
    """Customer-facing view – no phone/email/address/internal notes."""

    status_display = serializers.CharField(source="get_status_display", read_only=True)
    payment_status_display = serializers.CharField(source="get_payment_status_display", read_only=True)
    items = OrderItemPublicSerializer(many=True, read_only=True)
    timeline = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            "reference", "status", "status_display", "payment_status", "payment_status_display",
            "delivery_method", "subtotal", "discount_total", "total", "created_at", "items", "timeline",
        ]

    def get_timeline(self, obj):
        return [{"status": h.to_status, "at": h.created_at} for h in obj.history.all()]
