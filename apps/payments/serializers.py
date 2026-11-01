from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.core.utils import normalize_phone


def _phone(value):
    try:
        return normalize_phone(value)
    except DjangoValidationError as exc:
        raise serializers.ValidationError(exc.messages) from None


class StkPushSerializer(serializers.Serializer):
    reference = serializers.CharField(max_length=20)
    phone = serializers.CharField(max_length=32, help_text="The phone number used on the order (proves ownership).")
    pay_phone = serializers.CharField(max_length=32, required=False, allow_blank=True,
                                      help_text="Optional different M-Pesa number to charge.")

    def validate_phone(self, value):
        return _phone(value)

    def validate_pay_phone(self, value):
        return _phone(value) if value else ""
