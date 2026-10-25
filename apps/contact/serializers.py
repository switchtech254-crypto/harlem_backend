from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.catalog.models import Product
from apps.core.utils import normalize_phone

from .models import ContactMessage


class ContactSerializer(serializers.ModelSerializer):
    product = serializers.SlugRelatedField(slug_field="slug", queryset=Product.objects.all(),
                                           required=False, allow_null=True)
    cart_snapshot = serializers.ListField(child=serializers.DictField(), required=False, max_length=50)
    website = serializers.CharField(write_only=True, required=False, allow_blank=True)  # honeypot

    class Meta:
        model = ContactMessage
        fields = ["kind", "name", "phone", "email", "organisation", "subject", "message",
                  "product", "cart_snapshot", "website"]

    def validate_phone(self, value):
        if not value:
            return ""
        try:
            return normalize_phone(value)
        except DjangoValidationError as e:
            raise serializers.ValidationError(e.messages)

    def validate(self, attrs):
        if not attrs.get("phone") and not attrs.get("email"):
            raise serializers.ValidationError("Please provide a phone number or an email address.")
        return attrs
