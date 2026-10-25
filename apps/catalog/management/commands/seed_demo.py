"""Load the data currently hard-coded in the Next.js storefront (lib/products.ts, HomeClient.tsx).

    python manage.py seed_demo --frontend-public ../harlem-store/public

--frontend-public (optional) imports the referenced /images/... files into media storage.
Safe to re-run: records are matched by slug / key and updated.
"""
from pathlib import Path

from django.core.files import File
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.catalog.models import Category, Product, ProductImage, ProductVariant
from apps.orders.models import PromoCode
from apps.storefront.models import Banner, Deal, HeroSlide, ServiceHighlight, SiteSettings, Testimonial

CLOTHING = ["S", "M", "L", "XL", "XXL"]
SHOES = ["39", "40", "41", "42", "43", "44", "45"]
WAIST = ["30", "32", "34", "36", "38"]
IMG = "/images/homepage/"

CATEGORIES = [
    ("jerseys", "Jerseys & Branding", "Custom names, numbers and club badges.", "jerseys.jpg"),
    ("uniforms", "Team Uniforms & Socks", "Full kits for clubs, schools and teams.", "jerseys.jpg"),
    ("balls", "Balls", "Match and training balls.", "balls.jpg"),
    ("sports-shoes", "Sports Shoes", "Boots and trainers built to perform.", "boots.jpg"),
    ("jeans", "Men's Jeans", "Everyday denim, sharp fits.", "jeans.jpg"),
    ("sneakers", "Sneakers", "Street-ready classics.", "sneakers.jpg"),
]

# slug, name, price, category, image, sizes, description, tracked
PRODUCTS = [
    ("home-jersey", "Classic Home Jersey", 2500, "jerseys", "jerseys.jpg", CLOTHING, "Breathable match jersey. Add your name, number and badge.", True),
    ("custom-branding", "Custom Jersey Branding", 500, "jerseys", "jerseys.jpg", None, "Name, number and logo printing per jersey.", False),
    ("team-kit", "Full Team Kit (Jersey + Shorts)", 3500, "uniforms", "jerseys.jpg", CLOTHING, "Matching jersey and shorts set for every player.", True),
    ("team-socks", "Team Socks", 450, "uniforms", "jerseys.jpg", ["Junior", "Adult"], "Cushioned, striped football socks.", True),
    ("match-ball", "Match Football", 2800, "balls", "balls.jpg", None, "Size 5 stitched match ball.", True),
    ("basketball", "Indoor/Outdoor Basketball", 3200, "balls", "balls.jpg", None, "Grippy composite size 7 basketball.", True),
    ("pro-boots", "Pro Football Boots", 6500, "sports-shoes", "boots.jpg", SHOES, "Firm-ground boots with responsive studs.", True),
    ("runner", "Training Trainers", 4800, "sports-shoes", "boots.jpg", SHOES, "Light, cushioned training shoe.", True),
    ("slim-jeans", "Slim Fit Jeans", 2900, "jeans", "jeans.jpg", WAIST, "Dark indigo stretch denim.", True),
    ("straight-jeans", "Straight Leg Jeans", 3100, "jeans", "jeans.jpg", WAIST, "Classic straight cut, rigid denim.", True),
    ("court-sneaker", "Harlem Court Sneaker", 5200, "sneakers", "sneakers.jpg", SHOES, "Leather low-top in cream and plum.", True),
    ("street-sneaker", "Street Low Sneaker", 4500, "sneakers", "sneakers.jpg", SHOES, "Everyday comfort, clean style.", True),
]
FEATURED = ["court-sneaker", "pro-boots", "home-jersey", "slim-jeans", "street-sneaker", "match-ball", "team-kit", "straight-jeans"]
BESTSELLERS = ["street-sneaker", "runner", "home-jersey", "court-sneaker", "team-kit", "pro-boots", "slim-jeans", "match-ball"]
DEALS = [("court-sneaker", "Deal", 8, 16), ("pro-boots", "Hot", 13, 40), ("slim-jeans", "Deal", 7, 14), ("runner", "New", 31, 69)]

SERVICES = [
    ("Everyday style", "Sportswear to streetwear", "tags"),
    ("Delivery enquiries", "Contact us for delivery options", "truck"),
    ("Custom branding", "Your name, number and club badge", "shirt"),
    ("Personal service", "Talk to us about your order", "message-circle"),
    ("Team & club orders", "Matching kits for your whole team", "badge-check"),
]


