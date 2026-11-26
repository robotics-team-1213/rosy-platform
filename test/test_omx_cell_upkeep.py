"""cell_upkeep with fakes for each failure of 2026-11-03/04: a missing board, caps at 885, a 503 camera, a closed
value below the jaws' stop, a missing map, a hold. No hardware, no motion."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "deploy/robot/omx"))
import cell_upkeep as cu  # noqa: E402

JPEG = b"\xff\xd8\xff\xe0frame"
DEV = "usb-ROBOTIS_OpenRB-150_FF06202D-if00-port0"


class Frame:
    def __init__(self, mean):
        self.value = mean

    def mean(self):
        return self.value


class Bus:
    def __init__(self, caps=(20, 50), torque=0, error=0):
        self.rows = [self.motor(i, *caps, torque, error) for i in range(11, 17)]
        self.fixed = 0

    @staticmethod
    def motor(i, pwm, cur, torque, error):
        return {"id": i, "torque_enabled": torque if i == 11 else 0, "hardware_error": error if i == 11 else 0,
                "pwm_limit_raw": pwm, "current_limit_raw": cur if i >= 14 else None}

    def read(self, device):
        return self.rows

    def fix(self, device, out):
        self.fixed += 1
        self.rows = [self.motor(r["id"], 20, 50, r["torque_enabled"], r["hardware_error"]) for r in self.rows]
        return True


def make_io(bus=None, urls=None, mean=100.0, sessions=(), locked=False, todo=()):
    bus = bus or Bus()
    urls = urls or {}
    return cu.Io(fetch=lambda url: urls.get(url, (200, JPEG)), decode=lambda body, gray=False: Frame(mean),
                 bus_read=bus.read, bus_fix=bus.fix, sessions=lambda: list(sessions), lock_free=lambda arm: not locked,
                 calibrate=lambda c, cal, f, p: {"check": {"missing_map": list(todo)}, "todo": list(todo)},
                 replays=lambda h, t, p: ({}, {}), labels=lambda: {}, roles=lambda: {}, unit_tail=lambda r: "",
                 unit_restart=lambda r: None), bus


def arms_setup(tmp, closed=49.0, boards=True, tcp=0.074):
    port, leader = tmp / DEV, tmp / "leader"
    if boards:
        port.write_text("")
        leader.write_text("")
    (tmp / "cell.json").write_text(json.dumps({
        "calibration_path": str(tmp / "cal.json"),
        **({"tcp_x_m": tcp, "tcp_x_m_evidence": "box-top touch"} if tcp else {}),
        "cameras": {"top": {"url": "http://v/top.jpg"}, "wrist": {"url": "http://v/wrist.jpg"}}}))
    (tmp / "record.json").write_text(json.dumps({"robot": {"port": str(port)}, "teleop": {"port": str(leader)}}))
    (tmp / "chunks.json").write_text(json.dumps({"gripper_closed": closed}))
    return {"arm_a": {"cell": "cell.json", "record": "record.json", "chunks": "chunks.json", "_base": str(tmp)}}


def report(tmp, arms=None, fix=False, **kw):
    io, bus = make_io(**kw)
    out = cu.run(arms or arms_setup(tmp), fix, io=io, out_dir=tmp / "upkeep", incidents=tmp / "incidents", stamp="S")
    return out["arm_a"], {c["check"]: c for c in out["arm_a"]["checks"]}, bus


def test_a_healthy_arm_is_ready_and_the_report_is_written(tmp_path):
    rep, checks, _ = report(tmp_path)
    assert rep["verdict"] == "ready" and all(c["status"] == "ok" for c in rep["checks"])
    assert json.loads((tmp_path / "upkeep/S-arm_a.json").read_text())["verdict"] == "ready"
    assert "0.074" in checks["tcp"]["detail"]


def test_an_unmeasured_jaw_tcp_keeps_the_arm_from_ready(tmp_path):
    """arm_b's stock TCP put its tips 18 mm above every planned height until the box-top touch (2026-11-03)."""
    rep, checks, _ = report(tmp_path, arms=arms_setup(tmp_path, tcp=None))
    assert checks["tcp"]["status"] == "warn" and "unmeasured" in checks["tcp"]["detail"] and rep["verdict"] == "needs_person"


