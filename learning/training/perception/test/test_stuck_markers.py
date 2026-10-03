"""D-407 §6 / D-379: lane stucks are marked in the recordings that contain them."""
import json

import stuck_markers


def _event(kind, ts, **data):
    return {"type": kind, "ts": ts, "data": data}


EVENTS = [
    _event("nav.line_stuck_opened", "2026-10-02T05:00:10.000Z", stuck_id="stuck-a",
           cause="obstacle_ahead", restuck_of=None, attempts=0),
    _event("nav.line_obstacle_hold", "2026-10-02T05:00:10.000Z"),
    _event("nav.line_stuck_closed", "2026-10-02T05:00:30.500Z", stuck_id="stuck-a",
           reason="recovered", attempts=1),
    _event("nav.line_stuck_opened", "2026-10-02T05:10:00.000Z", stuck_id="stuck-b",
           cause="lane_lost", restuck_of=None, attempts=0),
]


def test_pairs_opened_and_closed_by_stuck_id():
    markers = stuck_markers.pair(EVENTS)
    assert [m["stuck_id"] for m in markers] == ["stuck-a", "stuck-b"]
    a, b = markers
    assert (a["cause"], a["opened_at"], a["closed_at"], a["close_reason"], a["attempts"]) == (
        "obstacle_ahead", "2026-10-02T05:00:10.000Z", "2026-10-02T05:00:30.500Z", "recovered", 1)
    assert b["closed_at"] is None                       # still open at harvest


def test_only_sessions_overlapping_the_padded_stuck_get_it():
    markers = stuck_markers.pair(EVENTS)
    inside = stuck_markers.for_session(markers, "2026-10-02T04:59:00Z", "2026-10-02T05:01:00Z")
    assert [m["stuck_id"] for m in inside] == ["stuck-a"]
    edge = stuck_markers.for_session(markers, "2026-10-02T05:00:33Z", "2026-10-02T05:02:00Z")
    assert [m["stuck_id"] for m in edge] == ["stuck-a"]          # within the 5 s pad
    later = stuck_markers.for_session(markers, "2026-10-02T05:00:40Z", "2026-10-02T05:05:00Z")
    assert later == []
    open_ended = stuck_markers.for_session(markers, "2026-10-02T05:09:00Z", "2026-10-02T05:12:00Z")
    assert [m["stuck_id"] for m in open_ended] == ["stuck-b"]
    assert stuck_markers.for_session(markers, None, "2026-10-02T05:12:00Z") == []


def test_write_puts_markers_beside_session_json(tmp_path):
    assert stuck_markers.write(tmp_path, []) is None
    path = stuck_markers.write(tmp_path, stuck_markers.pair(EVENTS)[:1])
    data = json.loads(path.read_text(encoding="utf-8"))
    assert path.name == "stuck_markers.json" and data["schema"] == "rosy.recording.stuck_markers/1"
    assert data["markers"][0]["stuck_id"] == "stuck-a" and data["pad_s"] == 5.0
