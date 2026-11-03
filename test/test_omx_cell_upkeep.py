"""cell_upkeep with fakes for each failure of 2026-11-03/04: a missing board, caps at 885, a 503 camera, a closed
value below the jaws' stop, a missing map, a hold. No hardware, no motion."""
import json
from pathlib import Path
import sys

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