def test_a_missing_board_fails_and_skips_the_register_read(tmp_path):
    rep, checks, _ = report(tmp_path, arms_setup(tmp_path, boards=False))
    assert checks["boards"]["status"] == "fail" and "robot.port" in checks["boards"]["detail"]
    assert checks["registers"]["status"] == "skipped" and rep["verdict"] == "needs_person"


def test_caps_at_885_are_fixed_only_when_every_torque_is_off(tmp_path):
    rep, checks, bus = report(tmp_path, fix=True, bus=Bus(caps=(885, 1750)))
    assert checks["registers"]["status"] == "fixed" and bus.fixed == 1 and rep["verdict"] == "ready"
    _, checks, bus = report(tmp_path, bus=Bus(caps=(885, 1750)))  # no --fix: reported
    assert checks["registers"]["status"] == "fail" and bus.fixed == 0
    _, checks, bus = report(tmp_path, fix=True, bus=Bus(caps=(885, 1750), torque=1))
    assert checks["registers"]["status"] == "fail" and bus.fixed == 0
    _, checks, bus = report(tmp_path, fix=True, bus=Bus(caps=(885, 1750), error=32))  # latched: omx_incident reboots
    assert "omx_incident" in checks["registers"]["detail"] and bus.fixed == 0


def test_a_running_session_or_lock_skips_the_bus_and_never_reads_it(tmp_path):
    for kw in ({"sessions": ["python record_session.py --arm arm_a --io chunk-fifo"]}, {"locked": True},
               {"sessions": ["python record_session.py --config x"]}):
        _, checks, bus = report(tmp_path, bus=Bus(caps=(885, 1750)), fix=True, **kw)
        assert checks["bus ownership"]["status"] == "skipped" and checks["registers"]["status"] == "skipped"
        assert bus.fixed == 0
    _, checks, _ = report(tmp_path, sessions=["python record_session.py --arm arm_b"], bus=Bus(caps=(885, 1750)), fix=True)
    assert checks["registers"]["status"] == "fixed"  # another arm's session does not own this bus


def test_a_wrist_turned_by_hand_while_folded_needs_the_home_stage(tmp_path):
    """2026-11-19: torque OFF, someone turned all three wrists ~95 units; nothing flagged it until a run refused."""
    home = [0.0, -62.0, 53.0, 51.6, 44.9, 49.0]
    arms = arms_setup(tmp_path)
    (tmp_path / "chunks.json").write_text(json.dumps({"gripper_closed": 49.0, "chunks": {"home": [home]}}))
    bus = Bus()
    for r, value in zip(bus.rows, home[:5] + [49.0]):
        r["position_raw"] = round((value + 100) * 4095 / 200)
    rep, checks, _ = report(tmp_path, arms, bus=bus)
    assert checks["pose"]["status"] == "ok" and rep["verdict"] == "ready"
    bus.rows[4]["position_raw"] = round((-50.5 + 100) * 4095 / 200)
    rep, checks, _ = report(tmp_path, arms, bus=bus)
    assert checks["pose"]["status"] == "fail" and "--stage home" in checks["pose"]["detail"]
    assert rep["verdict"] == "needs_motion_step"


def test_a_failed_camera_unit_and_a_dark_top_frame_fail(tmp_path):
    _, checks, _ = report(tmp_path, urls={"http://v/wrist.jpg": (503, b"")})
    assert checks["cameras"]["status"] == "fail" and "wrist" in checks["cameras"]["detail"] and "503" in checks["cameras"]["detail"]
    _, checks, _ = report(tmp_path, mean=1.4)
    assert checks["light top"]["status"] == "fail"
    _, checks, _ = report(tmp_path, urls={"http://v/top.jpg": (200, b"<html>")})
    assert "not a JPEG" in checks["cameras"]["detail"]


def health_log(path, closed_cmd=46.6, stop=48.84, pwm=-150):
    cmd, present = round(closed_cmd * 4095 / 100), round(stop * 4095 / 100)  # gripper raw: 1999 reads 48.8
    names = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]
    rows = [{"event": "sample", "sample_time": 1000 + i, "motors": [
        {"joint": n, "usb_port": f"/dev/serial/by-id/{DEV}", "command_raw": cmd if n == "gripper" else 2048,
         "present_raw": present if n == "gripper" else 2048, "pwm": pwm if n == "gripper" else 0, "pwm_limit": 300}
        for n in names]} for i in range(6)]
    path.write_text("\n".join(json.dumps(r) for r in rows))


