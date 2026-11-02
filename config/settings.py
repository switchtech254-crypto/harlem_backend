"""Harlem Store backend settings (environment driven)."""
import os
import sys
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

TESTING = "test" in sys.argv


def env(key, default=""):
    return os.environ.get(key, default)


def env_bool(key, default=False):
    return os.environ.get(key, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_list(key, default=""):
    return [v.strip() for v in os.environ.get(key, default).split(",") if v.strip()]


DEBUG = env_bool("DJANGO_DEBUG", False)
SECRET_KEY = env("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if DEBUG or TESTING:
        SECRET_KEY = "insecure-development-key-do-not-use-in-production"
    else:
        raise ImproperlyConfigured("Set DJANGO_SECRET_KEY.")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "django_filters",
    "corsheaders",
    "drf_spectacular",
    "apps.core",
    "apps.catalog",
    "apps.orders",
    "apps.storefront",
    "apps.contact",
    "apps.payments",
    "apps.notifications",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]

DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}", conn_max_age=600
    )
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Nairobi"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = Path(env("MEDIA_ROOT", str(BASE_DIR / "media")))
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        if (DEBUG or TESTING)
        else "whitenoise.storage.CompressedManifestStaticFilesStorage"
    },
}

# ---- Media storage ----------------------------------------------------
# Uploaded images (products, banners, ...) go to Cloudinary when CLOUDINARY_URL is set
# (format: cloudinary://API_KEY:API_SECRET@CLOUD_NAME). Without it, files are saved to
# MEDIA_ROOT, which is fine for local development only (Django does not serve /media/
# when DEBUG is off, and many hosts wipe the disk on every deploy).
CLOUDINARY_URL = env("CLOUDINARY_URL")
if CLOUDINARY_URL:
    # cloudinary_storage must come before staticfiles, cloudinary after it.
    INSTALLED_APPS.insert(INSTALLED_APPS.index("django.contrib.staticfiles"), "cloudinary_storage")
    INSTALLED_APPS.insert(INSTALLED_APPS.index("django.contrib.staticfiles") + 1, "cloudinary")
    STORAGES["default"] = {"BACKEND": "cloudinary_storage.storage.MediaCloudinaryStorage"}
    CLOUDINARY_STORAGE = {"SECURE": True}
elif not (DEBUG or TESTING):
    import warnings

    warnings.warn(
        "CLOUDINARY_URL is not set: uploaded images will be stored on the server's local disk "
        "and will not be served in production.",
        RuntimeWarning,
        stacklevel=1,
    )

# ---- API --------------------------------------------------------------
_rate = lambda v: "100000/min" if TESTING else v  # noqa: E731
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    # Secure by default: public endpoints opt in with AllowAny.
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAdminUser"],
    "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend"],
    "DEFAULT_PAGINATION_CLASS": "apps.core.pagination.StandardPagination",
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": _rate("240/min"),
        "user": _rate("600/min"),
        "orders": _rate("10/hour"),
        "track": _rate("30/hour"),
        "contact": _rate("10/hour"),
        "reviews": _rate("10/hour"),
        "mpesa_push": _rate("10/hour"),
        "mpesa_status": _rate("900/hour"),
        "track_poll": _rate("1200/hour"),
    },
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"]
    + (["rest_framework.renderers.BrowsableAPIRenderer"] if DEBUG else []),
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}
SPECTACULAR_SETTINGS = {
    "TITLE": "Harlem Store API",
    "DESCRIPTION": "Storefront and management API for Harlem Store.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", "http://localhost:3000")

# ---- Store ------------------------------------------------------------
LOW_STOCK_THRESHOLD = int(env("LOW_STOCK_THRESHOLD", "5"))
STORE_NOTIFICATION_EMAILS = env_list("STORE_NOTIFICATION_EMAILS")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "Harlem Store <no-reply@harlemstore.co.ke>")

