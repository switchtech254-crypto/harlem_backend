from django.conf import settings
from rest_framework import serializers

from apps.core.utils import file_url

from .models import Category, Product, Review


class CategorySerializer(serializers.ModelSerializer):
    id = serializers.CharField(source="slug", read_only=True)
    image = serializers.SerializerMethodField()
    product_count = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = ["id", "name", "blurb", "image", "product_count"]

    def get_image(self, obj):
        return file_url(self.context.get("request"), obj.image)

    def get_product_count(self, obj):
        return getattr(obj, "product_count", None)


class ProductListSerializer(serializers.ModelSerializer):
    """Shape matches the storefront's `Product` type (id = slug, price in KSh)."""

    id = serializers.CharField(source="slug", read_only=True)
    category = serializers.CharField(source="category.slug", read_only=True)
    category_name = serializers.CharField(source="category.name", read_only=True)
    price = serializers.IntegerField(source="current_price", read_only=True)
    original_price = serializers.SerializerMethodField()
    image = serializers.SerializerMethodField()
    sizes = serializers.SerializerMethodField()
    in_stock = serializers.SerializerMethodField()
    rating = serializers.SerializerMethodField()
    review_count = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id", "name", "price", "original_price", "category", "category_name",
            "image", "description", "sizes", "badge", "in_stock", "rating", "review_count",
        ]

    def get_original_price(self, obj):
        return obj.price if obj.on_sale else None

    def get_image(self, obj):
        images = list(obj.images.all())
        return file_url(self.context.get("request"), images[0].image) if images else None

    def get_sizes(self, obj):
        # null (not []) when unsized, so `product.sizes && ...` in the frontend stays falsy.
        sizes = [v.size for v in obj.variants.all() if v.size]
        return sizes or None

    def get_in_stock(self, obj):
        if not obj.track_inventory:
            return True
        return any(v.stock > 0 for v in obj.variants.all())

    def get_rating(self, obj):
        value = getattr(obj, "rating", None)
        return round(value, 1) if value is not None else None

    def get_review_count(self, obj):
        return getattr(obj, "review_count", 0)


class ProductDetailSerializer(ProductListSerializer):
    images = serializers.SerializerMethodField()
    variants = serializers.SerializerMethodField()

    class Meta(ProductListSerializer.Meta):
        fields = ProductListSerializer.Meta.fields + ["images", "variants"]

    def get_images(self, obj):
        request = self.context.get("request")
        return [
            {"url": file_url(request, i.image), "alt": i.alt_text or obj.name} for i in obj.images.all()
        ]

    def get_variants(self, obj):
        # Exact stock levels are never exposed publicly.
        return [
            {
                "size": v.size,
                "in_stock": (not obj.track_inventory) or v.stock > 0,
                "low_stock": obj.track_inventory and 0 < v.stock <= settings.LOW_STOCK_THRESHOLD,
            }
            for v in obj.variants.all()
        ]


class ReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = Review
        fields = ["name", "rating", "comment", "created_at"]


class ReviewCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Review
        fields = ["name", "rating", "comment"]
