from pathlib import Path
import sys
from urllib.error import HTTPError

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ceiling_marker_live_yaw as live  # noqa: E402


def _site(monkeypatch, *, refusal=None):
    challenge = {"robot_id": "rosy_45", "sources": ["ceiling_north"], "color": "blue",
                 "request_id": "led-1", "not_before": 101, "not_after": 106}
    calls = []
    frame_count = 0

    def request(_fleet, path, _token, _context, body=None, *, raw=False):
        nonlocal frame_count
        calls.append((path, body))
        if path == "/api/fleet/vision/lease":
            return {"frame_path": "/frame", "lease": "viewer"}
        if path == "/frame":
            assert raw
            stamp = 100 + frame_count
            frame_count += 1
            return b"jpeg", {"stamp": stamp, "X-Frame-Rotation-Deg": "0"}
        if path.endswith("/identify"):
            assert body == {"color": "blue"}
            assert frame_count >= 1
            if refusal is not None:
                raise HTTPError(path, refusal, "refused", {}, None)
            return challenge
        if path == "/api/fleet/tracking/identity":
            return {"pendings": [challenge]}
        raise AssertionError(path)

    record = {"map_id": "world", "source_id": "ceiling_north", "calibration_revision": "cal-1",
              "approved_by": "operator"}
    monkeypatch.setattr(live, "_request", request)
    monkeypatch.setattr(live, "_approved_record", lambda *a: record)
    monkeypatch.setattr(live, "check_candidate_source", lambda *a, **kw: (record, {}))
    monkeypatch.setattr(live, "live_frame_stamp", lambda headers, _record, **kw: headers["stamp"])
    monkeypatch.setattr(live, "FRAME_INTERVAL_S", 0.01)
    return challenge, calls


def _collect(**kwargs):
    return live.collect_live_candidate(
        "https://fleet", token="operator", context=None, source="ceiling_north", robot="rosy_45",
        marker=45, heading_edge=(0, 1), revision="cal-1", seconds=7, **kwargs,
    )


def test_live_candidate_collects_across_exact_challenge_window(monkeypatch):
    challenge, calls = _site(monkeypatch)

    def estimate(frames, _record, **kwargs):
        assert kwargs["challenge"] == challenge
        assert [stamp for stamp, _ in frames][:7] == list(range(100, 107))
        return {"candidate_offset_deg": -90, "evidence": "led"}

    monkeypatch.setattr(live, "estimate_led", estimate)
    candidate = _collect()
    assert candidate["candidate_offset_deg"] == -90
    assert candidate["map_id"] == "world"
    assert [p for p, _ in calls if p.endswith("/identify")] == ["/api/fleet/robots/rosy_45/identify"]


def test_explicit_identify_refusal_is_preserved_without_retry(monkeypatch):
    _challenge, calls = _site(monkeypatch, refusal=409)
    with pytest.raises(HTTPError) as exc:
        _collect()
    assert exc.value.code == 409
    assert sum(p.endswith("/identify") for p, _ in calls) == 1


@pytest.mark.parametrize("visible_led", [False, True])
def test_usable_cargo_only_falls_back_for_absent_led(monkeypatch, visible_led):
    _site(monkeypatch)
    monkeypatch.setattr(live, "cargo_frame_sample", lambda *a, **kw: "cargo sample")
    monkeypatch.setattr(live, "estimate_cargo", lambda *a, **kw: {"candidate_offset_deg": -90})

    def estimate(*_args, **_kwargs):
        if visible_led:
            return {"candidate_offset_deg": 90}
        raise live.LedUnobserved("no rear blink")

    monkeypatch.setattr(live, "estimate_led", estimate)
    if visible_led:
        with pytest.raises(live.EstimateError, match="disagree"):
            _collect(cargo_height_m=0.15)
    else:
        result = _collect(cargo_height_m=0.15)
        assert result["candidate_offset_deg"] == -90 and result["led_unavailable"] == "no rear blink"