def test_a_closed_value_below_the_jaws_stop_is_flagged_with_the_numbers(tmp_path):
    arms = arms_setup(tmp_path, closed=46.6)
    health_log(tmp_path / "motor-health-1.jsonl")
    _, checks, _ = report(tmp_path, arms)
    jaw = checks["jaw closed"]
    assert jaw["status"] == "warn" and "target 46.6" in jaw["detail"] and "48.8" in jaw["detail"] and "-150" in jaw["detail"]
    arms = arms_setup(tmp_path, closed=49.0)  # the library now closes at the stop
    assert report(tmp_path, arms)[1]["jaw closed"]["status"] == "ok"


def trace(path, pairs):
    path.write_text("\n".join(json.dumps({"sent": [0] * 5 + [s], "present": [0] * 5 + [p]}) for s, p in pairs))


def test_jaws_that_stop_short_of_the_last_command_need_a_person(tmp_path):
    """The site's open_max is 62 while a library asked 58.6: the session's own command is the yardstick."""
    arms = arms_setup(tmp_path)
    (tmp_path / "cell.json").write_text(json.dumps({**json.loads((tmp_path / "cell.json").read_text()),
                                                    "params_path": str(tmp_path / "params.json")}))
    (tmp_path / "params.json").write_text(json.dumps({"schema": "rosy.omx-cell-params.v1", "params": {"gripper.open_max": {
        "value": 62.0, "unit": "gripper", "source": "measured", "evidence": "the site's value"}}}))
    trace(tmp_path / "trace-arm_a-1.jsonl", [(49.0, 49.0), (58.6, 52.0), (58.6, 53.9)])  # arm_b 2026-11-04 04:55
    rep, checks, _ = report(tmp_path, arms)
    assert checks["jaw open"]["status"] == "warn" and "53.90 of 58.60" in checks["jaw open"]["detail"]
    assert rep["verdict"] == "needs_person"
    trace(tmp_path / "trace-arm_a-1.jsonl", [(49.0, 49.0), (61.98, 61.17)])  # the same arm at 03:00
    assert report(tmp_path, arms)[1]["jaw open"]["status"] == "ok"
    trace(tmp_path / "trace-arm_a-1.jsonl", [(49.74, 49.74)])  # a closing-only session reaches its command
    assert report(tmp_path, arms)[1]["jaw open"]["status"] == "ok"


def test_a_missing_map_is_a_motion_step_and_a_hold_needs_a_person(tmp_path):
    rep, checks, _ = report(tmp_path, todo=["remap", "regions"])
    assert checks["map"]["status"] == "warn" and "auto --commissioning --person-at-switch" in checks["map"]["detail"]
    assert rep["verdict"] == "needs_motion_step"
    (tmp_path / "incidents").mkdir()
    (tmp_path / "incidents/HOLD-arm_a.json").write_text(json.dumps({"reason": "elbow overload at home"}))
    rep, checks, _ = report(tmp_path, todo=["remap"])
    assert "elbow overload" in checks["hold"]["detail"] and rep["verdict"] == "needs_person"


def test_monitors_report_hits_from_logs_newer_than_the_last_report(tmp_path):
    arms = arms_setup(tmp_path)
    health_log(tmp_path / "motor-health-1.jsonl")
    seen = []
    io, _ = make_io()
    hit = {"FF06202D": {"hits": [{"session": "s", "t": 3.0, "reason": "elbow wound up"}]}}
    io.replays = lambda h, t, p: (seen.append(h) or hit, {})
    out = cu.run(arms, io=io, out_dir=tmp_path / "upkeep", incidents=tmp_path / "i", stamp="S")["arm_a"]
    assert {c["check"]: c for c in out["checks"]}["monitors"]["status"] == "warn" and seen[0]
    io.replays = lambda h, t, p: (seen.append(h) or {}, {})
    cu.run(arms, io=io, out_dir=tmp_path / "upkeep", incidents=tmp_path / "i", stamp="T")
    assert len(seen) == 1  # the log is older than the report just written: no replay


def test_tcp_evidence_comes_from_the_cell_config():
    assert "0.074" in cu.check_tcp({"tcp_x_m": 0.074, "tcp_x_m_evidence": "box-top touch"})["detail"]


