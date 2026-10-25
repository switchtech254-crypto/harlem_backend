from django.urls import path

from .views import DealsView, HomepageView, SiteSettingsView

urlpatterns = [
    path("homepage/", HomepageView.as_view(), name="homepage"),
    path("settings/", SiteSettingsView.as_view(), name="site-settings"),
    path("deals/", DealsView.as_view(), name="deals"),
]
