import re

from django.core.exceptions import ValidationError


def normalize_phone(raw: str) -> str:
    """Normalise Kenyan numbers to +2547XXXXXXXX / +2541XXXXXXXX.
    Other international numbers are accepted if written with + or 00."""
    s = re.sub(r"[\s\-().]", "", raw or "")
    international = s.startswith("+") or s.startswith("00")
    digits = re.sub(r"^(\+|00)", "", s)
    if not digits.isdigit():
        raise ValidationError("Enter a valid phone number, e.g. 0712 345 678.")
    if re.fullmatch(r"0[17]\d{8}", digits):
        digits = "254" + digits[1:]
    elif re.fullmatch(r"[17]\d{8}", digits):
        digits = "254" + digits
    if re.fullmatch(r"254[17]\d{8}", digits):
        return "+" + digits
    if international and 8 <= len(digits) <= 15:
        return "+" + digits
    raise ValidationError("Enter a valid phone number, e.g. 0712 345 678.")


def file_url(request, field_file):
    """Absolute URL for an ImageField/FileField value, or None."""
    if not field_file:
        return None
    url = field_file.url
    return request.build_absolute_uri(url) if request else url
