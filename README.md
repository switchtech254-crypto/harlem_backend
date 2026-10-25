# Harlem Store – Django backend

Django 5.2 + Django REST Framework. Staff manage everything in **Django admin** (`/admin/`);
the Next.js storefront reads a public JSON API (`/api/`). Interactive docs: `/api/docs/`.

## Quick start
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DJANGO_DEBUG=true            # see .env.example for all settings
python manage.py migrate
python manage.py createsuperuser
python manage.py setup_roles        # "Store Manager" and "Order Desk" groups
python manage.py seed_demo --frontend-public ../your-next-app/public   # loads current hard-coded data + images
python manage.py runserver
python manage.py test               # 20 tests
```
Docker: `cp .env.example .env && docker compose up --build` (Postgres included).

## What lives where
| App | Models | Admin highlights |
|---|---|---|
| `catalog` | Category, Product, ProductImage, ProductVariant (size + stock), Review | inline sizes/stock/images, sale price, bulk activate, review approval, CSV export |
| `orders` | PromoCode, Order, OrderItem (price snapshot), OrderStatusHistory, Payment | status workflow actions, cancel returns stock, M-Pesa/cash payments auto-update paid status, manual (phone) orders |
| `storefront` | SiteSettings (singleton), HeroSlide, Banner, ServiceHighlight, Testimonial, Deal | edit every homepage section, schedule slides/banners/deals |
| `contact` | ContactMessage | inbox with status, assignment, spam, CSV export |

## API (all JSON, prices are whole KSh integers)
| Method & path | Purpose |
|---|---|
| `GET /api/homepage/` | Everything `HomeClient` renders in one call (slides, banners, services, featured, categories, bestsellers, deals, testimonials, settings, `server_time`) |
| `GET /api/products/` | Filters: `category`, `q`, `min_price`, `max_price`, `in_stock`, `on_sale`, `featured`, `bestseller`; `ordering=price\|-price\|name\|newest\|featured`; `page`, `page_size` |
| `GET /api/products/{id}/` | Detail (`id` is the slug, e.g. `court-sneaker`) with `images`, per-size `in_stock`/`low_stock` |
| `GET /api/products/{id}/related/` | "Complete your collection" (4 items) |
| `GET/POST /api/products/{id}/reviews/` | Approved reviews / submit (held for moderation) |
| `GET /api/categories/` | Categories with `product_count` |
| `GET /api/deals/` | Live deals + `server_time` for the countdown |
| `GET /api/settings/` | Contact details, announcement, promo code, `online_ordering_enabled` |
| `POST /api/cart/quote/` | Send the localStorage cart `{items:[{id,size,qty}], promo_code?}` → server-priced lines, discount, total, per-item errors |
| `POST /api/orders/` | Place an order (403 while `online_ordering_enabled` is off) |
| `POST /api/orders/track/` | `{reference, phone}` → status timeline |
| `POST /api/contact/` | Enquiry / team order / branding request (rate-limited, honeypot field `website`) |
| `GET /api/staff/dashboard/` | Staff only: 30-day revenue, orders by status, low stock, top products |

## Wiring up the Next.js app
1. Set `NEXT_PUBLIC_API_URL` and add the frontend origin to `CORS_ALLOWED_ORIGINS`.
2. Replace `lib/products.ts` imports with `fetch` calls. Response fields match the existing `Product` type
   (`id`, `name`, `price`, `category`, `image`, `description`, `sizes`) plus extras (`original_price`, `in_stock`, `rating`, `badge`).
3. `sizes` is `null` (not `[]`) for unsized items so `product.sizes && …` keeps working.
4. Keep the cart in localStorage; call `/api/cart/quote/` on the cart page so prices and stock come from the server.
5. `HomeClient`: `services[].icon` is a lucide icon name (map it to the component); use `deals[].ends_at` and `server_time`
   for the countdown instead of "end of day"; show the announcement from `settings`.
6. When ready to take orders online, tick **Online ordering enabled** in *Site settings* and POST the checkout form to `/api/orders/`.

## Design notes
* **Server is the source of truth** for price, size validity, stock and promo rules; client prices are ignored.
* Checkout runs in one transaction with row locks (`select_for_update`) – no overselling; failures roll back.
* Order items snapshot name/price, so later price edits never change past orders.
* Order statuses follow an enforced workflow (pending → confirmed → processing → ready → completed; cancel from any open state restores stock and promo usage).
* Phones are normalised to `+2547XXXXXXXX`; order tracking needs reference **and** phone.
* Secure defaults: API is admin-only unless a view opts in; throttling on orders/contact/tracking/reviews; image size limits; HTTPS/HSTS/secure cookies when `DJANGO_DEBUG` is false.

## Before production
* Set `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `DATABASE_URL`, SMTP vars, `STORE_NOTIFICATION_EMAILS`.
* Serve `/media/` via nginx or object storage (e.g. `django-storages` + S3) – Django only serves it in DEBUG.
* Use a shared cache (Redis) so throttles work across gunicorn workers.
* Not included (natural next steps): M-Pesa STK-push integration (the `Payment` model is ready for it), customer accounts, SMS notifications.
