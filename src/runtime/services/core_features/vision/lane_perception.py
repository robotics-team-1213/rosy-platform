"""Latest keeper paint readback. Display evidence only, never a motion input."""
from __future__ import annotations

import json
import math
import threading

_SOURCES = frozenset({"threshold", "denoise", "learned", "denoise_fallback"})
_EMPTY = dict(applied_paint_source=None, applied_model_revision=None, applied_source_age_s=None)


def _finite(value) -> bool:
    return type(value) in (float, int) and math.isfinite(value)


class LanePerceptionStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._entry = None

    def clear(self) -> None:
        with self._lock:
            self._entry = None

    def accept(self, raw: str, *, now: float, source_now: float) -> bool:
        try:
            if not isinstance(raw, str) or len(raw) > 16384 or not _finite(now):
                raise ValueError("invalid packet")
            doc = json.loads(raw)
            if not isinstance(doc, dict) or doc.get("paint_source_used") not in _SOURCES:
                raise ValueError("unknown paint source")
            stamp = doc.get("stamp")
            if not _finite(stamp) or stamp < 0:
                raise ValueError("invalid camera stamp")
            if not _finite(source_now) or not 0 <= source_now - stamp <= 2.0:
                raise ValueError("camera image is stale or clock is invalid")
            requested = doc.get("paint_source_requested")
            if requested is not None and requested not in {"threshold", "denoise", "learned"}:
                raise ValueError("unknown requested source")
            revision = doc.get("paint_model_revision")
            if revision is not None and (not isinstance(revision, str) or not revision
                                         or revision.strip() != revision or len(revision) > 128):
                raise ValueError("invalid model revision")
            if doc["paint_source_used"] == "learned" and (requested != "learned" or revision is None):
                raise ValueError("learned source needs producer request and served-mask revision")
        except (ValueError, TypeError):
            self.clear()
            return False
        with self._lock:
            if self._entry is not None and (stamp <= self._entry["stamp"] or now < self._entry["at"]):
                self._entry = None  # reset/reordered camera clock must not preserve old evidence
                return False
            self._entry = dict(source=doc["paint_source_used"], requested=requested,
                               revision=revision, stamp=float(stamp), at=float(now))
        return True

    def snapshot(self, *, paint_source: str, model_revision: str | None = None, now: float) -> dict:
        with self._lock:
            entry = dict(self._entry) if self._entry is not None else None
        if entry is None or not _finite(now):
            return dict(_EMPTY)
        age = float(now) - entry["at"]
        compatible = {"threshold": {"threshold"}, "denoise": {"denoise"},
                      "learned": {"learned", "denoise_fallback"}}
        if (not 0 <= age <= 2.0 or entry["source"] not in compatible.get(paint_source, set())
                or entry["requested"] not in (None, paint_source)
                or (entry["source"] == "learned" and entry["revision"] is not None
                    and model_revision is not None and entry["revision"] != model_revision)):
            return dict(_EMPTY)
        return dict(applied_paint_source=entry["source"],
                    applied_model_revision=entry["revision"] if entry["source"] == "learned" else None,
                    applied_source_age_s=round(age, 3))
