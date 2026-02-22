from collections import deque
from decimal import Decimal
from datetime import timedelta
from django.utils import timezone
from django.db.models import Sum
from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from django.shortcuts import get_object_or_404
from monitoring import cache_utils
from monitoring.models import Basin, BasinRelation, DataType, Observation
from .serializers import (
    BasinSerializer,
    BasinRelationSerializer,
    DataTypeSerializer,
    ObservationSerializer,
)
from .filters import ObservationFilter, BasinFilter
from rest_framework import filters
from django_filters.rest_framework import DjangoFilterBackend


class BasinViewSet(viewsets.ModelViewSet):
    queryset = Basin.objects.all().order_by("basin_id")
    serializer_class = BasinSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = BasinFilter
    search_fields = ["basin_id", "name"]
    ordering_fields = ["basin_id", "name", "created_at"]

    @action(detail=True, methods=["get"])
    def timeseries(self, request, pk=None):
        """
        GET /api/basins/{id}/timeseries?data_type=rainfall&window=24h
        """
        basin = self.get_object()
        data_type_name = request.query_params.get("data_type")
        window = request.query_params.get("window", "24h")

        
        if window.endswith("h"):
            hours = int(window[:-1])
        else:
            try:
                hours = int(window)
            except Exception:
                hours = 24
        cutoff = timezone.now() - timedelta(hours=hours)

        if not data_type_name:
            return Response({"detail": "data_type query param is required"}, status=400)
        try:
            dt = DataType.objects.get(name__iexact=data_type_name)
        except DataType.DoesNotExist:
            return Response({"detail": "data_type not found"}, status=400)

        qs = Observation.objects.filter(basin=basin, data_type=dt, datetime__gte=cutoff).order_by("datetime")
        
        data = [{"datetime": o.datetime, "value": o.value} for o in qs]
        ser = ObservationSerializer(qs, many=True)
        return Response({"basin": BasinSerializer(basin).data, "data": ser.data})

    @action(detail=True, methods=["get"])
    def upstream_aggregate(self, request, pk=None):
        """
        GET /api/basins/{id}/upstream_aggregate?data_type=Rainfall&window=24h&depth=1
        Uses Redis cache (via cache_utils). Cached payload is returned if available.
        """
        basin = self.get_object()
        data_type_name = request.query_params.get("data_type")
        window = request.query_params.get("window", "24h")
        depth = int(request.query_params.get("depth", 1))

        if not data_type_name:
            return Response({"detail": "data_type query param is required"}, status=400)

        # try cache
        cached = cache_utils.get_upstream_cache(basin.basin_id, data_type_name, window, depth)
        if cached is not None:
            return Response(cached)

        # compute cutoff
        if window.endswith("h"):
            try:
                hours = int(window[:-1])
            except ValueError:
                return Response({"detail": "invalid window format"}, status=400)
        else:
            try:
                hours = int(window)
            except ValueError:
                return Response({"detail": "invalid window format"}, status=400)

        cutoff = timezone.now() - timedelta(hours=hours)

        try:
            dt = DataType.objects.get(name__iexact=data_type_name)
        except DataType.DoesNotExist:
            return Response({"detail": "data_type not found"}, status=400)

        # BFS for upstream nodes (1-hop or multi-hop depending on depth)
        upstream_ids = set()
        queue = deque()
        visited = set()

        queue.append((basin.id, 0))
        visited.add(basin.id)

        while queue:
            cur_id, cur_depth = queue.popleft()
            if cur_depth >= 1:
                upstream_ids.add(cur_id)
            if depth and cur_depth >= depth:
                continue
            relations = BasinRelation.objects.filter(to_basin_id=cur_id).only("from_basin_id")
            for rel in relations:
                nid = rel.from_basin_id
                if nid not in visited:
                    visited.add(nid)
                    queue.append((nid, cur_depth + 1))

        basin_sum = (
            Observation.objects.filter(basin=basin, data_type=dt, datetime__gte=cutoff)
            .aggregate(total=Sum("value"))["total"]
            or Decimal("0")
        )

        upstream_sum = Decimal("0")
        if upstream_ids:
            upstream_sum = (
                Observation.objects.filter(basin_id__in=upstream_ids, data_type=dt, datetime__gte=cutoff)
                .aggregate(total=Sum("value"))["total"]
                or Decimal("0")
            )

        payload = {
            "basin_id": basin.basin_id,
            "data_type": dt.name,
            "window_hours": hours,
            "basin_total": str(basin_sum),
            "upstream_total": str(upstream_sum),
            "upstream_count": len(upstream_ids),
        }

        
        try:
            cache_utils.set_upstream_cache(basin.basin_id, data_type_name, window, depth, payload)
        except Exception:
            logger.exception("Failed to set upstream cache for %s", basin.basin_id)

        return Response(payload)




class BasinRelationViewSet(viewsets.ModelViewSet):
    queryset = BasinRelation.objects.select_related("from_basin", "to_basin").all()
    serializer_class = BasinRelationSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    ordering_fields = ["from_basin", "to_basin", "weight"]

class DataTypeViewSet(viewsets.ModelViewSet):
    queryset = DataType.objects.all()
    serializer_class = DataTypeSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name"]

class ObservationViewSet(viewsets.ModelViewSet):
    queryset = Observation.objects.select_related("basin", "data_type").all()
    serializer_class = ObservationSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = ObservationFilter
    search_fields = ["basin__basin_id", "data_type__name"]
    ordering_fields = ["datetime", "value"]

    
    @action(detail=False, methods=["get"])
    def recent(self, request):
        """
        /api/observations/recent/?data_type=Rainfall&hours=24
        """
        data_type_name = request.query_params.get("data_type")
        hours = int(request.query_params.get("hours", 24))
        if not data_type_name:
            return Response({"detail": "data_type required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            dt = DataType.objects.get(name__iexact=data_type_name)
        except DataType.DoesNotExist:
            return Response({"detail": "data_type not found"}, status=status.HTTP_400_BAD_REQUEST)

        cutoff = timezone.now() - timedelta(hours=hours)
        qs = Observation.objects.filter(data_type=dt, datetime__gte=cutoff).order_by("datetime")
        page = self.paginate_queryset(qs)
        if page is not None:
            ser = ObservationSerializer(page, many=True)
            return self.get_paginated_response(ser.data)
        ser = ObservationSerializer(qs, many=True)
        return Response(ser.data)
