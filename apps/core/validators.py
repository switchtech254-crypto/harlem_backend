from django.core.exceptions import ValidationError

MAX_IMAGE_MB = 5


def validate_image_size(f):
    if f.size > MAX_IMAGE_MB * 1024 * 1024:
        raise ValidationError(f"Images must be smaller than {MAX_IMAGE_MB} MB.")
