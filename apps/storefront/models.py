from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.core.models import TimeStampedModel
from apps.core.validators import validate_image_size


class SiteSettings(models.Model):
    """Singleton: store-wide details editable by staff."""

    store_name = models.CharField(max_length=80, default="Harlem Store")
    tagline = models.CharField(max_length=120, default="Sports & Fashion")
    contact_phone = models.CharField(max_length=30, blank=True)
    whatsapp_number = models.CharField(max_length=30, blank=True, help_text="International format, e.g. +2547...")
    contact_email = models.EmailField(blank=True)
    address = models.CharField(max_length=250, blank=True)
    opening_hours = models.CharField(max_length=200, blank=True)
    facebook_url = models.URLField(blank=True)
    instagram_url = models.URLField(blank=True)
    tiktok_url = models.URLField(blank=True)
    delivery_info = models.TextField(blank=True)
    announcement_text = models.CharField(max_length=120, default="Harlem Store · Own your style", blank=True)
    announcement_enabled = models.BooleanField(default=True)
    featured_promo = models.ForeignKey(
        "orders.PromoCode", null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
        help_text="Code shown in the homepage sale strip.",
    )
    online_ordering_enabled = models.BooleanField(
        default=False,
        help_text="OFF: the API refuses online orders and the storefront should show 'contact us to order'.",
    )

    class Meta:
        verbose_name = verbose_name_plural = "site settings"

    def __str__(self):
        return "Site settings"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        pass

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class ScheduledQuerySet(models.QuerySet):
    def live(self):
        now = timezone.now()
        return self.filter(is_active=True).filter(
            Q(starts_at__isnull=True) | Q(starts_at__lte=now), Q(ends_at__isnull=True) | Q(ends_at__gte=now)
        )


class HeroSlide(TimeStampedModel):
    title = models.CharField(max_length=120)
    text = models.CharField(max_length=250, blank=True)
    image = models.ImageField(upload_to="hero/", validators=[validate_image_size])
    image_alt = models.CharField(max_length=200, blank=True)
    category = models.ForeignKey("catalog.Category", null=True, blank=True, on_delete=models.SET_NULL,
                                 help_text="'Shop now' links to this category.")
    link_url = models.CharField(max_length=200, blank=True, help_text="Overrides category link, e.g. /shop")
    button_label = models.CharField(max_length=40, default="Shop now")
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    objects = ScheduledQuerySet.as_manager()

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self):
        return self.title


class Banner(TimeStampedModel):
    class Placement(models.TextChoices):
        SIDE_PANEL = "side_panel", "Hero side panel ('Fresh kicks')"
        COLLECTION_PANEL = "collection_panel", "Featured products side panel ('The collection')"
        BESTSELLERS_BANNER = "bestsellers_banner", "Bestsellers banner"
        DEALS_BANNER = "deals_banner", "Deals of the week banner"

    placement = models.CharField(max_length=30, choices=Placement.choices)
    eyebrow = models.CharField(max_length=60, blank=True)
    heading = models.CharField(max_length=120)
    subheading = models.CharField(max_length=160, blank=True)
    body = models.CharField(max_length=250, blank=True)
    link_label = models.CharField(max_length=40, blank=True)
    link_url = models.CharField(max_length=200, default="/shop")
    image = models.ImageField(upload_to="banners/", validators=[validate_image_size])
    image_alt = models.CharField(max_length=200, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True, help_text="If several are active for a placement, the first is used.")
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    objects = ScheduledQuerySet.as_manager()

    class Meta:
        ordering = ["placement", "sort_order", "id"]

    def __str__(self):
        return f"{self.get_placement_display()}: {self.heading}"


class ServiceHighlight(models.Model):
    ICONS = [(i, i) for i in ("tags", "truck", "shirt", "message-circle", "badge-check", "shield-check",
                              "headset", "star", "timer", "package", "credit-card")]
    title = models.CharField(max_length=60)
    text = models.CharField(max_length=120)
    icon = models.CharField(max_length=30, choices=ICONS, default="tags", help_text="lucide-react icon name.")
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self):
        return self.title


class Testimonial(models.Model):
    quote = models.TextField(max_length=400)
    author = models.CharField(max_length=80)
    role = models.CharField(max_length=120, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self):
        return f"{self.author}: {self.quote[:40]}"


class Deal(TimeStampedModel):
    product = models.ForeignKey("catalog.Product", on_delete=models.CASCADE, related_name="deals")
    badge = models.CharField(max_length=20, default="Deal")
    sold = models.PositiveIntegerField(default=0)
    available = models.PositiveIntegerField(default=0, help_text="Units left in this promotion (drives the progress bar).")
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True, help_text="Drives the countdown. Blank = end of today.")
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    objects = ScheduledQuerySet.as_manager()

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self):
        return f"Deal: {self.product.name}"

    @property
    def percent_sold(self):
        total = self.sold + self.available
        return round(self.sold / total * 100) if total else 0
