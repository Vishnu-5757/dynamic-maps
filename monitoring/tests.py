import pytest
from django.urls import reverse
from django.utils import timezone
from .models import Basin, DataType, Observation, BasinRelation
from .logic import get_upstream_aggregation

@pytest.mark.django_db
class TestMonitoringSystem:

    def setup_method(self):
       
        self.dtype = DataType.objects.create(name="Rainfall")

        
        self.upstream_basin = Basin.objects.create(basin_id="UP-01", name="Mountain Peak")
        self.downstream_basin = Basin.objects.create(basin_id="DOWN-01", name="Valley River")

        
        BasinRelation.objects.create(
            from_basin=self.upstream_basin,
            to_basin=self.downstream_basin,
            relation_type=BasinRelation.RELATION_TYPE_UPSTREAM
        )

        
        Observation.objects.create(
            basin=self.upstream_basin,
            data_type=self.dtype,
            datetime=timezone.now(),
            value=15.5,
            source="sensor_01"
        )

    def test_timeseries_endpoint(self, client):
        """Minimal unit test for timeseries endpoint."""
        url = reverse('monitoring_timeseries_api') 
        params = {
            'basin_id': 'UP-01',
            'data_type': 'Rainfall'
        }
        response = client.get(url, params)
        
        assert response.status_code == 200
        data = response.json()
        assert data['ok'] is True
        assert len(data['points']) == 1
        assert float(data['points'][0]['y']) == 15.5

    def test_upstream_aggregation_logic(self):
        """Verify that downstream basin correctly aggregates upstream data."""
        
        result = get_upstream_aggregation(self.downstream_basin, self.dtype)
        
        
        assert float(result) == 15.5