LABELS = {"top": "/top_camera/image_raw", "front": "/arm_a_wrist_camera/image_raw",
          "arm_b_wrist": "/arm_b_wrist_camera/image_raw"}
ROLES = {"/arm_a_wrist_camera/image_raw": "arm_a_wrist", "/arm_b_wrist_camera/image_raw": "arm_b_wrist"}


def test_a_wrist_url_the_viewer_does_not_serve_names_the_label_that_does():
    """2026-11-04: arm_a's config read arm_a_wrist.jpg; the viewer serves that topic as front.jpg."""
    io = cu.Io(fetch=lambda url: (404, b"") if "arm_a_wrist" in url else (200, JPEG), labels=lambda: LABELS, roles=lambda: ROLES)
    rows, _ = cu.check_cameras("arm_a", {"wrist": {"url": "http://v/frame/arm_a_wrist.jpg"}}, io)
    assert rows[0]["status"] == "fail" and "http://v/frame/front.jpg" in rows[0]["detail"]


def test_a_preview_unit_left_on_a_replaced_device_is_restarted_only_with_fix_and_a_free_bus():
    """2026-11-04: after a reconnect rosy-omx-camera@arm_a_wrist polled the old node ('selected camera is unavailable')."""
    state = {"up": False, "restarts": 0}

    def restart(role):
        state["up"], state["restarts"] = True, state["restarts"] + 1
    io = cu.Io(fetch=lambda url: (200, JPEG) if state["up"] or "front" not in url else (404, b""), labels=lambda: LABELS,
               roles=lambda: ROLES, unit_tail=lambda role: "selected camera is unavailable\n", unit_restart=restart)
    cams = {"wrist": {"url": "http://v/frame/front.jpg"}}
    assert cu.check_cameras("arm_a", cams, io)[0][0]["status"] == "fail" and state["restarts"] == 0
    assert cu.check_cameras("arm_a", cams, io, fix=True, bus_free=False)[0][0]["status"] == "fail" and state["restarts"] == 0
    rows, _ = cu.check_cameras("arm_a", cams, io, fix=True, bus_free=True)
    assert rows[0]["status"] == "fixed" and "arm_a_wrist" in rows[0]["detail"] and state["restarts"] == 1


class Usb:
    """A D435 whose first direct reads give nothing; `late` reads after the re-enable fail before one streams."""

    def __init__(self, boards=(), late=3, speed=480):
        self.boards, self.late, self.speed = list(boards), late, speed
        self.log, self.cycled = [], False

    def io(self):
        def frames(device):
            self.log.append("read")
            if not self.cycled:
                return False
            self.late -= 1
            return self.late < 0
        return cu.Io(fetch=lambda url: (200, JPEG) if self.cycled else (503, b""), labels=lambda: LABELS, roles=lambda: ROLES,
                     unit_tail=lambda role: "watchdog", unit_restart=lambda role: None, device=lambda role: "/dev/cam",
                     usb_port=lambda device: {"ports": ["root", "peer"], "speed": self.speed, "boards": self.boards},
                     frames=frames, ports=self.ports, units=lambda role, up: self.log.append("units up" if up else "units down"),
                     sleep=lambda s: self.log.append(f"sleep {s}"))

    def ports(self, ports, disabled):
        self.log.append(f"{'off' if disabled else 'on'} {','.join(ports)}")
        self.cycled = self.cycled or not disabled


CAMS = {"wrist": {"url": "http://v/frame/front.jpg"}}


def test_a_camera_with_no_frames_gets_its_root_port_and_peer_cycled_and_a_late_first_frame_is_waited_for():
    """2026-11-05: a D435 on a USB2 root port gave 0 bytes until port and peer were off 30 s and a minute passed."""
    usb = Usb()
    rows, _ = cu.check_cameras("arm_a", CAMS, usb.io(), fix=True, bus_free=True)
    assert rows[0]["status"] == "fixed" and "480 Mbit/s" in rows[0]["detail"] and "WARN: USB2" in rows[0]["detail"]
    log = usb.log
    assert log[0] == "units down" and log[-1] == "units up"
    assert log.index("off root,peer") < log.index("sleep 30") < log.index("on root,peer")
    assert log.count("read") == 1 + 4  # one before the cycle, three late misses, then the frame


