from django.test import TestCase
from rest_framework.test import APIClient

from apps.orders.tests import make_product


class CatalogApiTests(TestCase):
    def setUp(self):
        self.c = APIClient()
        make_product("court", 5000)
        make_product("sale-shoe", 4000, sale_price=3000)
        make_product("ball", 2800, sizes=(""), stock=0)

    def test_list_shape_matches_frontend_type(self):
        r = self.c.get("/api/products/")
        self.assertEqual(r.status_code, 200)
        item = next(i for i in r.data["results"] if i["id"] == "court")
        self.assertEqual(item["price"], 5000)
        self.assertEqual(item["category"], "sneakers")
        self.assertEqual(item["sizes"], ["41", "42"])

    def test_unsized_product_has_null_sizes_and_stock_flag(self):
        item = self.c.get("/api/products/ball/").data
        self.assertIsNone(item["sizes"])
        self.assertFalse(item["in_stock"])

    def test_sale_price_search_and_filters(self):
        self.assertEqual(self.c.get("/api/products/sale-shoe/").data["original_price"], 4000)
        self.assertEqual(self.c.get("/api/products/sale-shoe/").data["price"], 3000)
        ids = lambda q: {i["id"] for i in self.c.get("/api/products/", q).data["results"]}  # noqa: E731
        self.assertEqual(ids({"q": "sneakers"}), {"court", "sale-shoe", "ball"})
        self.assertEqual(ids({"in_stock": "true"}), {"court", "sale-shoe"})
        self.assertEqual(ids({"on_sale": "true"}), {"sale-shoe"})
        self.assertEqual(ids({"max_price": 3500}), {"sale-shoe", "ball"})

    def test_ordering_by_price(self):
        prices = [i["price"] for i in self.c.get("/api/products/", {"ordering": "price"}).data["results"]]
        self.assertEqual(prices, sorted(prices))
        prices = [i["price"] for i in self.c.get("/api/products/", {"ordering": "-price"}).data["results"]]
        self.assertEqual(prices, sorted(prices, reverse=True))

    def test_reviews_need_approval(self):
        r = self.c.post("/api/products/court/reviews/", {"name": "Joy", "rating": 5, "comment": "Great"}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.c.get("/api/products/court/reviews/").data, [])

    def test_inactive_hidden(self):
        from apps.catalog.models import Product
        Product.objects.filter(slug="court").update(is_active=False)
        self.assertEqual(self.c.get("/api/products/court/").status_code, 404)

    def test_staff_dashboard_requires_staff(self):
        self.assertIn(self.c.get("/api/staff/dashboard/").status_code, (401, 403))
