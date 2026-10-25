from rest_framework.routers import SimpleRouter

from .views import CategoryViewSet, ProductViewSet

router = SimpleRouter()
router.register("categories", CategoryViewSet, basename="category")
router.register("products", ProductViewSet, basename="product")
urlpatterns = router.urls