def test_a_port_shared_with_an_arm_board_is_never_cycled():
    usb = Usb(boards=["usb-ROBOTIS_OpenRB-150_AAAA-if00"])
    rows, _ = cu.check_cameras("arm_a", CAMS, usb.io(), fix=True, bus_free=True)
    assert rows[0]["status"] == "fail" and "OpenRB-150" in rows[0]["detail"]
    assert usb.log == []


def test_without_fix_the_dead_camera_is_only_reported():
    usb = Usb()
    rows, _ = cu.check_cameras("arm_a", CAMS, usb.io(), fix=False, bus_free=True)
    assert rows[0]["status"] == "fail" and usb.log == []


def usb_tree(tmp_path, monkeypatch, board_root="4-4"):
    """A USB3 camera and a USB2 serial board behind paired root ports, using real symlinks."""
    ports = []
    for bus in (3, 4):
        root = tmp_path / f"sys/devices/platform/usb{bus}"
        (root / f"{bus}-4").mkdir(parents=True)
        port = root / f"{bus}-0:1.0/usb{bus}-port4"
        port.mkdir(parents=True)
        (port / "disable").write_text("0")
        link = tmp_path / f"sys/bus/usb/devices/{bus}-0:1.0"
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(port.parent, target_is_directory=True)
        (link.parent / f"{bus}-4").symlink_to(root / f"{bus}-4", target_is_directory=True)
        ports.append(port)
    (ports[0] / "peer").symlink_to(ports[1], target_is_directory=True)
    camera = tmp_path / "sys/devices/platform/usb3/3-4/3-4.2"
    camera.mkdir()
    (camera / "idVendor").write_text("8086")
    (camera / "speed").write_text("5000")
    (camera / "3-4.2:1.0").mkdir()
    video = tmp_path / "sys/class/video4linux/video0/device"
    video.parent.mkdir(parents=True)
    video.symlink_to(camera / "3-4.2:1.0", target_is_directory=True)
    dev = tmp_path / "dev"
    (dev / "serial/by-id").mkdir(parents=True)
    (dev / "video0").touch()
    (dev / "cam").symlink_to(dev / "video0")
    board = tmp_path / f"sys/devices/platform/usb{board_root[0]}/{board_root}/{board_root}.1"
    board.mkdir(parents=True)
    tty = tmp_path / "sys/class/tty/ttyUSB0/device"
    tty.parent.mkdir(parents=True)
    tty.symlink_to(board, target_is_directory=True)
    (dev / "ttyUSB0").touch()
    (dev / "serial/by-id" / DEV).symlink_to(dev / "ttyUSB0")

    def redirect(path):
        path = Path(path)
        return tmp_path / str(path).lstrip("/") if path.is_absolute() and path.parts[1] in ("sys", "dev") else path

    realpath, glob = cu.os.path.realpath, cu.glob.glob
    monkeypatch.setattr(cu, "Path", redirect)
    monkeypatch.setattr(cu.os.path, "realpath", lambda p, **kw: realpath(redirect(p), **kw))
    monkeypatch.setattr(cu.glob, "glob", lambda p: glob(str(redirect(p))))
    return ports


def test_usb_recovery_refuses_a_board_below_the_peer_root(tmp_path, monkeypatch):
    usb_tree(tmp_path, monkeypatch)
    usb = Usb()
    io = usb.io()
    io.usb_port = cu.usb_port
    assert "refused" in cu.usb_recover("arm_a_wrist", io)
    assert usb.log == []


def test_usb_root_matching_does_not_include_a_neighboring_port(tmp_path, monkeypatch):
    usb_tree(tmp_path, monkeypatch, board_root="3-40")
    assert cu.usb_port("/dev/cam")["boards"] == []


def test_usb_recovery_leaves_an_already_disabled_peer_alone(tmp_path, monkeypatch):
    ports = usb_tree(tmp_path, monkeypatch)
    (ports[1] / "disable").write_text("1")
    with pytest.raises(OSError):
        cu.usb_port("/dev/cam")


