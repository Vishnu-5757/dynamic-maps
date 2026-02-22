from django.db.models import Sum
from .models import BasinRelation, Observation

def get_upstream_aggregation(target_basin, data_type_obj):
    """
    Finds all basins that flow INTO the target_basin and 
    returns the total sum of their values.
    """
    
    upstream_ids = BasinRelation.objects.filter(
        to_basin=target_basin,
        relation_type='upstream_to_downstream'
    ).values_list('from_basin_id', flat=True)
    
    
    total = Observation.objects.filter(
        basin_id__in=upstream_ids,
        data_type=data_type_obj
    ).aggregate(total=Sum('value'))['total']
    
    return total or 0