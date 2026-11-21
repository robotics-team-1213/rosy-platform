"""Last sample per sensor key; a key may be lazy (built from a raw message on read)."""

from __future__ import annotations

import threading
from typing import Callable, Optional


class SensorStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._samples: dict[str, dict] = {}
        self._lazy: dict[str, Callable[[], Optional[dict]]] = {}

    def set(self, key: str, data: dict) -> None:
        with self._lock:
            self._samples[key] = data

    def set_lazy(self, key: str, provider: Callable[[], Optional[dict]]) -> None:
        """`provider` runs on the reader's thread, outside the lock, so a ROS callback only keeps a raw message."""
        self._lazy[key] = provider

    def get(self, key: str) -> Optional[dict]:
        with self._lock:
            data = self._samples.get(key)
        if not data and key in self._lazy:
            data = self._lazy[key]()
        return dict(data) if data else None

    def all(self) -> dict[str, dict]:
        with self._lock:
            keys = [*self._samples, *(k for k in self._lazy if k not in self._samples)]
        return {k: s for k in keys if (s := self.get(k))}