def test_missing_camera_sysfs_chain_terminates_with_a_resolution_error(tmp_path):
    code = ("import cell_upkeep as c\ntry: c.usb_port(" + repr(str(tmp_path / "missing-camera")) + ")\n"
            "except OSError: pass\nelse: raise AssertionError('missing chain accepted')")
    try:
        result = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, "
                                 + repr(str(Path(cu.__file__).parent)) + "); " + code],
                                capture_output=True, text=True, timeout=3)
    except subprocess.TimeoutExpired:
        pytest.fail("missing camera sysfs traversal did not terminate")
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("failure", ["partial-disable", "interrupted-wait"])
def test_usb_recovery_reenables_ports_after_a_failed_cycle(failure):
    usb = Usb()
    io = usb.io()
    disabled = set()

    def ports(names, off):
        for name in names:
            if off and failure == "partial-disable" and name == "peer":
                raise OSError("peer write failed")
            disabled.add(name) if off else disabled.discard(name)

    def sleep(seconds):
        if seconds == 30:
            raise KeyboardInterrupt("interrupted wait")

    io.ports, io.sleep = ports, sleep
    with pytest.raises(OSError if failure == "partial-disable" else KeyboardInterrupt):
        cu.usb_recover("arm_a_wrist", io)
    assert disabled == set()
    assert usb.log[-1] == "units up"


def test_port_restore_attempts_the_peer_even_when_the_first_write_fails(monkeypatch):
    restored = []

    def run(argv, **kw):
        if argv[-1] == "root/disable":
            raise subprocess.CalledProcessError(1, argv)
        restored.append(argv[-1])

    monkeypatch.setattr(cu.subprocess, "run", run)
    with pytest.raises(subprocess.CalledProcessError):
        cu.port_set(["root", "peer"], False)
    assert restored == ["peer/disable"]


def test_optional_camera_offline_leaves_upkeep_ok_without_usb_cycle():
    io = cu.Io(fetch=lambda url: (200, JPEG) if "wrist" in url else (503, b""), labels=lambda: LABELS, roles=lambda: ROLES)
    rows, top = cu.check_cameras("arm_s", {
        "top": {"url": "http://v/frame/arm_s_top.jpg", "optional": True},
        "wrist": {"url": "http://v/frame/arm_s_wrist.jpg"},
    }, io, fix=True, bus_free=True, usb_recover_fn=lambda *a: (_ for _ in ()).throw(AssertionError("must not cycle optional")))
    assert top is None and rows[0]["status"] == "ok" and "optional top offline" in rows[0]["detail"]


def test_check_map_warns_needs_person_on_low_zone_gaps(tmp_path):
    gap = {
        "site": "beltend", "z_m": -0.0571, "floor_z_m": 0.005, "uncovered": 3, "total": 9,
        "mapped_x_m": [0.10, 0.19], "mapped_y_m": [0.09, 0.25],
        "uncovered_x_m": [0.11, 0.19], "uncovered_y_m": [0.174, 0.25],
    }
    io, _ = make_io()
    io.calibrate = lambda c, cal, f, p: {"check": {"missing_map": [], "low_zone_gaps": [gap]}, "todo": []}
    out = cu.run(arms_setup(tmp_path), io=io, out_dir=tmp_path / "upkeep", incidents=tmp_path / "incidents", stamp="G")["arm_a"]
    checks = {c["check"]: c for c in out["checks"]}
    assert checks["map"]["status"] == "warn"
    assert "low_zones gap" in checks["map"]["detail"] and "beltend" in checks["map"]["detail"]
    assert not checks["map"].get("motion")
    assert out["verdict"] == "needs_person"


def test_usb_recovery_reauthorizes_isolated_camera_leaf_when_root_port_carries_openrb(tmp_path, monkeypatch):
    usb_tree(tmp_path, monkeypatch, board_root="3-4")
    camera = tmp_path / "sys/devices/platform/usb3/3-4/3-4.2"
    (camera / "authorized").write_text("1")
    (camera / "bDeviceClass").write_text("ef")
    port_info = cu.usb_port("/dev/cam")
    assert port_info["leaf"].endswith("3-4.2") and port_info["leaf_authorized"] == "1" and port_info["leaf_boards"] == []
    assert port_info["boards"] == [DEV]
    state, log = {"reauth": False}, []

    def frames(device):
        log.append("read")
        return state["reauth"]

    def leaf_auth(leaf, enabled):
        log.append(f"auth {1 if enabled else 0}")
        if enabled:
            state["reauth"] = True

    io = cu.Io(
        fetch=lambda url: (200, JPEG) if state["reauth"] else (503, b""),
        labels=lambda: LABELS,
        roles=lambda: ROLES,
        unit_tail=lambda role: "watchdog",
        unit_restart=lambda role: None,
        device=lambda role: "/dev/cam",
        usb_port=cu.usb_port,
        frames=frames,
        ports=lambda *a: (_ for _ in ()).throw(AssertionError("root port must not cycle")),
        leaf_auth=leaf_auth,
        rebind=lambda: log.append("rebind"),
        units=lambda role, up: log.append("units up" if up else "units down"),
        sleep=lambda s: log.append(f"sleep {s}"),
    )
    rows, _ = cu.check_cameras("arm_a", CAMS, io, fix=True, bus_free=True)
    assert rows[0]["status"] == "fixed" and "re-authorized USB leaf 3-4.2" in rows[0]["detail"]
    assert log == ["units down", "read", "auth 0", "sleep 2", "auth 1", "sleep 2", "rebind", "sleep 2", "read", "units up"]


