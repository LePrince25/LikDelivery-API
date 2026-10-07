import threading
import time

from odoo.http import request

from .envelope import RATE_LIMITED, raise_error

# In-memory sliding window (per process). workers=0 in the dev stack; for
# multi-worker production this moves behind redis/ir.config_parameter sync.
_BUCKETS = {}
_LOCK = threading.Lock()

DEFAULT_LIMITS = {
    "auth": (100, 60),
    "orders": (30, 60),
    "rate": (10, 60),
}


def check_rate_limit(bucket, limit=None, window=None):
    default_limit, default_window = DEFAULT_LIMITS.get(bucket, (100, 60))
    limit = limit or default_limit
    window = window or default_window
    key = (bucket, request.httprequest.remote_addr)
    now = time.monotonic()
    with _LOCK:
        hits = [t for t in _BUCKETS.get(key, []) if now - t < window]
        if len(hits) >= limit:
            raise_error(RATE_LIMITED, "Trop de requetes, reessayez plus tard")
        hits.append(now)
        _BUCKETS[key] = hits
