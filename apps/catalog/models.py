from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q

from apps.core.models import TimeStampedModel
from apps.core.validators import validate_image_size


class Category(TimeStampedModel):
    slug = models.SlugField(unique=True, help_text="Public ID used in URLs, e.g. 'sneakers'.")
    name = models.CharField(max_length=100)
    blurb = models.CharField(max_length=200, blank=True)
    image = models.ImageField(upload_to="categories/", blank=True, validators=[validate_image_size])
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name


class Product(TimeStampedModel):
    slug = models.SlugField(max_length=100, unique=True, help_text="Public ID, e.g. 'court-sneaker'.")
    name = models.CharField(max_length=200)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="products")
    description = models.TextField(blank=True)
    price = models.PositiveIntegerField(validators=[MinValueValidator(1)], help_text="Regular price in KSh.")
    sale_price = models.PositiveIntegerField(
        null=True, blank=True, help_text="Optional discounted price in KSh (must be below the regular price)."
    )
    badge = models.CharField(max_length=30, blank=True, help_text="Optional label on cards, e.g. 'New'.")
    track_inventory = models.BooleanField(
        default=True, help_text="Untick for services/made-to-order items (e.g. custom branding)."
    )
    is_active = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False, help_text="Show in 'Featured products' on the homepage.")
    is_bestseller = models.BooleanField(default=False, help_text="Pin to 'Latest bestsellers'.")
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]
        indexes = [models.Index(fields=["is_active", "category"])]
        constraints = [
            models.CheckConstraint(
                condition=Q(sale_price__isnull=True) | Q(sale_price__lt=F("price")),
                name="product_sale_price_below_price",
            )
        ]

    def __str__(self):
        return self.name

    def clean(self):
        if self.sale_price is not None and self.price is not None and self.sale_price >= self.price:
            raise ValidationError({"sale_price": "Sale price must be lower than the regular price."})

    @property
    def current_price(self):
        return self.sale_price if self.sale_price is not None else self.price

    @property
    def on_sale(self):
        return self.sale_price is not None


class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to="products/", validators=[validate_image_size])
    alt_text = models.CharField(max_length=200, blank=True)
    sort_order = models.PositiveIntegerField(default=0, help_text="Lowest number is the main image.")

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self):
        return f"{self.product.name} image {self.pk}"


class ProductVariant(models.Model):
    """A sellable unit: one row per size (or one row with blank size for unsized items)."""

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="variants")
    size = models.CharField(max_length=20, blank=True, default="", help_text="Leave blank for unsized items.")
    sku = models.CharField(max_length=50, blank=True)
    stock = models.PositiveIntegerField(default=0)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]
        constraints = [
            models.UniqueConstraint(fields=["product", "size"], name="unique_size_per_product"),
            models.UniqueConstraint(fields=["sku"], condition=~Q(sku=""), name="unique_nonblank_sku"),
        ]

    def __str__(self):
        return f"{self.product.name} / {self.size or 'one size'}"


class Review(TimeStampedModel):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="reviews")
    name = models.CharField(max_length=80)
    rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    comment = models.TextField(max_length=1000, blank=True)
    is_approved = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.product.name}: {self.rating}★ by {self.name}"
