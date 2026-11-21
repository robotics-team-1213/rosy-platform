from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy" / "robot" / "omx"))


def test_site_finger_params_override_global_params_for_finger_room(monkeypatch):
    import cell_auto_pick_plan as cap

    seen = []
    monkeypatch.setattr(cap, "predicted_pixel", lambda *a: (100, 100))
    monkeypatch.setattr(cap, "past_pan_limit", lambda *a: None)
    monkeypatch.setattr(cap, "past_park_reach", lambda *a: None)
    monkeypatch.setattr(
        cap,
        "finger_room",
        lambda _m, _r, _pf, _o, _e, params, **_kw: seen.append(params) or {"margin_mm": None, "free_mm": [24.0, 6.0]},
    )
    monkeypatch.setattr(cap, "reachable_ends", lambda *a: [])
    cfg = {
        "params": {"auto.finger_mm": 12.0, "auto.min_jaw_margin_mm": 1.0, "auto.neighbour_clear_mm": 0.0},
        "sites": {
            "pinky": {
                "start": [0.1, 0.14],
                "finger_params": {"auto.finger_mm": 0.0, "auto.min_jaw_margin_mm": 0.5, "evidence": "ignored"},
            }
        },
    }
    objs = [{"raw_m": [0.1, 0.14], "matched": True, "object": "c2", "long_axis_deg": 0.0, "centre_mm": [100, 140]}]
    cat = [{"id": "c2", "length_mm": 60, "width_mm": 30}]
    cap.choose(None, cfg, {}, "pinky", "belt", [0.1, -0.05], [0, 0, 300, 300], objs, None, cat, {}, [], None, set(), None)
    assert len(seen) == 1
    assert seen[0]["auto.finger_mm"] == 0.0 and seen[0]["auto.min_jaw_margin_mm"] == 0.5
    assert "evidence" not in seen[0]
