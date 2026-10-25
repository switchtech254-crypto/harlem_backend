from django.urls import path

from .views import DashboardView, HealthView

urlpatterns = [
    path("health/", HealthView.as_view(), name="health"),
    path("staff/dashboard/", DashboardView.as_view(), name="staff-dashboard"),
]
