from django.urls import path

from .views import MpesaCallbackView, MpesaStatusView, MpesaStkPushView

urlpatterns = [
    path("payments/mpesa/stk-push/", MpesaStkPushView.as_view(), name="mpesa-stk-push"),
    path("payments/mpesa/status/<str:checkout_request_id>/", MpesaStatusView.as_view(), name="mpesa-status"),
    path("payments/mpesa/callback/<str:secret>/", MpesaCallbackView.as_view(), name="mpesa-callback"),
]
