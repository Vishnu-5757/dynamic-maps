from django.db import models

class Basin(models.Model):

    basin_id = models.CharField(max_length=100, unique=True, db_index=True)
    name = models.CharField(max_length=255, blank=True, null=True)
    metadata = models.JSONField(blank=True, null=True)  

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.basin_id} - {self.name or ''}"


class BasinRelation(models.Model):
    RELATION_TYPE_UPSTREAM = 'upstream_to_downstream'
    RELATION_TYPE_CHOICES = [
        (RELATION_TYPE_UPSTREAM, 'upstream_to_downstream'),
        ('other', 'other'),
    ]

    from_basin = models.ForeignKey(
        Basin, related_name='outbound_relations', on_delete=models.CASCADE
    )
    to_basin = models.ForeignKey(
        Basin, related_name='inbound_relations', on_delete=models.CASCADE
    )
    relation_type = models.CharField(max_length=64, choices=RELATION_TYPE_CHOICES)
    weight = models.FloatField(blank=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['from_basin', 'to_basin', 'relation_type'],
                name='unique_basin_relation'
            )
        ]

    def __str__(self):
        return f"{self.from_basin.basin_id} -> {self.to_basin.basin_id} ({self.relation_type})"


class DataType(models.Model):
    name = models.CharField(max_length=64, unique=True)
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.name


class Observation(models.Model):
    basin = models.ForeignKey(Basin, on_delete=models.CASCADE, related_name='observations')
    
    data_type = models.ForeignKey(DataType, on_delete=models.CASCADE, related_name='observations')

    
    datetime = models.DateTimeField()

    
    value = models.DecimalField(max_digits=12, decimal_places=4)

    
    source = models.CharField(max_length=128, default='unknown')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        
        constraints = [
            models.UniqueConstraint(
                fields=['basin', 'data_type', 'datetime', 'source'],
                name='unique_observation_per_source_dt'
            )
        ]
        indexes = [
            models.Index(fields=['basin', 'data_type', 'datetime'], name='idx_basin_dt_type'),
            models.Index(fields=['data_type', 'datetime'], name='idx_type_datetime'),
            models.Index(fields=['datetime'], name='idx_datetime'),
        ]
        ordering = ['-datetime']

    def __str__(self):
        return f"{self.basin.basin_id} | {self.data_type.name} | {self.datetime} = {self.value}"
