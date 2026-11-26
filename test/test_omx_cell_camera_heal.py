"""Camera jobs run the upkeep camera recovery before they start (2026-11-26 arm_b wrist UVC -71)."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy" / "robot" / "omx"))

import cell_camera_heal as heal  # noqa: E402
import cell_job_spec as spec  # noqa: E402,F401


def test_heal_uses_upkeep_recovery_and_respects_bus_owner(tmp_path, monkeypatch):
    import cell_upkeep_checks as checks

    cfg = tmp_path / "cell-b.json"
    cfg.write_text(json.dumps({"cameras": {"wrist": {"url": "http://127.0.0.1:8767/frame/arm_b_wrist.jpg"}}}))
    seen = []
    monkeypatch.setattr(checks, "check_cameras", lambda arm, cams, io, fix, bus_free: (
        seen.append((arm, list(cams), fix, bus_free)) or ([{"check": "cameras", "status": "fixed", "detail": "x"}], None)))
    owned = type("Io", (), {"sessions": lambda self: [], "lock_free": lambda self, arm: arm != "arm_b"})()
    rows = heal.heal([("arm_b", cfg), (None, cfg)], io=owned)
    assert seen == [("arm_b", ["wrist"], True, False), ("cell", ["wrist"], True, True)]
    assert [r["status"] for r in rows] == ["fixed", "fixed"] and rows[0]["arm"] == "arm_b"


def test_main_refuses_on_failed_recovery_and_execs_on_success(capsys):
    calls = []
    fail = lambda _t: [{"check": "cameras", "status": "fail", "detail": "wrist: still no frames"}]
    assert heal.main(["--target", "arm_b=c.json", "--", "job", "a"], heal_fn=fail, exec_fn=lambda *a: calls.append(a)) == 3
    assert "REFUSED: cameras not ready" in capsys.readouterr().out and calls == []
    ok = lambda targets: [{"check": "cameras", "status": "ok", "detail": "3 answer"}] if targets == [("arm_b", "c.json")] else []
    assert heal.main(["--target", "arm_b=c.json", "--", "job", "a"], heal_fn=ok, exec_fn=lambda *a: calls.append(a)) == 0
    assert calls == [("job", ["job", "a"])]
    assert heal.main(["--target", "arm_b=c.json"], heal_fn=ok, exec_fn=lambda *a: None) == 2


def test_with_camera_heal_wraps_only_camera_jobs():
    argv = ["./with-session-arm-b-par.sh", "bash", "-c", "x", "cell_policy_drive.py"]
    params = {"arm": "arm_b", "config": "cell-arm-b-d1073.json"}
    wrapped = heal.with_camera_heal(argv, spec.JOBS["cell_policy_drive"], params)
    assert wrapped[:2] == ["bash", "-c"] and wrapped[3] == heal.CAMERA_HEAL_SCRIPT
    assert Path(heal.CAMERA_HEAL_SCRIPT).is_file()
    assert wrapped[4:7] == ["--target", "arm_b=cell-arm-b-d1073.json", "--"] and wrapped[7:] == argv
    two = heal.with_camera_heal(argv, spec.JOBS["cell_two_arm_policy"], {"config_a": "a.json", "config_b": "b.json"})
    assert two[4:9] == ["--target", "arm_a=a.json", "--target", "arm_b=b.json", "--"]
    assert heal.with_camera_heal(argv, spec.JOBS["home"], params) is argv
    assert heal.with_camera_heal(argv, spec.JOBS["calibrate_check"], {"config": "c.json"})[4:6] == ["--target", "-=c.json"]


def test_seeded_dry_run_is_not_aged_by_an_idle_encoder_sample():
    import time

    import cell_policy_timing as timing

    class IdleCell:  # no arm session: the last encoder sample is hours old
        def policy_state(self):
            return {"ok": True, "state": [0.0] * 6, "t": time.time() - 3600}

    shadow = type("S", (), {"image_views": {}})()
    infer = lambda state, _images: ([list(state)] * 4, {})
    seeded = timing._observe(IdleCell(), shadow, infer, 0.5, None, None, time.monotonic, time.sleep, True,
                             seed_state=[1.0] * 6)
    assert seeded.observed > time.monotonic() - 1
    timing.action_window(seeded.frames, seeded.observed, time.monotonic(), 30, 4, 0.5)
    unseeded = timing._observe(IdleCell(), shadow, infer, 0.5, None, None, time.monotonic, time.sleep, True)
    with pytest.raises(ValueError, match="stale policy observation"):
        timing.action_window(unseeded.frames, unseeded.observed, time.monotonic(), 30, 4, 0.5)


def test_client_retries_only_the_session_lock_409():
    from cell_job_client import CellJobError, start_when_lock_free

    class Client:
        def __init__(self, errors):
            self.errors, self.calls = list(errors), 0

        def start(self, *_a, **_kw):
            self.calls += 1
            if self.errors:
                raise self.errors.pop(0)
            return {"id": "j"}

    t = [0.0]
    lock = CellJobError(409, "session lock for arm_b is held by another process")
    c = Client([lock, lock])
    assert start_when_lock_free(c, "home", {}, clock=lambda: t[0], sleep=lambda s: t.__setitem__(0, t[0] + s)) == {"id": "j"}
    assert c.calls == 3
    with pytest.raises(CellJobError):
        start_when_lock_free(Client([CellJobError(409, "A/B cell space is held by arm_a (home)")]), "home", {},
                             clock=lambda: 0.0, sleep=lambda _s: None)
    with pytest.raises(CellJobError):
        start_when_lock_free(Client([lock] * 99), "home", {}, wait_s=10, clock=lambda: t[0],
                             sleep=lambda s: t.__setitem__(0, t[0] + s))
