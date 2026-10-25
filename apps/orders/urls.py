from django.urls import path

from .views import CartQuoteView, OrderCreateView, OrderTrackView

urlpatterns = [
    path("cart/quote/", CartQuoteView.as_view(), name="cart-quote"),
    path("orders/", OrderCreateView.as_view(), name="order-create"),
    path("orders/track/", OrderTrackView.as_view(), name="order-track"),
]
