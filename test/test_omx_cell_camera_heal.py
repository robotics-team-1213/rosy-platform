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


class HubIo:
    def __init__(self, sessions=(), locked=(), frames=(500,)):
        self.sessions_, self.locked, self.frames, self.restarted = list(sessions), set(locked), list(frames), []

    def device(self, role):
        return f"/dev/v4l/by-id/rosy-{role}"

    def sessions(self):
        return self.sessions_

    def lock_free(self, arm):
        return arm not in self.locked

    def unit_restart(self, role):
        self.restarted.append(role)

    def labels(self):
        return {"arm_b_wrist": "/arm_b_wrist_camera/image_raw"}

    def roles(self):
        return {"/arm_b_wrist_camera/image_raw": "arm_b_wrist"}

    def fetch(self, _url):
        code = self.frames.pop(0) if len(self.frames) > 1 else self.frames[0]
        return code, (b"\xff\xd8" if code == 200 else b"")


def test_hub_cycle_only_when_no_arm_session_and_reports_failures():
    cycled = []
    find = lambda _dev: (Path("/sys/3-1.4"), 2, Path("/sys/3-1.4.2"))
    cycle = lambda up, port: cycled.append((up.name, port))
    busy = HubIo(sessions=["python record_session.py --arm arm_a"])
    assert "skipped" in heal.hub_cycle("arm_b_wrist", busy, find=find, cycle=cycle, sleep=lambda _s: None) and not cycled
    locked = HubIo(locked={"arm_s"})
    assert "skipped" in heal.hub_cycle("arm_b_wrist", locked, find=find, cycle=cycle, sleep=lambda _s: None) and not cycled
    idle = HubIo()
    note = heal.hub_cycle("arm_b_wrist", idle, find=find, cycle=cycle, sleep=lambda _s: None)
    assert cycled == [("3-1.4", 2)] and idle.restarted == ["arm_b_wrist"] and "power-cycled hub 3-1.4.2" in note

    def broken(_dev):
        raise OSError("no external hub port above the camera to cycle")
    assert "failed" in heal.hub_cycle("arm_b_wrist", HubIo(), find=broken, cycle=cycle, sleep=lambda _s: None)


def test_heal_escalates_to_hub_cycle_after_failed_leaf_recovery(tmp_path, monkeypatch):
    import cell_upkeep_checks as checks

    cfg = tmp_path / "cell-b.json"
    cfg.write_text(json.dumps({"cameras": {"wrist": {"url": "http://127.0.0.1:8767/frame/arm_b_wrist.jpg"}}}))
    passes = []

    def fake_check(arm, cams, io, fix, bus_free):
        passes.append(fix)
        status = "fail" if fix else "ok"
        return [{"check": "cameras", "status": status, "detail": "wrist"}], None

    monkeypatch.setattr(checks, "check_cameras", fake_check)
    monkeypatch.setattr(heal, "hub_cycle", lambda role, io: f"cycled {role}")
    rows = heal.heal([("arm_b", cfg)], io=HubIo(frames=[500]))
    assert passes == [True, False] and rows[0]["status"] == "ok" and rows[0]["escalation"] == ["cycled arm_b_wrist"]
    passes.clear()
    rows = heal.heal([("arm_b", cfg)], io=HubIo(locked={"arm_b"}, frames=[500]))
    assert passes == [True] and rows[0]["status"] == "fail" and "escalation" not in rows[0]


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


def _usb_tree(root, *chain, hubs=()):
    """Fake sysfs: nested USB devices; names in hubs get bDeviceClass 09."""
    path = root
    for name in chain:
        path = path / name
        path.mkdir()
        (path / "idVendor").write_text("0c45\n")
        (path / "bDeviceClass").write_text("09\n" if name in hubs else "ef\n")
    return path


def test_hub_port_found_through_the_unconfigured_leaf_when_by_id_is_gone(tmp_path):
    """UVC -71 'can't set config' removes the by-id link and video4linux; the hub is found from the leaf instead."""
    leaf = _usb_tree(tmp_path, "3-1", "3-1.4", "3-1.4.2", "3-1.4.2.1", hubs={"3-1", "3-1.4", "3-1.4.2"})
    gone = str(tmp_path / "dev/v4l/by-id/rosy-arm_b_wrist")
    asked = []
    finder = lambda role: asked.append(role) or {"leaf": str(leaf)}
    upstream, port, hub = heal.camera_hub_port(gone, "arm_b_wrist", leaf_finder=finder)
    assert (upstream.name, port, hub.name) == ("3-1.4", 2, "3-1.4.2") and asked == ["arm_b_wrist"]
    with pytest.raises(OSError, match="no unique unconfigured leaf"):
        heal.camera_hub_port(gone, "arm_b_wrist", leaf_finder=lambda _r: None)  # ambiguous or shared with another arm
    with pytest.raises(OSError, match="no unique unconfigured leaf"):
        heal.camera_hub_port(gone, None, leaf_finder=finder)


def test_hub_port_still_refuses_a_camera_on_a_root_port(tmp_path):
    leaf = _usb_tree(tmp_path, "3-1", "3-1.1", hubs={"3-1"})
    with pytest.raises(OSError, match="no external hub port"):
        heal.camera_hub_port(str(tmp_path / "gone"), "arm_b_wrist", leaf_finder=lambda _r: {"leaf": str(leaf)})
