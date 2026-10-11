"""D-407 §6 / D-379: mark where a lane stuck sits inside a harvested recording.

The on-robot recorder (control/recording.py) knows nothing of CORE events, and adding a
CORE -> sensing channel would be a new protocol surface. So the marker is made on the
tooling side at harvest: CORE's event history (``GET /api/v1/events``, viewer) carries
``nav.line_stuck_opened`` / ``nav.line_stuck_closed`` with a wall-clock UTC ``ts``; they are
paired by ``stuck_id`` and every session whose ``started_at``..``ended_at`` overlaps a stuck
(padded by ``PAD_S``) gets ``stuck_markers.json`` beside its ``session.json``. Frames are then
found by comparing the bag's ``log_ns`` (robot wall clock) with ``opened_at``/``closed_at``.

Limits: CORE keeps its event history in memory, so stucks from before a CORE restart (or
older than the history window) are not marked; a stuck still open at harvest has
``closed_at`` null.
"""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Optional

OPENED = "nav.line_stuck_opened"
CLOSED = "nav.line_stuck_closed"
SCHEMA = "rosy.recording.stuck_markers/1"
FILENAME = "stuck_markers.json"
PAD_S = 5.0                      # frames just before / after the stuck matter too
HISTORY_LIMIT = 1000


def _time(text) -> Optional[datetime]:
    if not isinstance(text, str) or not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def pair(events: Iterable[dict]) -> list[dict]:
    """Opened/closed events -> one marker per stuck_id, in opening order."""
    markers: dict[str, dict] = {}
    for event in events:
        kind, data = event.get("type"), event.get("data") or {}
        stuck_id = data.get("stuck_id")
        if not isinstance(stuck_id, str):
            continue
        if kind == OPENED:
            markers[stuck_id] = {"stuck_id": stuck_id, "cause": data.get("cause"),
                                 "restuck_of": data.get("restuck_of"),
                                 "opened_at": event.get("ts"), "closed_at": None,
                                 "close_reason": None, "attempts": data.get("attempts")}
        elif kind == CLOSED and stuck_id in markers:
            markers[stuck_id].update(closed_at=event.get("ts"), close_reason=data.get("reason"),
                                     attempts=data.get("attempts"))
    return list(markers.values())


def for_session(markers: Iterable[dict], started_at, ended_at,
                pad_s: float = PAD_S) -> list[dict]:
    """Markers whose padded [opened, closed] span overlaps the session's [started, ended]."""
    start, end = _time(started_at), _time(ended_at)
    if start is None or end is None:
        return []
    pad = timedelta(seconds=pad_s)
    hits = []
    for marker in markers:
        opened = _time(marker.get("opened_at"))
        if opened is None:
            continue
        closed = _time(marker.get("closed_at")) or end
        if opened - pad <= end and closed + pad >= start:
            hits.append(dict(marker))
    return hits


def write(session_dir, markers: list[dict], pad_s: float = PAD_S) -> Optional[Path]:
    """Write stuck_markers.json beside session.json; nothing when there is no stuck."""
    if not markers:
        return None
    path = Path(session_dir) / FILENAME
    path.write_text(json.dumps({"schema": SCHEMA, "pad_s": pad_s, "markers": markers},
                               indent=2), encoding="utf-8")
    return path


def fetch_events(core_url: str, token: str, timeout: float) -> list[dict]:
    """CORE's in-memory event history (viewer token), oldest first."""
    url = core_url.rstrip("/") + f"/api/v1/events?limit={HISTORY_LIMIT}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (operator URL)
        return list(json.loads(resp.read().decode("utf-8")).get("events") or [])