def test_usb_recovery_refuses_leaf_reset_on_hub_or_composite_serial_leaf(tmp_path, monkeypatch):
    usb_tree(tmp_path, monkeypatch, board_root="3-4")
    camera = tmp_path / "sys/devices/platform/usb3/3-4/3-4.2"
    (camera / "authorized").write_text("1")
    (camera / "bDeviceClass").write_text("09")
    assert "leaf" not in cu.usb_port("/dev/cam")
    usb = Usb(boards=[DEV])
    io = usb.io()
    io.usb_port = cu.usb_port
    io.leaf_auth = lambda *a: (_ for _ in ()).throw(AssertionError("must never toggle hub authorized"))
    assert "refused" in cu.usb_recover("arm_a_wrist", io)
    assert usb.log == []
    with pytest.raises(OSError, match="USB hub"):
        cu.leaf_authorize(str(camera), False)

    # Composite device carrying an OpenRB interface on the same leaf must also refuse leaf reset.
    io2 = usb.io()
    io2.usb_port = lambda _d: {"ports": ["root"], "speed": 480, "boards": [DEV], "leaf": str(camera), "leaf_authorized": "1", "leaf_boards": [DEV]}
    io2.leaf_auth = lambda *a: (_ for _ in ()).throw(AssertionError("must never toggle composite leaf with OpenRB"))
    assert "refused" in cu.usb_recover("arm_a_wrist", io2)
    assert usb.log == []


def test_usb_recovery_restores_leaf_authorized_on_interruption():
    auth, log = [True], []

    def leaf_auth(leaf, enabled):
        auth[0] = enabled
        log.append(f"auth {1 if enabled else 0}")

    def sleep(s):
        if s == 2 and not auth[0]:
            raise KeyboardInterrupt("interrupted during de-authorize")

    io = cu.Io(
        device=lambda role: "/dev/cam",
        usb_port=lambda d: {"ports": ["root"], "speed": 480, "boards": [DEV], "leaf": "/sys/bus/usb/devices/3-4.2.1",
                            "leaf_authorized": "1", "leaf_boards": []},
        frames=lambda d: False,
        ports=lambda *a: (_ for _ in ()).throw(AssertionError("root port must not cycle")),
        leaf_auth=leaf_auth,
        rebind=lambda: log.append("rebind"),
        units=lambda role, up: log.append("units up" if up else "units down"),
        sleep=sleep,
    )
    with pytest.raises(KeyboardInterrupt):
        cu.usb_recover("arm_b_wrist", io)
    assert auth[0] is True
    assert log == ["units down", "auth 0", "auth 1", "units up"]


