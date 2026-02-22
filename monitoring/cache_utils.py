# monitoring/cache_utils.py
from django.core.cache import cache
from django.conf import settings
from django_redis import get_redis_connection
import hashlib
import json
import logging

logger = logging.getLogger(__name__)

# TTL defaults
TS_TTL = getattr(settings, "CACHE_TIMESERIES_TTL", 300)
UP_TTL = getattr(settings, "CACHE_UPSTREAM_TTL", 300)

def _normalize_iso(s):
    
    if not s:
        return "auto"
    return s.replace(" ", "T").split(".")[0]

def timeseries_key(basin_id: str, data_type: str, start_iso: str, end_iso: str, resolution: str):
    """
    Key for timeseries responses.
    Include start/end/resolution to avoid stale collisions.
    Example:
      timeseries:2046:Rainfall:2026-02-21T05:00:00:2026-02-22T05:00:00:hourly
    """
    s = _normalize_iso(start_iso)
    e = _normalize_iso(end_iso)
    key = f"timeseries:{basin_id}:{data_type}:{resolution}:{s}:{e}"
    
    if len(key) > 200:
        h = hashlib.sha1(key.encode()).hexdigest()[:16]
        return f"timeseries:hash:{h}"
    return key

def upstream_key(basin_id: str, data_type: str, window: str, depth: int = 1):
    return f"upstream_agg:{basin_id}:{data_type}:{window}:d{int(depth)}"

# simple wrappers
def get_timeseries_cache(basin_id, data_type, start_iso, end_iso, resolution):
    return cache.get(timeseries_key(basin_id, data_type, start_iso, end_iso, resolution))

def set_timeseries_cache(basin_id, data_type, start_iso, end_iso, resolution, payload, ttl=None):
    key = timeseries_key(basin_id, data_type, start_iso, end_iso, resolution)
    cache.set(key, payload, ttl or TS_TTL)
    return key

def get_upstream_cache(basin_id, data_type, window, depth):
    return cache.get(upstream_key(basin_id, data_type, window, depth))

def set_upstream_cache(basin_id, data_type, window, depth, payload, ttl=None):
    key = upstream_key(basin_id, data_type, window, depth)
    cache.set(key, payload, ttl or UP_TTL)
    return key


def invalidate_timeseries_for_basin(basin_id: str, data_type: str):
    """
    Conservative invalidation: delete common windows and use SCAN to remove keys that match prefix.
    SCAN is used only if django-redis connection available.
    """
    prefixes = [
        f"timeseries:{basin_id}:{data_type}:",
        f"timeseries:{basin_id}:",  
    ]
    try:
        conn = get_redis_connection("default")
        
        for prefix in prefixes:
            cursor = 0
            pattern = f"{prefix}*"
            while True:
                cursor, keys = conn.scan(cursor=cursor, match=pattern, count=1000)
                if keys:
                    conn.delete(*keys)
                if cursor == 0:
                    break
    except Exception as e:
        
        logger.exception("Redis SCAN delete failed, trying targeted deletes (%s)", e)
        for win in ("24h", "48h", "168h"):
            try:
                cache.delete(timeseries_key(basin_id, data_type, win, "auto", "auto"))
            except Exception:
                pass

def invalidate_upstream_for_impacted_downstream(basin_internal_id, get_downstream_fn):
    """
    Invalidate upstream caches for basins that have 'basin_internal_id' as upstream.
    get_downstream_fn should return a list of affected downstream basin_ids (external basin_id strings).
    We keep this generic so ingest command can pass a function that queries BasinRelation.
    """
    try:
        downstream_list = get_downstream_fn(basin_internal_id) or []
        for dbid in downstream_list:
            
            for w in ("24h", "48h", "168h"):
                for dtype in ("Rainfall", "Temperature"):  
                    try:
                        cache.delete(upstream_key(dbid, dtype, w, 1))
                        cache.delete(upstream_key(dbid, dtype, w, 2))
                    except Exception:
                        pass
    except Exception:
        logger.exception("invalidate_upstream_for_impacted_downstream failed")
