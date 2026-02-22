import json
import logging
import math
from decimal import Decimal
from datetime import datetime, timedelta

from django.shortcuts import render
from django.http import JsonResponse, HttpResponseBadRequest
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.conf import settings

from django.db.models import Sum, Avg, Min, Max, Count
from django.db.models.functions import TruncHour, TruncDay

from .models import Basin, DataType, Observation
from monitoring import cache_utils


logger = logging.getLogger(__name__)

MAX_POINTS_INITIAL = getattr(settings, "DASHBOARD_MAX_POINTS_INITIAL", 800)  
MAX_RAW_POINTS = getattr(settings, "DASHBOARD_MAX_RAW_POINTS", 5000)         
AGGREGATE_HOURLY_THRESHOLD = getattr(settings, "DASHBOARD_AGG_HOURLY_THRESHOLD", 2000)  

def parse_datetime_local(value):
    """Parse HTML datetime-local like '2026-02-22T14:30' -> naive datetime or None"""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                return datetime.strptime(value, fmt)
            except Exception:
                continue
    return None


def dashboard_view(request):
    """
    Renders the dashboard page. The heavy data is fetched via AJAX from /monitoring/api/timeseries/.
    """
    basins = list(Basin.objects.order_by("basin_id").all())
    dtypes = list(DataType.objects.order_by("name").all())

   
    selected_basin = request.GET.get("basin_id") or (basins[0].basin_id if basins else "")
    selected_dtype = request.GET.get("data_type") or (dtypes[0].name if dtypes else "")
    last24 = request.GET.get("last24", "1") in ("1", "true", "True", "on")

    
    context = {
        "basins": basins,
        "dtypes": dtypes,
        "selected_basin": selected_basin,
        "selected_dtype": selected_dtype,
        "last24": last24,
        "MAX_POINTS_INITIAL": MAX_POINTS_INITIAL,
        "MAX_RAW_POINTS": MAX_RAW_POINTS,
        "AGGREGATE_HOURLY_THRESHOLD": AGGREGATE_HOURLY_THRESHOLD,
    }
    return render(request, "monitoring/dashboard.html", context)


def timeseries_api(request):
    """
    Cached timeseries API.
    Query params: basin_id, data_type, start, end, resolution
    """
    basin_id = request.GET.get("basin_id")
    data_type = request.GET.get("data_type")
    if not basin_id or not data_type:
        return HttpResponseBadRequest(json.dumps({"ok": False, "error": "basin_id and data_type required"}), content_type="application/json")

    
    now = timezone.now()
    start_raw = request.GET.get("start")
    end_raw = request.GET.get("end")
    if not start_raw or not end_raw:
        end_dt = now
        start_dt = now - timedelta(hours=24)
        start_iso = "auto"
        end_iso = "auto"
    else:
        sp = parse_datetime_local(start_raw)
        ep = parse_datetime_local(end_raw)
        if not sp or not ep:
            end_dt = now
            start_dt = now - timedelta(hours=24)
            start_iso = "auto"
            end_iso = "auto"
        else:
            start_dt = timezone.make_aware(sp, timezone.get_current_timezone()) if timezone.is_naive(sp) else sp
            end_dt = timezone.make_aware(ep, timezone.get_current_timezone()) if timezone.is_naive(ep) else ep
            start_iso = start_dt.isoformat()
            end_iso = end_dt.isoformat()

    resolution = (request.GET.get("resolution") or "auto").lower()
    
    resolution_for_key = resolution

    
    cached = cache_utils.get_timeseries_cache(basin_id, data_type, start_iso, end_iso, resolution_for_key)
    if cached is not None:
        
        return JsonResponse(cached)

    base_qs = Observation.objects.filter(
        basin__basin_id=basin_id,
        data_type__name__iexact=data_type,
        datetime__gte=start_dt,
        datetime__lte=end_dt,
    )
    try:
        data_count = base_qs.count()
    except Exception:
        data_count = 0

    
    if resolution_for_key == "auto":
        if data_count > getattr(settings, "DASHBOARD_AGG_HOURLY_THRESHOLD", 2000):
            resolution_for_key = "hourly"
        else:
            resolution_for_key = "raw"

    
    points = []
    dtype_lower = data_type.strip().lower()
    use_sum = dtype_lower == "rainfall" or "rain" in dtype_lower

    if resolution_for_key == "raw":
        MAX_RAW = getattr(settings, "DASHBOARD_MAX_RAW_POINTS", 5000)
        if data_count > MAX_RAW:
            payload = {
                "ok": False,
                "error": "raw_too_large",
                "message": f"Raw data has {data_count} rows which is > {MAX_RAW}. Request hourly/daily or narrower range.",
                "data_count": data_count,
                "resolution": "raw",
            }
            
            return JsonResponse(payload, status=413)
        qs = base_qs.order_by("datetime").values_list("datetime", "value")
        for dt, val in qs:
            dt_iso = dt.isoformat() if hasattr(dt, "isoformat") else str(dt)
            points.append({"x": dt_iso, "y": float(val) if val is not None else None})
    else:
        
        if resolution_for_key == "hourly":
            trunc = TruncHour('datetime')
        else:
            trunc = TruncDay('datetime')
        if use_sum:
            agg_qs = base_qs.annotate(period=trunc).values('period').annotate(value=Sum('value')).order_by('period')
        else:
            agg_qs = base_qs.annotate(period=trunc).values('period').annotate(value=Avg('value')).order_by('period')
        for row in agg_qs:
            period = row.get('period')
            val = row.get('value')
            if not period:
                continue
            dt_iso = period.isoformat() if hasattr(period, "isoformat") else str(period)
            points.append({"x": dt_iso, "y": float(val) if val is not None else None})

    agg_summary = base_qs.aggregate(count=Count('pk'), sum=Sum('value'), avg=Avg('value'), min=Min('value'), max=Max('value'))
    def conv(v):
        if v is None:
            return None
        try:
            return float(v)
        except Exception:
            return str(v)
    summary = {
        "count": agg_summary.get('count') or 0,
        "sum": conv(agg_summary.get('sum')),
        "avg": conv(agg_summary.get('avg')),
        "min": conv(agg_summary.get('min')),
        "max": conv(agg_summary.get('max')),
    }

    payload = {
        "ok": True,
        "data_count": data_count,
        "resolution": resolution_for_key,
        "points": points,
        "summary": summary,
    }

    
    try:
        cache_utils.set_timeseries_cache(basin_id, data_type, start_iso, end_iso, resolution_for_key, payload)
    except Exception:
        logger.exception("Failed to set timeseries cache")

    return JsonResponse(payload)