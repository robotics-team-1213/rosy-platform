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


def test_recovery_jobs_are_never_held_back_by_the_camera_preflight():
    """recover_hold folds an arm still holding under torque and safe_home brings an incident arm home: a dead
    camera (or a hub cycle the live session would skip) must not refuse them; the job itself decides, as before."""
    argv = ["bash", "-c", "x", "cell_auto_fold.py"]
    params = {"arm": "arm_b", "config": "cell-arm-b.json"}
    recovery = [name for name, job in spec.JOBS.items() if job.get("camera") and (job.get("attach_live_hold") or job.get("recovery_home"))]
    assert {"recover_hold", "safe_home"} <= set(recovery)
    for name in recovery:
        assert heal.with_camera_heal(argv, spec.JOBS[name], params) is argv, name


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


class _FakeLock:
    def close(self):
        pass


def test_hub_cycle_only_when_no_arm_session_and_reports_failures():
    cycled = []
    find = lambda _dev: (Path("/sys/3-1.4"), 2, Path("/sys/3-1.4.2"))
    cycle = lambda up, port: cycled.append((up.name, port))
    busy = HubIo(sessions=["python record_session.py --arm arm_a"])
    assert "skipped" in heal.hub_cycle("arm_b_wrist", busy, find=find, cycle=cycle, sleep=lambda _s: None, cell_lock=_FakeLock, at_rest=lambda _r: None) and not cycled
    locked = HubIo(locked={"arm_s"})
    assert "skipped" in heal.hub_cycle("arm_b_wrist", locked, find=find, cycle=cycle, sleep=lambda _s: None, cell_lock=_FakeLock, at_rest=lambda _r: None) and not cycled
    idle = HubIo()
    note = heal.hub_cycle("arm_b_wrist", idle, find=find, cycle=cycle, sleep=lambda _s: None, cell_lock=_FakeLock, at_rest=lambda _r: None)
    assert cycled == [("3-1.4", 2)] and idle.restarted == ["arm_b_wrist"] and "power-cycled hub 3-1.4.2" in note

    def broken(_dev):
        raise OSError("no external hub port above the camera to cycle")
    assert "failed" in heal.hub_cycle("arm_b_wrist", HubIo(), find=broken, cycle=cycle, sleep=lambda _s: None, cell_lock=_FakeLock, at_rest=lambda _r: None)


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
    monkeypatch.setattr(heal, "hub_cycle", lambda role, io, **_kw: f"cycled {role}")
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
    assert start_when_lock_free(c, "home", {}, wait_s=180, clock=lambda: t[0], sleep=lambda s: t.__setitem__(0, t[0] + s)) == {"id": "j"}
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


def test_hub_cycle_holds_the_whole_cell_lock_exclusively_until_the_camera_is_back(tmp_path, monkeypatch):
    """A session that starts after the idle check (it holds session.lock shared) stops the cycle; during the cycle
    nothing can take the cell lock, and it is free again before the job's own session wrapper runs."""
    import fcntl

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("ROSY_OMX_HOME", str(tmp_path / "rosy-omx"))
    (tmp_path / "rosy-omx").mkdir()
    lock = tmp_path / "rosy-omx" / "session.lock"
    find = lambda _dev: (Path("/sys/3-1.4"), 2, Path("/sys/3-1.4.2"))

    def try_shared():
        with lock.open("a") as fh:
            try:
                fcntl.flock(fh, fcntl.LOCK_SH | fcntl.LOCK_NB)
                return True
            except BlockingIOError:
                return False

    seen, cycled = [], []
    io = HubIo()
    io.unit_restart = lambda role: (seen.append(("restart", try_shared())), io.restarted.append(role))
    note = heal.hub_cycle("arm_b_wrist", io, find=find, cycle=lambda up, port: (cycled.append(port), seen.append(("cycle", try_shared()))),
                          sleep=lambda _s: None, at_rest=lambda _r: None)
    assert "power-cycled" in note and seen == [("cycle", False), ("restart", False)]
    assert try_shared()  # released before exec into the job

    with lock.open("a") as session:  # an arm session started between the idle check and the cycle
        fcntl.flock(session, fcntl.LOCK_SH | fcntl.LOCK_NB)
        cycled.clear()
        note = heal.hub_cycle("arm_b_wrist", HubIo(), find=find, cycle=lambda up, port: cycled.append(port), sleep=lambda _s: None, at_rest=lambda _r: None)
    assert "skipped" in note and "session.lock" in note and not cycled


def _dev(parent, name, vendor="0c45", product="6367", serial=None, hub=False):
    path = parent / name
    path.mkdir()
    (path / "idVendor").write_text(vendor + "\n")
    (path / "idProduct").write_text(product + "\n")
    (path / "bDeviceClass").write_text("09\n" if hub else "ef\n")
    (path / f"{name}:1.0").mkdir()  # an interface directory, not a device
    if serial:
        (path / "serial").write_text(serial + "\n")
    return path


