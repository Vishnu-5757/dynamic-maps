# monitoring/views_dashboard.py
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

logger = logging.getLogger(__name__)

# Tunable settings (move to settings.py if you like)
MAX_POINTS_INITIAL = getattr(settings, "DASHBOARD_MAX_POINTS_INITIAL", 800)   # server-side "fast" points
MAX_RAW_POINTS = getattr(settings, "DASHBOARD_MAX_RAW_POINTS", 5000)         # raw rows allowed to return
AGGREGATE_HOURLY_THRESHOLD = getattr(settings, "DASHBOARD_AGG_HOURLY_THRESHOLD", 2000)  # switch to hourly when > this

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

    # defaults (first items if present)
    selected_basin = request.GET.get("basin_id") or (basins[0].basin_id if basins else "")
    selected_dtype = request.GET.get("data_type") or (dtypes[0].name if dtypes else "")
    last24 = request.GET.get("last24", "1") in ("1", "true", "True", "on")

    # For the template we only provide the UI; the actual timeseries and summary come from the API
    context = {
        "basins": basins,
        "dtypes": dtypes,
        "selected_basin": selected_basin,
        "selected_dtype": selected_dtype,
        "last24": last24,
        # expose some tuned defaults for client hints
        "MAX_POINTS_INITIAL": MAX_POINTS_INITIAL,
        "MAX_RAW_POINTS": MAX_RAW_POINTS,
        "AGGREGATE_HOURLY_THRESHOLD": AGGREGATE_HOURLY_THRESHOLD,
    }
    return render(request, "monitoring/dashboard.html", context)


def timeseries_api(request):
    """
    API endpoint that returns timeseries (and a summary) for a basin + data_type + datetime range.

    Query params:
    - basin_id (required)
    - data_type (required)
    - start (ISO or datetime-local optional)  -> if missing, server will use last 24h
    - end (optional)
    - resolution: 'auto'|'raw'|'hourly'|'daily' (default 'auto')
      - 'auto' picks raw if small else hourly
    Response JSON:
    {
      "ok": true,
      "data_count": <int>,
      "resolution": "hourly",
      "points": [{ "x": "<ISO datetime>", "y": <float|null> }, ...],
      "summary": { "count":.., "sum":.., "avg":.., "min":.., "max":.. }
    }
    """
    basin_id = request.GET.get("basin_id")
    data_type = request.GET.get("data_type")
    if not basin_id or not data_type:
        return HttpResponseBadRequest(json.dumps({"ok": False, "error": "basin_id and data_type required"}), content_type="application/json")

    # parse dates
    tz = timezone.get_current_timezone()
    now = timezone.now()
    start_raw = request.GET.get("start")
    end_raw = request.GET.get("end")
    if not start_raw or not end_raw:
        end_dt = now
        start_dt = now - timedelta(hours=24)
    else:
        sp = parse_datetime_local(start_raw)
        ep = parse_datetime_local(end_raw)
        if not sp or not ep:
            # fallback to last24 if parsing fails
            end_dt = now
            start_dt = now - timedelta(hours=24)
        else:
            start_dt = timezone.make_aware(sp, tz) if timezone.is_naive(sp) else sp
            end_dt = timezone.make_aware(ep, tz) if timezone.is_naive(ep) else ep

    # base queryset
    base_qs = Observation.objects.filter(
        basin__basin_id=basin_id,
        data_type__name__iexact=data_type,
        datetime__gte=start_dt,
        datetime__lte=end_dt,
    )

    # count rows (fast on indexed datetime/basin)
    try:
        data_count = base_qs.count()
    except Exception as e:
        logger.exception("Failed to count observations: %s", e)
        data_count = 0

    # choose resolution
    resolution = (request.GET.get("resolution") or "auto").lower()
    if resolution == "auto":
        if data_count > AGGREGATE_HOURLY_THRESHOLD:
            resolution = "hourly"
        else:
            resolution = "raw"

    points = []
    # choose aggregation function: for rainfall 'sum' makes sense; for temperature 'avg' better
    dtype_lower = data_type.strip().lower()
    use_sum = dtype_lower == "rainfall" or "rain" in dtype_lower

    # handle 'raw' (but protect huge payloads)
    if resolution == "raw":
        if data_count > MAX_RAW_POINTS:
            # too big to return raw — instruct client to choose hourly/daily
            return JsonResponse({
                "ok": False,
                "error": "raw_too_large",
                "message": f"Raw data has {data_count} rows which is > {MAX_RAW_POINTS}. Request hourly or daily aggregation or narrow the date range.",
                "data_count": data_count,
                "resolution": "raw",
            }, status=413)
        # return raw rows
        qs = base_qs.order_by("datetime").values_list("datetime", "value")
        for dt, val in qs:
            dt_iso = dt.isoformat() if hasattr(dt, "isoformat") else str(dt)
            y = float(val) if val is not None else None
            points.append({"x": dt_iso, "y": y})
    else:
        # aggregated (hourly or daily)
        if resolution == "hourly":
            trunc = TruncHour('datetime')
        elif resolution == "daily":
            trunc = TruncDay('datetime')
        else:
            # fallback to hourly
            trunc = TruncHour('datetime')

        # annotate and aggregate at DB level
        if use_sum:
            agg_qs = base_qs.annotate(period=trunc).values('period').annotate(value=Sum('value')).order_by('period')
        else:
            agg_qs = base_qs.annotate(period=trunc).values('period').annotate(value=Avg('value')).order_by('period')

        for row in agg_qs:
            period = row.get('period')
            val = row.get('value')
            if period is None:
                continue
            dt_iso = period.isoformat() if hasattr(period, "isoformat") else str(period)
            y = float(val) if val is not None else None
            points.append({"x": dt_iso, "y": y})

    # summary aggregates (on raw values) computed at DB
    # For rainfall we'll include sum; always return count,min,max,avg if available
    agg_summary = base_qs.aggregate(
        count=Count('pk'),
        sum=Sum('value'),
        avg=Avg('value'),
        min=Min('value'),
        max=Max('value'),
    )
    # convert Decimal -> float/string
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

    return JsonResponse({
        "ok": True,
        "data_count": data_count,
        "resolution": resolution,
        "points": points,
        "summary": summary,
    })
