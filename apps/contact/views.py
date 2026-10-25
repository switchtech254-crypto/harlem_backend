import logging

from django.conf import settings
from django.core.mail import send_mail
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .serializers import ContactSerializer

logger = logging.getLogger(__name__)
OK = {"detail": "Thanks! Our team will get back to you shortly."}


class ContactView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "contact"

    def post(self, request):
        ser = ContactSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = dict(ser.validated_data)
        if data.pop("website", ""):  # bots fill the hidden field: pretend success, store nothing
            return Response(OK, status=status.HTTP_201_CREATED)
        msg = ser.save()
        if settings.STORE_NOTIFICATION_EMAILS:
            try:
                send_mail(
                    f"[Harlem Store] {msg.get_kind_display()} from {msg.name}",
                    f"{msg.message}\n\nPhone: {msg.phone or '—'}\nEmail: {msg.email or '—'}\n"
                    f"Organisation: {msg.organisation or '—'}",
                    settings.DEFAULT_FROM_EMAIL, settings.STORE_NOTIFICATION_EMAILS, fail_silently=True,
                )
            except Exception:
                logger.exception("Contact notification failed")
        return Response(OK, status=status.HTTP_201_CREATED)