if env("EMAIL_HOST"):
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = env("EMAIL_HOST")
    EMAIL_PORT = int(env("EMAIL_PORT", "587"))
    EMAIL_HOST_USER = env("EMAIL_HOST_USER")
    EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD")
    # Port 587 -> STARTTLS (EMAIL_USE_TLS). Port 465 -> implicit SSL (EMAIL_USE_SSL=true). Never both.
    EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", False)
    EMAIL_USE_TLS = False if EMAIL_USE_SSL else env_bool("EMAIL_USE_TLS", True)
    EMAIL_TIMEOUT = int(env("EMAIL_TIMEOUT", "20"))  # never hang a worker on a dead mail server
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# ---- M-Pesa (Safaricom Daraja, M-Pesa Express / STK push) ---------------
# Get the key/secret from your Daraja app, the shortcode + passkey from the Express simulator
# (sandbox shortcode is 174379). The callback URL must be PUBLIC HTTPS: in development expose
# Django with ngrok / cloudflared and put that URL in MPESA_CALLBACK_BASE_URL.
MPESA_ENV = env("MPESA_ENV", "sandbox").strip().lower()
if MPESA_ENV not in {"sandbox", "production"}:
    raise ImproperlyConfigured("MPESA_ENV must be 'sandbox' or 'production'.")
MPESA_CONSUMER_KEY = env("MPESA_CONSUMER_KEY")
MPESA_CONSUMER_SECRET = env("MPESA_CONSUMER_SECRET")
MPESA_SHORTCODE = env("MPESA_SHORTCODE")
MPESA_PASSKEY = env("MPESA_PASSKEY")
# CustomerPayBillOnline (Paybill) or CustomerBuyGoodsOnline (Till). For a Till, PartyB is the till number.
MPESA_TRANSACTION_TYPE = env("MPESA_TRANSACTION_TYPE", "CustomerPayBillOnline")
MPESA_PARTY_B = env("MPESA_PARTY_B") or MPESA_SHORTCODE
MPESA_CALLBACK_BASE_URL = env("MPESA_CALLBACK_BASE_URL").rstrip("/")
# Random string placed in the callback URL path so only Safaricom (who is given the URL) can call it.
MPESA_CALLBACK_SECRET = env("MPESA_CALLBACK_SECRET")
MPESA_BASE_URL = env("MPESA_BASE_URL") or (
    "https://sandbox.safaricom.co.ke" if MPESA_ENV == "sandbox" else "https://api.safaricom.co.ke"
)
MPESA_MAX_ATTEMPTS_PER_ORDER = int(env("MPESA_MAX_ATTEMPTS_PER_ORDER", "5"))
MPESA_ENABLED = all(
    [MPESA_CONSUMER_KEY, MPESA_CONSUMER_SECRET, MPESA_SHORTCODE, MPESA_PASSKEY,
     MPESA_CALLBACK_BASE_URL, MPESA_CALLBACK_SECRET]
)
if MPESA_ENABLED and not (DEBUG or TESTING):
    if not MPESA_CALLBACK_BASE_URL.startswith("https://"):
        raise ImproperlyConfigured("MPESA_CALLBACK_BASE_URL must be https:// in production.")
    if len(MPESA_CALLBACK_SECRET) < 24:
        raise ImproperlyConfigured("MPESA_CALLBACK_SECRET must be at least 24 random characters.")

# ---- Notifications (email + Telegram) -----------------------------------
# From address for payment receipts / payment alerts. The SMTP account must be allowed to send as it.
PAYMENTS_FROM_EMAIL = env("PAYMENTS_FROM_EMAIL", "Harlem Store Payments <payments@harlemstore.co.ke>")
# Shown to customers as "how to reach us" and used as Reply-To (falls back to Site settings' contact email).
SUPPORT_EMAIL = env("SUPPORT_EMAIL")
# Public URL of the Next.js storefront (used for the "Track your order" link in emails).
FRONTEND_URL = env("FRONTEND_URL", "http://localhost:3000")
# Public URL of this backend (used for the "Open order in admin" link sent to the owner).
BACKEND_PUBLIC_URL = env("BACKEND_PUBLIC_URL") or MPESA_CALLBACK_BASE_URL or "http://localhost:8000"
# Telegram bot: token from @BotFather; chat id(s) of the owner / staff group, comma separated. Blank = off.
TELEGRAM_BOT_TOKEN = env("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = env("TELEGRAM_CHAT_ID")
TELEGRAM_API_BASE = env("TELEGRAM_API_BASE", "https://api.telegram.org")
# Send on a background thread so checkout / Safaricom's callback never wait for SMTP.
NOTIFICATIONS_ASYNC = env_bool("NOTIFICATIONS_ASYNC", not TESTING)

# ---- Production hardening ---------------------------------------------
if not (DEBUG or TESTING):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(env("SECURE_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_CONTENT_TYPE_NOSNIFF = True

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
}
