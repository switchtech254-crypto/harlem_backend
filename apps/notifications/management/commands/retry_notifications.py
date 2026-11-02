"""Retry emails / Telegram messages that failed (e.g. the mail server was down). Run every few minutes:

    python manage.py retry_notifications
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.notifications.dispatch import retry
from apps.notifications.models import NotificationLog


class Command(BaseCommand):
    help = "Retry failed notifications from the last 24 hours."

    def handle(self, *args, **opts):
        now = timezone.now()
        logs = NotificationLog.objects.filter(
            status__in=[NotificationLog.Status.FAILED, NotificationLog.Status.PENDING],
            updated_at__lte=now - timedelta(minutes=1),
            created_at__gte=now - timedelta(hours=24),
        )
        n = 0
        for log in logs:
            retry(log)
            n += 1
        still = NotificationLog.objects.filter(status=NotificationLog.Status.FAILED, created_at__gte=now - timedelta(hours=24)).count()
        self.stdout.write(self.style.SUCCESS(f"Retried {n} notification(s); {still} still failing."))
