from datetime import timedelta
from smtplib import SMTPException
from unittest import mock

import requests
from django.core import mail
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone

from apps.orders.models import Order, OrderItem
from apps.orders.tests import make_product
from apps.payments.tests import MpesaBase, Resp, callback
from apps.storefront.models import SiteSettings

from .models import NotificationLog

NOTIF = dict(
    STORE_NOTIFICATION_EMAILS=["owner@example.com"],
    PAYMENTS_FROM_EMAIL="Harlem Store Payments <payments@harlemstore.co.ke>",
    DEFAULT_FROM_EMAIL="Harlem Store <orders@harlemstore.co.ke>",
    SUPPORT_EMAIL="help@harlemstore.co.ke",
    FRONTEND_URL="https://shop.example.com",
    BACKEND_PUBLIC_URL="https://api.example.com",
    TELEGRAM_BOT_TOKEN="123456:SECRET-TOKEN",
    TELEGRAM_CHAT_ID="111,-100222",
    TELEGRAM_API_BASE="https://tg.test",
    NOTIFICATIONS_ASYNC=False,
)


@override_settings(**NOTIF)
class NotificationBase(MpesaBase):
    def setUp(self):
        super().setUp()
        self.order.email, self.order.customer_name = "amina@example.com", "Amina Wanjiru"
        self.order.save()
        OrderItem.objects.create(order=self.order, product_name="Harlem Court Sneaker", size="42",
                                 unit_price=5000, quantity=1, customization={"name": "AMINA", "number": "10"})
        s = SiteSettings.get_solo()
        s.contact_phone, s.whatsapp_number = "+254 712 345 678", "+254712345678"
        s.opening_hours, s.address = "Mon-Sat 8am-6pm", "Moi Avenue, Nairobi"
        s.save()

        self.tg = []
        self.tg_response = Resp({"ok": True, "result": {}}, 200)

        def router(url, json=None, headers=None, timeout=None):
            if url.startswith("https://tg.test/"):
                self.tg.append((url, json))
                if isinstance(self.tg_response, Exception):
                    raise self.tg_response
                return self.tg_response
            return self.fake.post(url, json=json, headers=headers, timeout=timeout)  # Daraja

        patcher = mock.patch("requests.post", side_effect=router)
        patcher.start()
        self.addCleanup(patcher.stop)

    def pay(self):
        self.push()
        with self.captureOnCommitCallbacks(execute=True):
            self.cb(callback())

    def to(self, addr):
        return [m for m in mail.outbox if m.to == [addr]]


class CustomerEmailTests(NotificationBase):
    def test_customer_gets_payment_confirmation_with_order_number_and_help(self):
        self.pay()
        (m,) = self.to("amina@example.com")
        self.assertIn("Payment received", m.subject)
        self.assertIn(self.order.reference, m.subject)
        self.assertEqual(m.from_email, "Harlem Store Payments <payments@harlemstore.co.ke>")
        self.assertEqual(m.reply_to, ["help@harlemstore.co.ke"])
        for needle in (
            self.order.reference, "NLJ7RT61SV", "KSh 5,000", "Harlem Court Sneaker", "size 42", "AMINA",
            f"https://shop.example.com/track?ref={self.order.reference}&t={self.order.tracking_token}",
            "help@harlemstore.co.ke", "+254 712 345 678", "https://wa.me/254712345678", "Mon-Sat 8am-6pm",
            "quote order number", "reply to this email", "https://shop.example.com/returns-exchanges",
        ):
            self.assertIn(needle, m.body, needle)
        html = m.alternatives[0].content
        self.assertEqual(m.alternatives[0].mimetype, "text/html")
        for needle in (self.order.reference, "NLJ7RT61SV", "Track your order", "mailto:help@harlemstore.co.ke"):
            self.assertIn(needle, html, needle)

    def test_customer_name_is_html_escaped(self):
        self.order.customer_name = "<script>alert(1)</script> Eve"
        self.order.save()
        self.pay()
        html = self.to("amina@example.com")[0].alternatives[0].content
        self.assertNotIn("<script>alert(1)</script>", html)

    def test_no_customer_email_means_no_customer_message_but_owner_still_notified(self):
        self.order.email = ""
        self.order.save()
        self.pay()
        self.assertEqual(len(self.to("owner@example.com")), 1)
        self.assertEqual(len(self.tg), 2)
        self.assertFalse(NotificationLog.objects.filter(event="payment_customer").exists())


