import threading
import time
from typing import Any, Callable, Optional, Tuple


class ThrottleCache:
    def __init__(self, ttl_seconds: int = 120):
        self._lock = threading.Lock()
        self._data: Any = None
        self._error: Optional[str] = None
        self._fetched_at: float = 0
        self._ttl = ttl_seconds

    def get(self, fetch_fn: Callable) -> Tuple[Any, Optional[str]]:
        with self._lock:
            now = time.time()
            if self._fetched_at > 0 and (now - self._fetched_at) < self._ttl:
                return self._data, self._error

        try:
            data = fetch_fn()
            with self._lock:
                self._data = data
                self._error = None
                self._fetched_at = time.time()
            return data, None
        except Exception as e:
            err = str(e)
            with self._lock:
                self._error = err
                self._fetched_at = time.time()
            return None, err

    def invalidate(self):
        with self._lock:
            self._fetched_at = 0
