"""One list of what the cell S automation did by itself, success or not (2026-11-19 panel; user: "성공하고 실패하고 이런게
나오면 rosy에서도 확인이 되어야겠지").

Rows come from the cell (cell-quality POST `auto_events`: auto_clear, auto_fold) and from Fleet itself (auto_depart from
depart_tick). Each row is small and flat; the list keeps the newest MAX_EVENTS, de-duplicated by (kind, arm/robot,
incident/batch, t), persisted with the pipeline ledger and shown by GET /api/fleet/pipeline/cell-tasks. A failure that
needs a person carries `person_needed: True`; the console turns only those into its one alert surface."""
from __future__ import annotations

import math

MAX_EVENTS = 100
KINDS = ("auto_clear", "auto_fold", "auto_depart", "auto_repark", "auto_observe", "recovery_escalation")
TEXT_MAX = 200
FIELDS = ("kind", "arm", "robot_id", "incident_id", "batch_id", "result", "why", "candidate", "t", "person_needed", "source")
NEEDS_PERSON = {("auto_clear", False), ("auto_fold", "held"), ("auto_fold", "not_cleared"), ("auto_fold", "failed"),
                ("auto_depart", "HELD"), ("auto_repark", "held"), ("auto_repark", "failed"),
                ("recovery_escalation", "escalated")}


def clean(row) -> dict | None:
    """A bounded copy of one event, or None when it is not one."""
    if not isinstance(row, dict) or row.get("kind") not in KINDS:
        return None
    out = {}
    for key in FIELDS:
        value = row.get(key)
        if isinstance(value, bool) or value is None:
            out[key] = value
        elif isinstance(value, (int, float)) and math.isfinite(value):
            out[key] = round(float(value), 3)
        elif isinstance(value, str):
            out[key] = value[:TEXT_MAX]
    if not isinstance(out.get("t"), float):
        return None
    result = out.get("result")
    out["person_needed"] = bool(out.get("person_needed")) or (out["kind"], result) in NEEDS_PERSON
    return out


def add(state, rows, source: str) -> int:
    """Merge rows into state.cell_auto_events (newest last); returns how many were new."""
    events = getattr(state, "cell_auto_events", None)
    if events is None:
        events = state.cell_auto_events = []
    seen = {(e.get("kind"), e.get("arm") or e.get("robot_id"), e.get("incident_id") or e.get("batch_id"), e.get("t"))
            for e in events}
    added = 0
    for row in rows if isinstance(rows, list) else []:
        event = clean(row)
        if event is None:
            continue
        if not event.get("source"):  # clean() keeps an absent source as None; the sender names it
            event["source"] = source
        key = (event["kind"], event.get("arm") or event.get("robot_id"), event.get("incident_id") or event.get("batch_id"),
               event["t"])
        if key in seen:
            continue
        seen.add(key)
        events.append(event)
        added += 1
    del events[:-MAX_EVENTS]
    return added
