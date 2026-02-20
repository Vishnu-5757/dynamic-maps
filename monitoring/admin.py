from django.contrib import admin
from .models import Basin, BasinRelation, DataType, Observation

@admin.register(Basin)
class BasinAdmin(admin.ModelAdmin):
    list_display = ('basin_id', 'name')
    search_fields = ('basin_id', 'name')

@admin.register(BasinRelation)
class BasinRelationAdmin(admin.ModelAdmin):
    list_display = ('from_basin', 'to_basin', 'relation_type', 'weight')
    list_filter = ('relation_type',)

@admin.register(DataType)
class DataTypeAdmin(admin.ModelAdmin):
    list_display = ('name',)

@admin.register(Observation)
class ObservationAdmin(admin.ModelAdmin):
    list_display = ('basin', 'data_type', 'datetime', 'value', 'source')
    list_filter = ('data_type',)
    search_fields = ('basin__basin_id', 'source')
