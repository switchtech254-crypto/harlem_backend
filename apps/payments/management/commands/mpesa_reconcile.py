"""Settle pending M-Pesa payments whose callback never arrived. Run every few minutes (cron/scheduler):

    python manage.py mpesa_reconcile
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.payments.models import MpesaTransaction
from apps.payments.services import QUERY_AFTER_SECONDS, reconcile


class Command(BaseCommand):
    help = "Query Daraja for pending M-Pesa payments older than a short grace period."

    def handle(self, *args, **opts):
        cutoff = timezone.now() - timedelta(seconds=QUERY_AFTER_SECONDS)
        pending = MpesaTransaction.objects.filter(status=MpesaTransaction.Status.PENDING, created_at__lte=cutoff)
        checked = settled = 0
        for txn in pending:
            checked += 1
            if reconcile(txn).status != MpesaTransaction.Status.PENDING:
                settled += 1
        self.stdout.write(self.style.SUCCESS(f"Checked {checked} pending payment(s); settled {settled}."))