class OwnerNotificationTests(NotificationBase):
    def test_owner_email_comes_from_payments_address_with_payment_and_order_details(self):
        self.pay()
        (m,) = self.to("owner@example.com")
        self.assertEqual(m.from_email, "Harlem Store Payments <payments@harlemstore.co.ke>")
        self.assertIn("Payment received: KSh 5,000", m.subject)
        self.assertIn(self.order.reference, m.subject)
        self.assertIn("Amina Wanjiru", m.subject)
        for needle in (
            "NLJ7RT61SV", "KSh 5,000", "M-Pesa", "+254712345678", "amina@example.com", "Collection",
            "Harlem Court Sneaker", "size 42", "name: AMINA", "Paid",
            f"https://api.example.com/admin/orders/order/{self.order.pk}/change/",
        ):
            self.assertIn(needle, m.body, needle)
        self.assertEqual(m.reply_to, ["amina@example.com"])

    def test_telegram_message_goes_to_every_chat_with_the_order(self):
        self.pay()
        self.assertEqual(len(self.tg), 2)
        self.assertEqual([c["chat_id"] for _, c in self.tg], ["111", "-100222"])
        url, payload = self.tg[0]
        self.assertEqual(url, "https://tg.test/bot123456:SECRET-TOKEN/sendMessage")
        self.assertEqual(payload["parse_mode"], "HTML")
        for needle in ("Payment received", self.order.reference, "NLJ7RT61SV", "Amina Wanjiru", "KSh 5,000",
                       "Harlem Court Sneaker", f"https://api.example.com/admin/orders/order/{self.order.pk}/change/"):
            self.assertIn(needle, payload["text"], needle)

    def test_telegram_text_escapes_customer_input(self):
        self.order.customer_name = "<b>Evil</b> & Co"
        self.order.save()
        self.pay()
        text = self.tg[0][1]["text"]
        self.assertIn("&lt;b&gt;Evil&lt;/b&gt; &amp; Co", text)
        self.assertNotIn("<b>Evil</b>", text)

    def test_amount_mismatch_is_flagged_to_the_owner(self):
        self.push()
        with self.captureOnCommitCallbacks(execute=True):
            self.cb(callback(amount=4000))
        self.assertIn("Please check", self.to("owner@example.com")[0].body.replace("PLEASE CHECK", "Please check"))
        self.assertIn("needs checking", self.tg[0][1]["text"])

    @override_settings(TELEGRAM_BOT_TOKEN="")
    def test_telegram_is_skipped_when_not_configured(self):
        self.pay()
        self.assertEqual(self.tg, [])
        self.assertFalse(NotificationLog.objects.filter(channel="telegram").exists())


class IdempotencyAndFailureTests(NotificationBase):
    def test_duplicate_callback_does_not_send_anything_twice(self):
        self.pay()
        emails, tgs = len(mail.outbox), len(self.tg)
        with self.captureOnCommitCallbacks(execute=True):
            self.cb(callback())
        self.assertEqual((len(mail.outbox), len(self.tg)), (emails, tgs))
        self.assertEqual(NotificationLog.objects.filter(status="sent").count(), 4)  # customer, owner, 2 chats

    def test_telegram_rejection_is_logged_and_never_breaks_the_payment(self):
        self.tg_response = Resp({"ok": False, "description": "Bad Request: chat not found"}, 400)
        self.pay()
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, "paid")
        self.assertEqual(len(mail.outbox), 2)  # emails unaffected
        failed = NotificationLog.objects.filter(channel="telegram", status="failed")
        self.assertEqual(failed.count(), 2)
        self.assertIn("chat not found", failed[0].error)
        self.assertNotIn("SECRET-TOKEN", failed[0].error)

    def test_bot_token_never_leaks_through_network_errors(self):
        self.tg_response = requests.ConnectionError("HTTPSConnectionPool: /bot123456:SECRET-TOKEN/sendMessage failed")
        self.pay()
        for log in NotificationLog.objects.filter(channel="telegram"):
            self.assertEqual(log.status, "failed")
            self.assertNotIn("SECRET-TOKEN", log.error)

    def test_mail_server_down_is_logged_then_retried_without_duplicates(self):
        with mock.patch("apps.notifications.emails.EmailMultiAlternatives.send", side_effect=SMTPException("down")):
            self.pay()
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, "paid")  # the payment itself is safe
        self.assertEqual(NotificationLog.objects.filter(channel="email", status="failed").count(), 2)
        self.assertEqual(len(self.tg), 2)  # Telegram still went out

        NotificationLog.objects.update(updated_at=timezone.now() - timedelta(minutes=5))
        call_command("retry_notifications")
        self.assertEqual(len(self.to("amina@example.com")), 1)
        self.assertEqual(len(self.to("owner@example.com")), 1)
        self.assertEqual(len(self.tg), 2)  # not re-sent
        self.assertFalse(NotificationLog.objects.exclude(status="sent").exists())


class OrderPlacedTests(NotificationBase):
    def test_new_order_notifies_customer_owner_and_telegram(self):
        make_product("court", 5000, sizes=("42",), stock=5)
        s = SiteSettings.get_solo()
        s.online_ordering_enabled = True
        s.save()
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            r = self.c.post("/api/orders/", {
                "customer_name": "Brian O", "phone": "0722000111", "email": "brian@example.com",
                "delivery_method": "collection", "items": [{"id": "court", "size": "42", "qty": 1}]}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        ref = r.data["reference"]

        (cust,) = self.to("brian@example.com")
        self.assertIn(f"We received your order {ref}", cust.subject)
        self.assertEqual(cust.from_email, "Harlem Store <orders@harlemstore.co.ke>")
        self.assertIn(ref, cust.body)
        self.assertIn("track?ref=" + ref, cust.body)

        (owner,) = self.to("owner@example.com")
        self.assertIn(f"New order {ref}", owner.subject)
        self.assertTrue(any("New order" in p["text"] and ref in p["text"] for _, p in self.tg))
