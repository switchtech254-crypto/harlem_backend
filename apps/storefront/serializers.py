from rest_framework import serializers

from apps.core.utils import file_url

from .models import Banner, HeroSlide, ServiceHighlight, SiteSettings, Testimonial


class ImageMixin:
    def _img(self, obj):
        return file_url(self.context.get("request"), obj.image)


class SiteSettingsSerializer(serializers.ModelSerializer):
    promo_code = serializers.CharField(source="featured_promo.code", default=None, read_only=True)
    promo_description = serializers.CharField(source="featured_promo.description", default=None, read_only=True)

    class Meta:
        model = SiteSettings
        fields = [
            "store_name", "tagline", "contact_phone", "whatsapp_number", "contact_email", "address",
            "opening_hours", "facebook_url", "instagram_url", "tiktok_url", "delivery_info",
            "announcement_text", "announcement_enabled", "promo_code", "promo_description",
            "online_ordering_enabled",
        ]


class HeroSlideSerializer(ImageMixin, serializers.ModelSerializer):
    image = serializers.SerializerMethodField()
    category = serializers.CharField(source="category.slug", default=None, read_only=True)
    text = serializers.CharField(read_only=True)
    href = serializers.SerializerMethodField()

    class Meta:
        model = HeroSlide
        fields = ["id", "title", "text", "image", "image_alt", "category", "href", "button_label"]

    def get_image(self, obj):
        return self._img(obj)

    def get_href(self, obj):
        if obj.link_url:
            return obj.link_url
        return f"/shop?category={obj.category.slug}" if obj.category else "/shop"


class BannerSerializer(ImageMixin, serializers.ModelSerializer):
    image = serializers.SerializerMethodField()

    class Meta:
        model = Banner
        fields = ["placement", "eyebrow", "heading", "subheading", "body", "link_label", "link_url",
                  "image", "image_alt"]

    def get_image(self, obj):
        return self._img(obj)


class ServiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceHighlight
        fields = ["title", "text", "icon"]


class TestimonialSerializer(serializers.ModelSerializer):
    class Meta:
        model = Testimonial
        fields = ["quote", "author", "role"]
