import hmac
import logging

from django.conf import settings
from rest_framework import status
from rest_framework.parsers import JSONParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.orders.models import Order

from .models import MpesaTransaction
from .serializers import StkPushSerializer
from .services import PaymentError, handle_callback, initiate_mpesa_payment, reconcile_if_due, status_payload

logger = logging.getLogger(__name__)


class PublicView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []


class MpesaStkPushView(PublicView):
    """Send an M-Pesa prompt for an order's outstanding balance."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "mpesa_push"

    def post(self, request):
        ser = StkPushSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        # Order reference + the order's phone together act as the credential (same rule as order tracking).
        order = Order.objects.filter(reference__iexact=d["reference"].strip(), phone=d["phone"]).first()
        if not order:
            return Response({"detail": "No order found for those details."}, status=status.HTTP_404_NOT_FOUND)
        try:
            txn, resumed = initiate_mpesa_payment(order, pay_phone=d.get("pay_phone") or None)
        except PaymentError as exc:
            return Response({"detail": str(exc)}, status=exc.status)
        payload = status_payload(txn)
        payload["resumed"] = resumed
        return Response(payload, status=status.HTTP_200_OK if resumed else status.HTTP_201_CREATED)


class MpesaStatusView(PublicView):
    """Poll a payment. CheckoutRequestID is unguessable and acts as the capability token."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "mpesa_status"

    def get(self, request, checkout_request_id):
        txn = MpesaTransaction.objects.filter(checkout_request_id=checkout_request_id).first()
        if not txn:
            return Response({"detail": "Payment not found."}, status=status.HTTP_404_NOT_FOUND)
        txn = reconcile_if_due(txn)  # covers a lost/late callback
        return Response(status_payload(txn))


class MpesaCallbackView(PublicView):
    """Receives Safaricom's result. The secret in the URL stops anyone else from posting here."""

    throttle_classes: list = []
    parser_classes = [JSONParser]

    def post(self, request, secret):
        expected = settings.MPESA_CALLBACK_SECRET
        if not expected or not hmac.compare_digest(secret.encode(), expected.encode()):
            return Response(status=status.HTTP_404_NOT_FOUND)
        try:
            handle_callback(request.data)
        except Exception:  # never let a bug here turn into a failed delivery; reconcile will catch up
            logger.exception("Error while processing M-Pesa callback")
        return Response({"ResultCode": 0, "ResultDesc": "Accepted"})