def test_hub_cycle_refuses_a_hub_that_also_feeds_anything_but_this_arms_openrb(tmp_path):
    """The 2026-11-26 arm_b wrist hub held the camera and arm_b's OpenRB: that may be cycled. Another arm's board,
    an unregistered board, a second camera or a device behind a nested hub may not."""
    boards = tmp_path / "omx-arm-boards.json"
    boards.write_text(json.dumps({"RB-B": "arm_b", "RB-A": "arm_a"}))
    leaf = _usb_tree(tmp_path, "3-1", "3-1.4", "3-1.4.2", "3-1.4.2.1", hubs={"3-1", "3-1.4", "3-1.4.2"})
    hub = leaf.parent
    find = lambda _r: {"leaf": str(leaf)}
    port = lambda role="arm_b_wrist", path=boards: heal.camera_hub_port(str(tmp_path / "gone"), role, leaf_finder=find, boards_path=path)
    _dev(hub, "3-1.4.2.3", vendor="2f5d", product="2202", serial="RB-B")
    assert port()[1] == 2  # camera + its own arm's OpenRB
    with pytest.raises(OSError, match="OpenRB of arm_b, not arm_a"):
        port(role="arm_a_wrist")
    with pytest.raises(OSError, match="unreadable"):
        port(path=tmp_path / "missing.json")
    cases = [("3-1.4.2.4", {"vendor": "2f5d", "serial": "RB-A"}, "OpenRB of arm_a"),
             ("3-1.4.2.4", {"vendor": "2f5d", "serial": "RB-X"}, "unknown arm"),
             ("3-1.4.2.4", {"vendor": "8086", "product": "0b07"}, "would also lose power")]  # a D435
    for name, kw, text in cases:
        extra = _dev(hub, name, **kw)
        with pytest.raises(OSError, match=text):
            port()
        import shutil
        shutil.rmtree(extra)
    nested = _dev(hub, "3-1.4.2.2", vendor="05e3", product="0610", hub=True)
    _dev(nested, "3-1.4.2.2.1", vendor="0403", product="6014", serial="U2D2")  # behind a second hub
    with pytest.raises(OSError, match="3-1.4.2.2.1 .*would also lose power"):
        port()


def test_a_409_is_not_retried_unless_asked_for():
    from cell_job_client import CellJobError, start_when_lock_free

    class Busy:
        calls = 0

        def start(self, *_a, **_kw):
            self.calls += 1
            raise CellJobError(409, "session lock for arm_b is held by another process")

    busy = Busy()
    with pytest.raises(CellJobError):
        start_when_lock_free(busy, "home", {}, sleep=lambda _s: pytest.fail("must not wait"))
    assert busy.calls == 1


def test_hub_cycle_needs_the_arm_folded_with_torque_off_before_it_takes_the_lock():
    block = {"torque_after": {"11": 0, "12": 0}, "folded": True, "stable": True, "max_home_err": 0.4}
    seen = lambda b: (lambda arm, config, **kw: seen_kw.append(kw) or b)
    seen_kw = []
    assert heal.arm_at_rest("arm_b_wrist", {"arm_b": "b.json"}, reassess=seen(block)) is None
    assert seen_kw == [{"held": False, "with_frames": False}]  # no camera view: this camera is the dead one
    assert "torque ON" in heal.arm_at_rest("arm_b_wrist", {"arm_b": "b.json"}, reassess=seen({**block, "torque_after": {"11": 1}}))
    assert "not folded" in heal.arm_at_rest("arm_b_wrist", {"arm_b": "b.json"}, reassess=seen({**block, "folded": False}))
    assert "not folded" in heal.arm_at_rest("arm_b_wrist", {"arm_b": "b.json"}, reassess=seen({**block, "stable": False}))
    assert "no cell config" in heal.arm_at_rest("arm_b_wrist", {"arm_a": "a.json"}, reassess=seen(block))

    def lease_held(*_a, **_k):
        raise SystemExit("arm_b: lease held by someone; not read")
    assert "lease held" in heal.arm_at_rest("arm_b_wrist", {"arm_b": "b.json"}, reassess=lease_held)
    assert heal.arm_at_rest("top", {}) is None  # no arm board shares that camera's hub
    cycled = []
    note = heal.hub_cycle("arm_b_wrist", HubIo(), find=lambda _d: (Path("/sys/3-1.4"), 2, Path("/sys/3-1.4.2")),
                          cycle=lambda *a: cycled.append(a), cell_lock=lambda: pytest.fail("lock taken before the arm check"),
                          at_rest=lambda _r: "arm_b has a motor with torque ON")
    assert "refused" in note and "torque ON" in note and not cycled
    assert "refused" in heal.hub_cycle("arm_b_wrist", HubIo(), find=lambda _d: (Path("/sys/3-1.4"), 2, Path("/sys/3-1.4.2")),
                                       cycle=lambda *a: cycled.append(a), cell_lock=_FakeLock) and not cycled  # no check given: fail closed