def _unconfigured_leaf_tree(tmp_path, *, bcfg="", has_v4l=False, bclass="ef", extra_arm_a=False, second_cam=False):
    hub = tmp_path / "sys/devices/pci/3-4/3-4.2"
    cam = hub / "3-4.2.1"
    cam.mkdir(parents=True)
    (cam / "bDeviceClass").write_text(bclass)
    (cam / "idVendor").write_text("0c45")
    (cam / "idProduct").write_text("6367")
    (cam / "authorized").write_text("1")
    (cam / "speed").write_text("480")
    if bcfg is not None:
        (cam / "bConfigurationValue").write_text(bcfg)
    if has_v4l:
        (cam / "3-4.2.1:1.0/video4linux/video8").mkdir(parents=True)

    openrb = hub / "3-4.2.3"
    openrb.mkdir(parents=True)
    (openrb / "idVendor").write_text("2f5d")
    (openrb / "serial").write_text("SER_ARM_B")

    if extra_arm_a:
        oa = hub / "3-4.2.4"
        oa.mkdir(parents=True)
        (oa / "idVendor").write_text("2f5d")
        (oa / "serial").write_text("SER_ARM_A")
    if second_cam:
        c2 = hub / "3-4.2.2"
        c2.mkdir(parents=True)
        (c2 / "bDeviceClass").write_text("ef")
        (c2 / "idVendor").write_text("0c45")
        (c2 / "idProduct").write_text("6367")
        (c2 / "authorized").write_text("1")

    sys_usb = tmp_path / "sys/bus/usb/devices"
    sys_usb.mkdir(parents=True)
    for node in hub.iterdir():
        (sys_usb / node.name).symlink_to(node, target_is_directory=True)

    cams_path = tmp_path / "omx-cameras.json"
    cams_path.write_text(json.dumps({"cameras": [{"role": "arm_b_wrist", "device": str(tmp_path / "dev/v4l/by-id/rosy-arm_b_wrist"), "usb_id": "0c45:6367"}]}))
    boards_path = tmp_path / "omx-arm-boards.json"
    boards_path.write_text(json.dumps({"SER_ARM_B": "arm_b", "SER_ARM_A": "arm_a"}))
    return cam, sys_usb, cams_path, boards_path


def test_usb_recovery_recovers_unconfigured_leaf_when_by_id_missing(tmp_path):
    cam, sys_usb, cams_path, boards_path = _unconfigured_leaf_tree(tmp_path, bcfg="")
    state, log = {"ok": False}, []

    def missing_usb_port(_dev):
        raise FileNotFoundError("no such by-id symlink")

    def frames(_dev):
        log.append("read")
        return state["ok"]

    def leaf_auth(leaf, enabled):
        log.append(f"auth {1 if enabled else 0} {Path(leaf).name}")
        if enabled:
            state["ok"] = True

    io = cu.Io(
        device=lambda _role: str(tmp_path / "dev/v4l/by-id/rosy-arm_b_wrist"),
        usb_port=missing_usb_port,
        unconfigured_leaf=lambda role: cu.unconfigured_usb_leaf(role, sys_usb=sys_usb, cameras_path=cams_path, boards_path=boards_path),
        frames=frames,
        ports=lambda *a: (_ for _ in ()).throw(AssertionError("root port must not cycle")),
        leaf_auth=leaf_auth,
        rebind=lambda: log.append("rebind"),
        units=lambda _role, up: log.append("units up" if up else "units down"),
        sleep=lambda s: log.append(f"sleep {s}"),
    )
    msg = cu.usb_recover("arm_b_wrist", io)
    assert "re-authorized USB leaf 3-4.2.1" in msg and "SER_ARM_B untouched" in msg
    assert log == ["units down", "read", "auth 0 3-4.2.1", "sleep 2", "auth 1 3-4.2.1", "sleep 2", "rebind", "sleep 2", "read", "units up"]


def test_unconfigured_usb_leaf_refuses_hub_shared_arms_ambiguous_or_already_bound(tmp_path):
    _, sys_usb, cams_path, boards_path = _unconfigured_leaf_tree(tmp_path, bclass="09")
    assert cu.unconfigured_usb_leaf("arm_b_wrist", sys_usb=sys_usb, cameras_path=cams_path, boards_path=boards_path) is None

    hub_dir = tmp_path / "sys"
    import shutil
    shutil.rmtree(hub_dir)
    _, sys_usb, cams_path, boards_path = _unconfigured_leaf_tree(tmp_path, extra_arm_a=True)
    assert cu.unconfigured_usb_leaf("arm_b_wrist", sys_usb=sys_usb, cameras_path=cams_path, boards_path=boards_path) is None

    shutil.rmtree(hub_dir)
    _, sys_usb, cams_path, boards_path = _unconfigured_leaf_tree(tmp_path, second_cam=True)
    assert cu.unconfigured_usb_leaf("arm_b_wrist", sys_usb=sys_usb, cameras_path=cams_path, boards_path=boards_path) is None

    shutil.rmtree(hub_dir)
    _, sys_usb, cams_path, boards_path = _unconfigured_leaf_tree(tmp_path, bcfg="1", has_v4l=True)
    assert cu.unconfigured_usb_leaf("arm_b_wrist", sys_usb=sys_usb, cameras_path=cams_path, boards_path=boards_path) is None
