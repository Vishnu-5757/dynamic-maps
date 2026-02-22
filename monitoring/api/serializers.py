from rest_framework import serializers
from monitoring.models import Basin, BasinRelation, DataType, Observation

class BasinSerializer(serializers.ModelSerializer):
    class Meta:
        model = Basin
        fields = ["id", "basin_id", "name", "metadata", "created_at", "updated_at"]

class BasinRelationSerializer(serializers.ModelSerializer):
    from_basin = BasinSerializer(read_only=True)
    to_basin = BasinSerializer(read_only=True)
    from_basin_id = serializers.PrimaryKeyRelatedField(
        queryset=Basin.objects.all(), source="from_basin", write_only=True
    )
    to_basin_id = serializers.PrimaryKeyRelatedField(
        queryset=Basin.objects.all(), source="to_basin", write_only=True
    )

    class Meta:
        model = BasinRelation
        fields = [
            "id",
            "from_basin",
            "to_basin",
            "from_basin_id",
            "to_basin_id",
            "relation_type",
            "weight",
        ]

class DataTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = DataType
        fields = ["id", "name", "description"]

class ObservationSerializer(serializers.ModelSerializer):
    basin = BasinSerializer(read_only=True)
    basin_id = serializers.PrimaryKeyRelatedField(
        queryset=Basin.objects.all(), source="basin", write_only=True
    )
    data_type = DataTypeSerializer(read_only=True)
    data_type_id = serializers.PrimaryKeyRelatedField(
        queryset=DataType.objects.all(), source="data_type", write_only=True
    )

    class Meta:
        model = Observation
        fields = [
            "id",
            "basin",
            "basin_id",
            "data_type",
            "data_type_id",
            "datetime",
            "value",
            "source",
            "created_at",
            "updated_at",
        ]
