"""core_features.diagnostics.collector — DIAG-001/002 + OBS-101 (P1-11).

순수 로직: provider 등록 → 1 Hz 수집 → HealthState 표준화.
시스템 provider(CPU/MEM/Disk)는 /proc 기반 — 외부 의존 없음.
"""

from __future__ import annotations

import shutil
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from core_common.protocol.schemas import HealthState

HealthProvider = Callable[[], HealthState]

_ORDER = {HealthState.OK: 0, HealthState.UNKNOWN: 1, HealthState.WARNING: 2, HealthState.ERROR: 3}


def worst(states: list[HealthState]) -> HealthState:
    best = HealthState.UNKNOWN
    for s in states:
        if _ORDER[s] > _ORDER[best]:
            best = s
    return best


class DiagnosticsCollector:
    def __init__(self) -> None:
        self._providers: dict[str, HealthProvider] = {}
        self._lock = threading.Lock()
        self._latest: dict[str, HealthState] = {}

    def register(self, name: str, provider: HealthProvider) -> None:
        self._providers[name] = provider

    def collect(self) -> dict[str, HealthState]:
        results: dict[str, HealthState] = {}
        for name, provider in self._providers.items():
            try:
                results[name] = HealthState(provider())
            except Exception:
                results[name] = HealthState.ERROR
        with self._lock:
            self._latest = results
        return results

    @property
    def latest(self) -> dict[str, HealthState]:
        with self._lock:
            return dict(self._latest)

    def summary_health(self) -> HealthState:
        return worst(list(self.latest.values()) or [HealthState.UNKNOWN])


class _ThresholdProvider:
    def __init__(self, warn, error, read: Callable[[], float], descending: bool) -> None:
        self._warn, self._error = warn, error
        self._read = read
        self._descending = descending

    def __call__(self) -> HealthState:
        try:
            value = self._read()
        except Exception:
            return HealthState.UNKNOWN
        if self._descending:
            if value <= self._error:
                return HealthState.ERROR
            if value <= self._warn:
                return HealthState.WARNING
        else:
            if value >= self._error:
                return HealthState.ERROR
            if value >= self._warn:
                return HealthState.WARNING
        return HealthState.OK


class CpuLoadProvider:
    """/proc/stat 두 표본 차분으로 CPU 사용률 산출 (collect 주기에 의존)."""

    def __init__(self, warn_percent: float = 80.0, error_percent: float = 95.0) -> None:
        self._impl = _ThresholdProvider(warn_percent, error_percent, self._usage, descending=False)
        self._last: Optional[tuple[float, float]] = None

    def _read_stat(self) -> tuple[float, float]:
        fields = Path("/proc/stat").read_text().splitlines()[0].split()[1:]
        values = [float(v) for v in fields]
        idle = values[3] + (values[4] if len(values) > 4 else 0.0)
        return sum(values), idle

    def _usage(self) -> float:
        total, idle = self._read_stat()
        if self._last is None:
            self._last = (total, idle)
            return 0.0
        dt = total - self._last[0]
        di = idle - self._last[1]
        self._last = (total, idle)
        if dt <= 0:
            return 0.0
        return (1.0 - di / dt) * 100.0

    def __call__(self) -> HealthState:
        return self._impl()


class MemoryAvailableProvider:
    def __init__(self, warn_percent: float = 80.0, error_percent: float = 92.0) -> None:
        self._impl = _ThresholdProvider(warn_percent, error_percent, self._used_percent, descending=False)

    @staticmethod
    def _used_percent() -> float:
        info = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            parts = line.split()
            if len(parts) >= 2:
                info[parts[0].rstrip(":")] = float(parts[1])
        total = info.get("MemTotal", 0.0)
        available = info.get("MemAvailable", info.get("MemFree", 0.0))
        if total <= 0:
            raise ValueError("meminfo unavailable")
        return (1.0 - available / total) * 100.0

    def __call__(self) -> HealthState:
        return self._impl()


def disk_provider(path: str = "/", warn_percent: float = 85.0, error_percent: float = 95.0) -> HealthProvider:
    def _used_percent() -> float:
        usage = shutil.disk_usage(path)
        return usage.used / usage.total * 100.0
    return _ThresholdProvider(warn_percent, error_percent, _used_percent, descending=False)


def topic_freshness_provider(last_seen_getter: Callable[[], float], stale_s: float = 2.0) -> HealthProvider:
    def _check() -> HealthState:
        last = last_seen_getter()
        if last <= 0.0:
            return HealthState.UNKNOWN
        return HealthState.OK if (time.monotonic() - last) < stale_s else HealthState.ERROR
    return _check
