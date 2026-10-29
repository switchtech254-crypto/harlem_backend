
import os
import sys

# HostPinnacle Django application root
PROJECT_ROOT = "/home3/harlemst/harlem_api"

# Add the Django project root to Python's import path
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Django settings module
os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "config.settings"
)

# Load Django's WSGI application
from django.core.wsgi import get_wsgi_application

application = get_wsgi_application()
