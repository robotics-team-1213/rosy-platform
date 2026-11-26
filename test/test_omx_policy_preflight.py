"""A real ACT drive first runs the same episode as a one-chunk dry run, with no motion (2026-11-26 arm_b)."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/robot/omx"))
import cell_policy_drive as drive  # noqa: E402
import cell_policy_preflight as pre  # noqa: E402

CONDITIONS = {"installation_revision": "i", "object_revision": "o", "environment_revision": "e",
              "payload_max_kg": 0.08, "object_dimensions_m": [0.03, 0.03, 0.06]}
PAYLOAD = {"kg": 0.016, "source": "user-provided value", "object": "container-3"}


def test_missing_payload_refuses_before_any_inference(monkeypatch):
    calls = []
    monkeypatch.setattr(drive, "run_episode", lambda *a, **kw: calls.append(kw) or {"result": "dry_run"})
    out = pre.preflight(None, None, Path("lib.json"), Path("."), {"operating_conditions": CONDITIONS}, lambda _r: None, {})
    assert out["result"] == "refused" and "payload_unknown" in out["reason"] and calls == []


def test_dry_run_refusal_stops_the_drive_and_a_clean_dry_run_lets_it_start(monkeypatch):
    rows, config = [], {"operating_conditions": CONDITIONS, "payload": PAYLOAD}
    seen = []

    def dry(*_a, **kw):
        seen.append(kw)
        kw["log"]({"chunk": 0})
        return {"result": "refused", "at": 0, "reason": "policy window cannot play at the reviewed step rate"}

    monkeypatch.setattr(drive, "run_episode", dry)
    out = pre.preflight(None, None, Path("lib.json"), Path("."), config, rows.append, {"paced_chunks": False})
    assert out["result"] == "refused" and out["reason"] == "preflight: policy window cannot play at the reviewed step rate"
    assert seen[0]["dry_run"] is True and seen[0]["max_chunks"] == 1 and seen[0]["paced_chunks"] is False
    assert rows == [{"preflight": True, "chunk": 0}]
    monkeypatch.setattr(drive, "run_episode", lambda *a, **kw: {"result": "dry_run", "chunks": 1})
    assert pre.preflight(None, None, Path("lib.json"), Path("."), config, rows.append, {}) is None
    monkeypatch.setattr(drive, "run_episode", lambda *a, **kw: (_ for _ in ()).throw(ValueError("camera frame HTTP 503")))
    assert "camera frame HTTP 503" in pre.preflight(None, None, Path("lib.json"), Path("."), config, rows.append, {})["reason"]
