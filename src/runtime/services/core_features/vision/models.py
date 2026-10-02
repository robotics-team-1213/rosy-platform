"""Learned-model status per task, as the robot's model nodes report it (D-423 §3.6).

Read-only display data for Pilot: which model revision each task's node runs, its
last error, and how fresh the report is. Nothing here selects, loads or promotes a
model (promote/rollback stay on the operator CLI, rosy_ml), and nothing in the
driving path reads it.

CORE cannot read the pointer files under /var/lib/rosy/models (root:rosy-camera
0750), so a slot the robot runs no node for (object_det shadow, lane_seg active)
is simply absent rather than guessed."""

from __future__ import annotations

import json
import math
import threading

STATUS_SCHEMA = "rosy.perception.learned_status/1"
#: topic -> (task, slot the node on that topic runs)
MODEL_STATUS_TOPICS = {
    "perception/learned/status": ("lane_seg", "shadow"),
    "perception/learned/object_det/status": ("object_det", "active"),
}
MAX_TEXT = 200
MAX_PAYLOAD = 4096


def _int(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _number(value):
    ok = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    return float(value) if ok and value >= 0 else None


class ModelStatusStore:
    def __init__(self, *, stale_after_s: float = 5.0) -> None:
        if not math.isfinite(float(stale_after_s)) or float(stale_after_s) <= 0:
            raise ValueError("stale_after_s must be positive and finite")
        self._stale_after_s = float(stale_after_s)
        self._lock = threading.Lock()
        self._tasks: dict[str, dict] = {}

    def accept(self, topic: str, raw: str, *, now: float) -> bool:
        """Store one status message; False (and nothing stored) when it is not one."""
        if topic not in MODEL_STATUS_TOPICS or not isinstance(raw, str) or len(raw) > MAX_PAYLOAD:
            return False
        try:
            doc = json.loads(raw)
        except ValueError:
            return False
        if not isinstance(doc, dict) or doc.get("schema") != STATUS_SCHEMA:
            return False
        revision, error = doc.get("model_revision"), doc.get("last_error")
        if not (revision is None or isinstance(revision, str)) or not (error is None or isinstance(error, str)):
            return False
        task, slot = MODEL_STATUS_TOPICS[topic]
        entry = {"task": task, "slot": slot,
                 "model_revision": revision[:MAX_TEXT] if revision else None,
                 "last_error": error[:MAX_TEXT] if error else None,
                 "frames_inferred": _int(doc.get("frames_inferred")),
                 "latency_ms_p50": _number(doc.get("latency_ms_p50")), "_at": float(now)}
        with self._lock:
            self._tasks[task] = entry
        return True

    def snapshot(self, *, now: float) -> dict:
        with self._lock:
            entries = [dict(e) for e in self._tasks.values()]
        tasks = []
        for entry in sorted(entries, key=lambda e: e["task"]):
            age = max(0.0, float(now) - entry.pop("_at"))
            tasks.append({**entry, "age_s": round(age, 3), "stale": age > self._stale_after_s})
        return {"tasks": tasks}