def test_heal_budget_and_a_crash_still_leave_a_refusal(tmp_path, capsys):
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps({"cameras": {}}))
    clock = iter([0.0, 10.0, 10.0])
    rows = heal.heal([("arm_b", cfg), ("arm_a", cfg)], io=HubIo(), budget_s=5, clock=lambda: next(clock))
    assert [r["status"] for r in rows] == ["fail", "fail"] and "budget" in rows[0]["detail"]

    def boom(_t):
        raise RuntimeError("sysfs vanished")
    assert heal.main(["--target", "arm_b=c.json", "--", "job"], heal_fn=boom, exec_fn=lambda *a: pytest.fail("exec")) == 3
    out = capsys.readouterr().out
    assert '"camera_preflight"' in out and "sysfs vanished" in out and "REFUSED" in out


def _helper():
    import importlib.machinery
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "deploy" / "robot" / "omx" / "rosy-omx-hub-cycle"
    spec_ = importlib.util.spec_from_loader("hub_cycle_helper", importlib.machinery.SourceFileLoader("hub_cycle_helper", str(path)))
    mod = importlib.util.module_from_spec(spec_)
    spec_.loader.exec_module(mod)
    return mod


def test_root_helper_validates_its_arguments_and_cycles_through_usbfs(tmp_path):
    helper = _helper()
    sysfs, usbfs = tmp_path / "devices", tmp_path / "usb"
    hub = sysfs / "3-1.4"
    hub.mkdir(parents=True)
    for name, value in {"bDeviceClass": "09", "maxchild": "4", "busnum": "3", "devnum": "7"}.items():
        (hub / name).write_text(value + "\n")
    (sysfs / "3-1.5").mkdir()
    (sysfs / "3-1.5" / "bDeviceClass").write_text("ef\n")
    (usbfs / "003").mkdir(parents=True)
    (usbfs / "003" / "007").write_bytes(b"")
    assert helper.validate("3-1.4", "2", sysfs) == (hub, 2)
    for hub_name, port in [("../../etc", "2"), ("3-1.4/x", "2"), ("3-1.4;id", "2"), ("3-1.4", "0"), ("3-1.4", "5"),
                           ("3-1.4", "-1"), ("3-1.4", "2 3"), ("3-1.5", "1"), ("3-9", "1"), ("", "1")]:
        with pytest.raises(ValueError, match="refused"):
            helper.validate(hub_name, port, sysfs)
    sent = []
    helper.cycle(hub, 2, ioctl=lambda fd, req, ctrl: sent.append((ctrl.bRequestType, ctrl.bRequest, ctrl.wValue, ctrl.wIndex)),
                 sleep=lambda _s: None, usbfs=usbfs)
    assert sent == [(0xA3, 0, 0, 2), (0x23, 1, 8, 2), (0x23, 3, 8, 2), (0xA3, 0, 0, 2)]  # status, power off, power on, status
    assert helper.main(["only-one"]) == 2

    sent.clear()

    def dies_on_power_on(fd, req, ctrl):
        sent.append((ctrl.bRequestType, ctrl.bRequest))
        if (ctrl.bRequestType, ctrl.bRequest) == (0x23, 3):
            raise OSError("usbfs went away")
    with pytest.raises(OSError):
        helper.cycle(hub, 2, ioctl=dies_on_power_on, sleep=lambda _s: None, usbfs=usbfs)
    assert (0x23, 3) in sent  # power-on was attempted after the power-off
    sent.clear()

    def dies_while_off(fd, req, ctrl):
        sent.append((ctrl.bRequestType, ctrl.bRequest))
    with pytest.raises(KeyboardInterrupt):
        helper.cycle(hub, 2, ioctl=dies_while_off, sleep=lambda _s: (_ for _ in ()).throw(KeyboardInterrupt()), usbfs=usbfs)
    assert sent[-1] == (0x23, 3)  # interrupted during the off window: the port is still switched back on


def test_installer_writes_one_sudoers_line_naming_only_the_helper():
    import shutil
    import subprocess

    bash = shutil.which("bash")
    if not bash:
        pytest.skip("no bash on this host")
    script = Path(__file__).resolve().parents[1] / "deploy" / "robot" / "omx" / "install-hub-cycle.sh"
    done = subprocess.run([bash, str(script), "--user", "rosy", "--dry-run"], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    assert "rosy ALL=(root) NOPASSWD: /usr/local/sbin/rosy-omx-hub-cycle" in done.stdout
    assert "ALL=(root) NOPASSWD: ALL" not in done.stdout
    bad = subprocess.run([bash, str(script), "--user", "x; rm -rf /", "--dry-run"], capture_output=True, text=True, timeout=30)
    assert bad.returncode == 2
