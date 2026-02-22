import django_filters
from monitoring.models import Observation, Basin

class ObservationFilter(django_filters.FilterSet):
    basin_id = django_filters.CharFilter(field_name="basin__basin_id", lookup_expr="exact")
    data_type = django_filters.CharFilter(field_name="data_type__name", lookup_expr="iexact")
    datetime_after = django_filters.IsoDateTimeFilter(field_name="datetime", lookup_expr="gte")
    datetime_before = django_filters.IsoDateTimeFilter(field_name="datetime", lookup_expr="lte")
    over_threshold = django_filters.NumberFilter(field_name="value", lookup_expr="gt")

    class Meta:
        model = Observation
        fields = ["basin_id", "data_type", "datetime_after", "datetime_before", "over_threshold"]

class BasinFilter(django_filters.FilterSet):
    basin_id = django_filters.CharFilter(field_name="basin_id", lookup_expr="icontains")
    name = django_filters.CharFilter(field_name="name", lookup_expr="icontains")

    class Meta:
        model = Basin
        fields = ["basin_id", "name"]
