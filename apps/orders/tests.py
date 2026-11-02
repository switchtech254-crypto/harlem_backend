from django.test import TestCase
from rest_framework.test import APIClient

from apps.catalog.models import Category, Product, ProductVariant
from apps.orders.models import InvalidTransition, Order, PromoCode
from apps.storefront.models import SiteSettings


def make_product(slug="court", price=5000, sizes=("41", "42"), stock=5, **kw):
    cat, _ = Category.objects.get_or_create(slug="sneakers", defaults={"name": "Sneakers"})
    p = Product.objects.create(slug=slug, name=slug.title(), category=cat, price=price, **kw)
    for i, s in enumerate(sizes):
        ProductVariant.objects.create(product=p, size=s, stock=stock, sort_order=i)
    return p


class OrderApiTests(TestCase):
    def setUp(self):
        self.c = APIClient()
        self.p = make_product()
        s = SiteSettings.get_solo()
        s.online_ordering_enabled = True
        s.save()

    def payload(self, **over):
        d = {"customer_name": "Amina", "phone": "0712 345 678", "delivery_method": "collection",
             "items": [{"id": "court", "size": "42", "qty": 2}]}
        d.update(over)
        return d

    def test_quote_ignores_client_prices_and_applies_promo(self):
        PromoCode.objects.create(code="harlem10", value=10, first_purchase_only=True)
        r = self.c.post("/api/cart/quote/", {"items": [{"id": "court", "size": "41", "qty": 2, "price": 1}],
                                             "promo_code": "HARLEM10"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.data["subtotal"], r.data["discount"], r.data["total"]), (10000, 1000, 9000))

    def test_quote_reports_bad_size_and_stock(self):
        r = self.c.post("/api/cart/quote/", {"items": [{"id": "court", "size": "50", "qty": 1},
                                                       {"id": "court", "size": "41", "qty": 9}]}, format="json")
        self.assertFalse(r.data["valid"])
        self.assertEqual(len(r.data["errors"]), 2)

    def test_order_creates_snapshot_and_decrements_stock(self):
        r = self.c.post("/api/orders/", self.payload(), format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["total"], 10000)
        self.assertEqual(ProductVariant.objects.get(product=self.p, size="42").stock, 3)
        order = Order.objects.get()
        self.assertEqual(order.phone, "+254712345678")
        self.p.price = 9999
        self.p.save()
        self.assertEqual(order.items.first().unit_price, 5000)  # snapshot survives price change

    def test_oversell_rejected_and_nothing_changes(self):
        r = self.c.post("/api/orders/", self.payload(items=[{"id": "court", "size": "42", "qty": 6}]), format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(ProductVariant.objects.get(product=self.p, size="42").stock, 5)

    def test_delivery_requires_address(self):
        r = self.c.post("/api/orders/", self.payload(delivery_method="delivery"), format="json")
        self.assertEqual(r.status_code, 400)

    def test_ordering_can_be_switched_off(self):
        SiteSettings.objects.update(online_ordering_enabled=False)
        self.assertEqual(self.c.post("/api/orders/", self.payload(), format="json").status_code, 403)

    def test_first_purchase_code_only_once(self):
        PromoCode.objects.create(code="HARLEM10", value=10, first_purchase_only=True)
        ok = self.c.post("/api/orders/", self.payload(promo_code="HARLEM10"), format="json")
        self.assertEqual(ok.status_code, 201)
        again = self.c.post("/api/orders/", self.payload(promo_code="HARLEM10"), format="json")
        self.assertEqual(again.status_code, 400)
        self.assertEqual(PromoCode.objects.get().times_used, 1)

    def test_cancel_returns_stock_and_is_terminal(self):
        self.c.post("/api/orders/", self.payload(), format="json")
        order = Order.objects.get()
        order.change_status("cancelled")
        self.assertEqual(ProductVariant.objects.get(product=self.p, size="42").stock, 5)
        with self.assertRaises(InvalidTransition):
            order.change_status("confirmed")

    def test_tracking_requires_matching_phone(self):
        ref = self.c.post("/api/orders/", self.payload(), format="json").data["reference"]
        self.assertEqual(self.c.post("/api/orders/track/", {"reference": ref, "phone": "0712345678"}, format="json").status_code, 200)
        self.assertEqual(self.c.post("/api/orders/track/", {"reference": ref, "phone": "0799999999"}, format="json").status_code, 404)

    def test_payments_update_payment_status(self):
        self.c.post("/api/orders/", self.payload(), format="json")
        order = Order.objects.get()
        order.payments.create(method="mpesa", amount=4000, reference="ABC123")
        order.refresh_from_db()
        self.assertEqual(order.payment_status, "partial")
        order.payments.create(method="cash", amount=6000)
        order.refresh_from_db()
        self.assertEqual(order.payment_status, "paid")


class TrackingLinkTests(TestCase):
    def setUp(self):
        self.c = APIClient()
        make_product()
        s = SiteSettings.get_solo()
        s.online_ordering_enabled = True
        s.save()
        r = self.c.post("/api/orders/", {"customer_name": "Amina", "phone": "0712345678", "delivery_method": "collection",
                                         "items": [{"id": "court", "size": "42", "qty": 1}]}, format="json")
        self.ref, self.token = r.data["reference"], r.data["tracking_token"]

    def track(self, **body):
        return self.c.post("/api/orders/track/", {"reference": self.ref, **body}, format="json")

    def test_order_response_includes_a_private_tracking_token(self):
        self.assertEqual(len(self.token), 32)

    def test_token_alone_is_enough_so_email_links_need_no_phone(self):
        r = self.track(token=self.token)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["reference"], self.ref)
        self.assertEqual(r.data["status"], "pending")
        self.assertEqual(r.data["delivery_method_display"], "Collection")

    def test_wrong_token_wrong_phone_or_nothing_is_refused(self):
        self.assertEqual(self.track(token="0" * 32).status_code, 404)
        self.assertEqual(self.track(phone="0799999999").status_code, 404)
        self.assertEqual(self.track().status_code, 400)

    def test_another_orders_token_does_not_work(self):
        other = self.c.post("/api/orders/", {"customer_name": "B", "phone": "0722000111", "delivery_method": "collection",
                                             "items": [{"id": "court", "size": "41", "qty": 1}]}, format="json")
        self.assertEqual(self.track(token=other.data["tracking_token"]).status_code, 404)

    def test_phone_still_works_and_progress_shows_up(self):
        order = Order.objects.get(reference=self.ref)
        order.change_status("confirmed")
        order.payments.create(method="mpesa", amount=2000, reference="ABC123")
        r = self.track(phone="0712 345 678")
        self.assertEqual(r.status_code, 200)
        self.assertEqual([t["status"] for t in r.data["timeline"]], ["pending", "confirmed"])
        self.assertEqual((r.data["amount_paid"], r.data["balance_due"]), (2000, 3000))
        self.assertEqual(r.data["payments"][0]["reference"], "ABC123")
        self.assertNotIn("phone", r.data)  # no personal data in the public view
        self.assertNotIn("email", r.data)
