"""In-process sliding-window rate limiter for expensive per-user actions.

Single-worker deployments (uvicorn --workers 1) share one process, so an
in-memory window is an effective cost guard. On multi-worker deployments each
worker keeps its own window (still better than nothing — deployment should add
a reverse-proxy limit for hard guarantees).
"""

import threading
import time
from collections import defaultdict, deque

_lock = threading.Lock()
_history: dict[str, deque[float]] = defaultdict(deque)
_cleanup_at = time.monotonic() + 300


def check_rate_limit(key: str, limit: int, window_seconds: int = 60) -> bool:
    """Return True when the key is within its limit; False when throttled."""
    if limit <= 0:
        return True
    now = time.monotonic()
    global _cleanup_at
    with _lock:
        # Periodic memory cleanup for idle keys.
        if now >= _cleanup_at:
            cutoff_global = now - max(window_seconds * 2, 3600)
            dead = [k for k, dq in _history.items() if not dq or dq[0] < cutoff_global]
            for k in dead:
                del _history[k]
            _cleanup_at = now + 300

        dq = _history[key]
        cutoff = now - window_seconds
        while dq and dq[0] < cutoff:
            dq.popleft()
        if len(dq) >= limit:
            return False
        dq.append(now)
        return True
