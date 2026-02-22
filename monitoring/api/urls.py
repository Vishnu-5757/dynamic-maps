from rest_framework.routers import DefaultRouter
from django.urls import path, include
from .views import BasinViewSet, BasinRelationViewSet, DataTypeViewSet, ObservationViewSet

router = DefaultRouter()
router.register(r"basins", BasinViewSet, basename="basin")
router.register(r"basin-relations", BasinRelationViewSet, basename="basinrelation")
router.register(r"data-types", DataTypeViewSet, basename="datatype")
router.register(r"observations", ObservationViewSet, basename="observation")

urlpatterns = [
    path("api/", include(router.urls)),
]