class Command(BaseCommand):
    help = "Seed the database with the storefront's current demo content."

    def add_arguments(self, parser):
        parser.add_argument("--frontend-public", help="Path to the Next.js /public folder to import images from.")

    def attach(self, field, web_path):
        """Save a frontend image (e.g. /images/homepage/jerseys.jpg) into an ImageField."""
        if not self.public:
            return
        src = self.public / web_path.lstrip("/")
        if src.exists():
            with src.open("rb") as fh:
                field.save(src.name, File(fh), save=False)
        else:
            self.stderr.write(f"  ! image not found: {src}")

    @transaction.atomic
    def handle(self, *args, **opts):
        self.public = Path(opts["frontend_public"]).resolve() if opts.get("frontend_public") else None

        cats = {}
        for i, (slug, name, blurb, img) in enumerate(CATEGORIES):
            c, _ = Category.objects.update_or_create(slug=slug, defaults={"name": name, "blurb": blurb, "sort_order": i})
            if self.public and not c.image:
                self.attach(c.image, IMG + img)
                c.save()
            cats[slug] = c

        for i, (slug, name, price, cat, img, sizes, desc, tracked) in enumerate(PRODUCTS):
            p, created = Product.objects.update_or_create(
                slug=slug,
                defaults={"name": name, "price": price, "category": cats[cat], "description": desc,
                          "track_inventory": tracked, "sort_order": i,
                          "is_featured": slug in FEATURED, "is_bestseller": slug in BESTSELLERS},
            )
            for j, size in enumerate(sizes or [""]):
                ProductVariant.objects.get_or_create(product=p, size=size, defaults={"stock": 25, "sort_order": j})
            if self.public and not p.images.exists():
                pi = ProductImage(product=p, alt_text=name)
                self.attach(pi.image, IMG + img)
                if pi.image:
                    pi.save()

        # Promo + settings
        promo, _ = PromoCode.objects.update_or_create(
            code="HARLEM10",
            defaults={"description": "10% off your first purchase", "discount_type": "percent", "value": 10,
                      "first_purchase_only": True},
        )
        s = SiteSettings.get_solo()
        s.featured_promo = promo
        s.delivery_info = "Contact us to confirm delivery options, cost and timing."
        s.save()

        for i, (title, text, icon) in enumerate(SERVICES):
            ServiceHighlight.objects.update_or_create(title=title, defaults={"text": text, "icon": icon, "sort_order": i})
        Testimonial.objects.get_or_create(
            author="Brian O.",
            defaults={"quote": "Harlem Store kitted out our whole squad — jerseys, socks and branding, all done fast and looking sharp.",
                      "role": "Club coach, Nairobi"},
        )

        slides = [
            ("Sneakers & Sportswear", "Fresh kicks. Everyday confidence. Find your next favourite at Harlem Store.",
             "collection-hero.jpg", "Blue and white running shoes on a bright blue background", "sneakers"),
            ("Jerseys & Team Kits", "For your club. For your crew. Make every match your own.",
             "jerseys.jpg", "Harlem Store jerseys and teamwear", "jerseys"),
        ]
        for i, (title, text, img, alt, cat) in enumerate(slides):
            h, _ = HeroSlide.objects.get_or_create(title=title, defaults={"text": text, "image_alt": alt,
                                                                        "category": cats[cat], "sort_order": i})
            if self.public and not h.image:
                self.attach(h.image, IMG + img)
                h.save()

        banners = [
            ("side_panel", "", "Fresh kicks", "The sneaker collection", "", "See more products", "/shop?category=sneakers", "sneaker-panel.jpg", "Yellow statement sneaker"),
            ("collection_panel", "", "The collection", "Sport meets street", "", "See more products", "/shop", "jerseys.jpg", "Harlem Store collection"),
            ("bestsellers_banner", "", "Latest bestsellers", "", "", "See more products", "/shop", "bestsellers-banner.jpg", "Plum and cream high-top sneaker at dusk"),
            ("deals_banner", "Deals of the week", "Bold deals for your everyday style.", "",
             "This week only — sneakers, boots, denim and teamwear picked for you.", "Buy products", "/shop", "deals-banner.jpg", "Plum and cream high-top sneaker"),
        ]
        for i, (place, eyebrow, heading, sub, body, label, url, img, alt) in enumerate(banners):
            b, _ = Banner.objects.get_or_create(placement=place, defaults={
                "eyebrow": eyebrow, "heading": heading, "subheading": sub, "body": body,
                "link_label": label, "link_url": url, "image_alt": alt, "sort_order": i})
            if self.public and not b.image:
                self.attach(b.image, IMG + img)
                b.save()

        for i, (slug, badge, sold, avail) in enumerate(DEALS):
            Deal.objects.get_or_create(product=Product.objects.get(slug=slug),
                                       defaults={"badge": badge, "sold": sold, "available": avail, "sort_order": i})
        self.stdout.write(self.style.SUCCESS("Seeded categories, products, content, promo HARLEM10 and deals."))
