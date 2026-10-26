"""One-time: upload files already saved under MEDIA_ROOT to the configured storage (Cloudinary).

    python manage.py migrate_media --dry-run     # list what would be uploaded
    python manage.py migrate_media               # upload

Run it once after setting CLOUDINARY_URL if you created products/banners before switching.
Files are uploaded under the same name, so database records keep working.
"""
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.files import File
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError
from django.db import models


class Command(BaseCommand):
    help = "Upload existing local media files to the configured default storage (e.g. Cloudinary)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Only list the files.")

    def handle(self, *args, dry_run=False, **opts):
        if not settings.CLOUDINARY_URL:
            raise CommandError("CLOUDINARY_URL is not set, so default storage is the local disk. Nothing to do.")

        uploaded = missing = 0
        for model in apps.get_models():
            for field in model._meta.get_fields():
                if not isinstance(field, models.FileField):
                    continue
                for obj in model.objects.exclude(**{field.name: ""}).exclude(**{f"{field.name}__isnull": True}):
                    name = getattr(obj, field.name).name
                    local = Path(settings.MEDIA_ROOT) / name
                    label = f"{model.__name__}#{obj.pk}.{field.name} -> {name}"
                    if not local.exists():
                        missing += 1
                        self.stderr.write(f"  missing locally, skipped: {label}")
                        continue
                    if dry_run:
                        self.stdout.write(f"  would upload: {label}")
                        continue
                    with local.open("rb") as fh:
                        new_name = default_storage.save(name, File(fh))
                    if new_name != name:
                        model.objects.filter(pk=obj.pk).update(**{field.name: new_name})
                    uploaded += 1
                    self.stdout.write(f"  uploaded: {label}")

        verb = "would upload" if dry_run else "uploaded"
        self.stdout.write(self.style.SUCCESS(f"Done: {verb} {uploaded if not dry_run else '(see list)'}; {missing} missing locally."))
