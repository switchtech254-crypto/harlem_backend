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


## M-Pesa payments (Daraja M-Pesa Express / STK push)

Customers place an order, then tap **Pay with M-Pesa**: the backend sends an STK push, the customer enters their PIN,
Safaricom calls our callback, and the order is marked **Paid** and **Confirmed** (a `Payment` row with the M-Pesa receipt is created).
Without credentials the feature is simply off (`/api/settings/` reports `mpesa_enabled: false`).

### Setup (sandbox)
1. In `.env` set `MPESA_CONSUMER_KEY`, `MPESA_CONSUMER_SECRET`, `MPESA_PASSKEY` (from your Daraja app / Express simulator) and `MPESA_SHORTCODE=174379`.
2. Generate a callback secret: `python -c "import secrets;print(secrets.token_urlsafe(32))"` -> `MPESA_CALLBACK_SECRET`.
3. Safaricom must reach your backend over **public HTTPS**. Locally run `ngrok http 8000` (or cloudflared) and set
   `MPESA_CALLBACK_BASE_URL=https://<your-tunnel>.ngrok-free.app`. Add that host to `DJANGO_ALLOWED_HOSTS`.
4. `python manage.py migrate`, restart, then tick **Online ordering enabled** in Site settings.

### Endpoints
| Method & path | Purpose |
|---|---|
| `POST /api/payments/mpesa/stk-push/` | `{reference, phone, pay_phone?}`: sends the prompt for the order's outstanding balance. `phone` must be the order's phone. Repeating within ~90s returns the same pending prompt instead of charging twice. |
| `GET /api/payments/mpesa/status/<checkout_request_id>/` | Poll for the result. If the callback is late (>20s) the API asks Daraja directly (STK Query), rate-limited. |
| `POST /api/payments/mpesa/callback/<MPESA_CALLBACK_SECRET>/` | Safaricom's result. Wrong secret -> 404. Always answers 200 for valid calls so Safaricom does not retry. |

### How it stays safe
* The amount is always the order's **balance due** computed on the server; the browser never sends an amount.
* Callbacks are idempotent; a duplicate never double-credits, and a failure result can never undo a success.
* If money arrived (ResultCode 0) it is **always recorded**, even for an unexpected amount, which is flagged `needs_review`
  and shown in admin. A late success after we had guessed "timeout" is honoured.
* Max `MPESA_MAX_ATTEMPTS_PER_ORDER` (5) prompts per order; per-IP throttles on push (10/h) and polling.
* Request bodies (they contain the passkey) are never logged. Timestamps use East Africa Time.
* Callback URL secret + HTTPS are required in production (settings refuse to start otherwise).

### Admin
* **Payments -> M-Pesa transactions**: every attempt, receipt, raw callback, `needs_review` flag; action *Ask M-Pesa for the latest status* for missed callbacks.
* **Orders**: M-Pesa attempts are listed on each order; action *Send M-Pesa payment prompt* lets staff request payment for phone orders.
* Cron: `python manage.py mpesa_reconcile` every few minutes settles anything still pending.

### Before going live
Complete Safaricom's *Go Live* for your shortcode, then set `MPESA_ENV=production` with your production key/secret/shortcode/passkey
(for a Till use `MPESA_TRANSACTION_TYPE=CustomerBuyGoodsOnline` and `MPESA_PARTY_B=<till>`), keep the callback on HTTPS,
and make one small real payment (e.g. KSh 10) end to end. Use a shared cache (Redis) in production so throttles and the token cache work across workers.

## Design notes
* **Server is the source of truth** for price, size validity, stock and promo rules; client prices are ignored.
* Checkout runs in one transaction with row locks (`select_for_update`) – no overselling; failures roll back.
* Order items snapshot name/price, so later price edits never change past orders.
* Order statuses follow an enforced workflow (pending → confirmed → processing → ready → completed; cancel from any open state restores stock and promo usage).
* Phones are normalised to `+2547XXXXXXXX`; order tracking needs reference **and** phone.
* Secure defaults: API is admin-only unless a view opts in; throttling on orders/contact/tracking/reviews; image size limits; HTTPS/HSTS/secure cookies when `DJANGO_DEBUG` is false.

## Before production
* Set `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `DATABASE_URL`, SMTP vars, `STORE_NOTIFICATION_EMAILS`.
* **Image uploads → Cloudinary.** Set `CLOUDINARY_URL` (Cloudinary dashboard → API Keys). With it set, every admin upload
  (products, categories, banners) is stored on Cloudinary and the API returns `https://res.cloudinary.com/...` URLs.
  Without it files go to local disk, which Django does not serve when `DEBUG` is off. If you already uploaded images locally,
  run `python manage.py migrate_media --dry-run` and then `python manage.py migrate_media` once.
  On the Next.js side set `NEXT_PUBLIC_CLOUDINARY_CLOUD_NAME` (the cloud name from the URL).
* Use a shared cache (Redis) so throttles work across gunicorn workers.
* Not included (natural next steps): customer accounts, SMS notifications, refunds/reversals via Daraja.
