from django.test import TestCase
from rest_framework.test import APIClient

from apps.contact.models import ContactMessage


class ContactApiTests(TestCase):
    def setUp(self):
        self.c = APIClient()

    def test_saves_message_and_normalises_phone(self):
        r = self.c.post("/api/contact/", {"name": "Brian", "phone": "0722000111", "kind": "team",
                                          "message": "Need 20 kits"}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(ContactMessage.objects.get().phone, "+254722000111")

    def test_requires_phone_or_email(self):
        self.assertEqual(self.c.post("/api/contact/", {"name": "x", "message": "hi"}, format="json").status_code, 400)

    def test_honeypot_silently_ignored(self):
        r = self.c.post("/api/contact/", {"name": "bot", "email": "a@b.co", "message": "spam", "website": "http://x"}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(ContactMessage.objects.count(), 0)
