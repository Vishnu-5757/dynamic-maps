from django.urls import path
from .views import dashboard_view ,timeseries_api

urlpatterns = [
    
  path("monitoring/dashboard/", dashboard_view, name="monitoring_dashboard"),

path("monitoring/api/timeseries/", timeseries_api, name="monitoring_timeseries_api"),
]
