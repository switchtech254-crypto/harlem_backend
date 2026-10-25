from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create the 'Store Manager' and 'Order Desk' staff groups (idempotent)."

    def handle(self, *args, **opts):
        def perms(apps, actions=("view", "add", "change", "delete"), models=None):
            q = Permission.objects.filter(content_type__app_label__in=apps)
            if models:
                q = q.filter(content_type__model__in=models)
            return [p for p in q if p.codename.split("_")[0] in actions]

        manager, _ = Group.objects.get_or_create(name="Store Manager")
        manager.permissions.set(perms(["catalog", "orders", "storefront", "contact"]))

        desk, _ = Group.objects.get_or_create(name="Order Desk")
        desk.permissions.set(
            perms(["orders"], ("view", "add", "change"), ["order", "orderitem", "payment", "orderstatushistory"])
            + perms(["contact"], ("view", "change"))
            + perms(["catalog"], ("view",))
        )
        self.stdout.write(self.style.SUCCESS("Groups ready: Store Manager, Order Desk"))
