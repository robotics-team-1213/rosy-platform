"""D-512 device test runner on a fake robot (no network, no SSH, virtual clock)."""
import hashlib
import json
import math
import signal
import sys
from pathlib import Path

import importlib.util

import pytest
import yaml

_TOOL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_TOOL))
# Load by path under a unique name: another suite already imports a different
# top-level `run` module, and a bare `import run` would reuse that one.
_spec = importlib.util.spec_from_file_location("device_test_run", _TOOL / "run.py")
run = importlib.util.module_from_spec(_spec)
sys.modules["device_test_run"] = run
_spec.loader.exec_module(run)

ROBOT = "rosy-pinky-test"
PLAN = Path(__file__).resolve().parents[1] / "plans" / "d476_bridge_9dfk.yaml"
ORIGINAL = b"robot:\n  name: Rosy 26\n# operator comment kept byte for byte\nline_follow:\n  bridge_enabled: false\n"


class FakeCore:
    def __init__(self, robot):
        self.robot = robot

    def call(self, method, path, body=None, raw=False, timeout=3.0, attempts=2):
        r = self.robot
        mode = body.get("mode") if isinstance(body, dict) else None
        r.log.append(f"{method} {path.split('?')[0]}" + (f" {mode}" if mode else ""))
        if r.on_call:
            r.on_call(method, path, mode)
        key = (method, path.split("?")[0])
        if key == ("GET", "/system/info"):
            return 200, {"robot_id": "rosy_26", "robot_name": "Rosy 26"}
        if key == ("GET", "/robot/state"):
            if r.state_fail and r.lf_mode == "CAMERA_LINE":
                return 0, None
            pose = None if r.pose_none else {"x": r.x, "y": r.y, "yaw": math.atan2(math.sin(r.yaw), math.cos(r.yaw))}
            return 200, {"online": True, "mode": r.mode, "map_id": r.map_id, "battery": {"percent": 80}, "safety": {"estop": False},
                         "pose": pose, "localization": r.localization}
        if key == ("GET", "/line-follow"):
            if r.lf_mode == "OFF":
                return 200, {"mode": "OFF", "state": "IDLE", "reason": "off", "linear": 0.0}
            reason = r.reasons.pop(0) if r.reasons else r.default_reason
            moving = reason not in ("blocked_unexplained",)
            r.yaw += r.yaw_rate if moving else 0.0
            r.x += 0.008 * math.cos(r.yaw) if moving else 0.0
            r.y += 0.008 * math.sin(r.yaw) if moving else 0.0
            state = "RECOVERING" if reason == "lane_bridge" else "TRACKING"
            return 200, {"mode": "CAMERA_LINE", "state": state, "reason": reason,
                         "linear": 0.08 if moving else 0.0, "angular": 0.0}
        if key == ("PUT", "/line-follow/mode"):
            status = r.start_status if mode == "CAMERA_LINE" else r.off_status
            if status == 200:
                r.lf_mode = mode
            return status, {"mode": mode} if status == 200 else {"code": "NOT_LOCALIZED"}
        if key == ("POST", "/mode"):
            if r.idle_status == 200:
                r.mode = mode
            return r.idle_status, {}
        if key == ("POST", "/teleop"):
            r.teleops.append((body["linear"], body["angular"]))
            r.yaw += body["angular"] * 0.1
            r.x += body["linear"] * math.cos(r.yaw) * 0.1
            r.y += body["linear"] * math.sin(r.yaw) * 0.1
            return 200, {}
        if key == ("POST", "/line-follow/hold"):
            return 200, {}
        if key == ("POST", "/host/lamp/identify"):
            s = r.identify_status.pop(0) if r.identify_status else 200
            if s != 200:
                return s, {"error": {"code": {409: "IDENTIFY_COLOR_UNSET", 429: "HW_TEST_COOLDOWN"}.get(s, "NOT_FOUND")}}
            r.blink_t = r.t
            return 200, {"accepted": True, "request_id": "req1", "color": "blue", "state": "pending_visual_confirmation"}
        if key == ("GET", "/vision/front/status"):
            return 200, {"sequence": 1}
        if key == ("GET", "/vision/front/frame"):
            return 200, b"\xff\xd8front\xff\xd9"
        if key == ("GET", "/sensors/lidar"):
            return 200, {"ranges": r.lidar_ranges(), "received_at": r.scan_t, "source_stamp_ns": int(r.scan_t * 1e9), "angle_min": -math.pi, "angle_increment": 2 * math.pi / 360,
                         "range_min": 0.05, "range_max": 12.0}
        if key == ("POST", "/recordings"):
            r.rec = True
            return 201, {"id": "rec1"}
        if key == ("GET", "/recordings/active"):
            if r.rec_unreachable and not r.rec:
                return 0, None
            return 200, {"active": {"state": "recording", "id": "rec1"} if r.rec else None}
        if key == ("POST", "/recordings/active/stop"):
            r.rec = False
            return 200, {"state": "stopping"}
        if key == ("GET", "/recordings"):
            return 200, {"items": []}
        if key == ("GET", "/events"):
            if "since_seq" in path and r.events:
                return 200, {"events": [r.events.pop(0)], "last_seq": 10}
            return 200, {"events": [], "last_seq": 9}
        raise AssertionError(f"unexpected call {method} {path}")

    def raw_frame(self, timeout=5.0):
        return b"\xff\xd8raw\xff\xd9"


class FakeRobot:
    def __init__(self, overlay=ORIGINAL, precheck="ok", reasons=(), events=(), **kw):
        self.t, self.x, self.lf_mode, self.rec, self.pid, self.hold = 1000.0, 0.0, "OFF", False, 100, False
        self.overlay, self.tmp, self.precheck = overlay, None, precheck
        self.reasons, self.events, self.log = list(reasons), list(events), []
        self.default_reason, self.pose_none, self.localization = "following", False, None
        self.off_status = self.idle_status = self.start_status = 200
        self.release_rc, self.corrupt_tee, self.mangle_after_mv, self.fail_restore = 0, False, False, False
        self.core_env, self.core_errors, self.on_call = "HOME=/var/lib/rosy/core", "0", None
        self.state_fail = self.rec_unreachable = False
        self.restart_rc = self.precheck_rc = 0
        self.y = self.yaw = self.yaw_rate = 0.0
        self.mode, self.lidar_range, self.teleops = "IDLE", 1.5, []
        self.lidar_block, self.lidar_frozen, self.site_map_id, self.map_id = None, False, "map_v2_fleet", "map_v2_fleet"
        self.calib = [CALIB]
        self.identify_status, self.blink_t, self.blink_at = [], None, None   # blink_at None: at the map origin
        self.blink_s, self.blink_bgr, self.led_at, self.light_change = 6.0, (255, 0, 0), [], False
        self.__dict__.update(kw)
        self.core = FakeCore(self)

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s

    def overhead(self):
        """A grey overhead JPEG. For blink_s after an identify the lamp (blink_bgr, blue) blinks at
        blink_at, 0.4 s on / 0.4 s off; led_at blink like that always (a charge light); light_change
        brightens the whole frame after the request."""
        import cv2
        import numpy as np
        size, h = (self.calib or [CALIB])[0]["image"], (self.calib or [CALIB])[0]["map_to_image"]
        img = np.full((size["height"], size["width"], 3), 90, np.uint8)
        if self.light_change and self.blink_t is not None:
            img[:] = 170
        dt = None if self.blink_t is None else self.t - self.blink_t
        if dt is not None and dt <= self.blink_s and int((dt + 1e-6) / 0.4) % 2 == 0:
            for u, v in [(h[2], h[5])] if self.blink_at is None else self.blink_at:
                cv2.circle(img, (int(u), int(v)), 4, self.blink_bgr, -1)
        if int((self.t + 1e-6) / 0.4) % 2 == 0:
            for u, v in self.led_at:
                cv2.circle(img, (int(u), int(v)), 3, (40, 255, 40), -1)
        return cv2.imencode(".jpg", img)[1].tobytes()

    def overhead_source(self):
        return "cam1"

    def calibrations(self):
        return self.calib

    def active_site_map_id(self):
        return self.site_map_id

    @property
    def scan_t(self):
        return 5.0 if self.lidar_frozen else self.t

    def lidar_ranges(self):
        """1.5 m everywhere; lidar_block "front"/"rear" puts 0.1 m returns in that +-30 deg body sector."""
        fwd = run.edge_drive.lidar_forward_deg(ROBOT)[0]
        centre = {"front": 0.0, "rear": 180.0}.get(self.lidar_block)
        out = []
        for i in range(360):
            body = (-180.0 + i - fwd + 180.0) % 360.0 - 180.0
            near = centre is not None and abs((body - centre + 180.0) % 360.0 - 180.0) <= 30.0
            out.append(0.1 if near else self.lidar_range)
        return out

    def ssh(self, cmd, stdin=b""):
        self.log.append("ssh " + cmd)
        if cmd == "hostname":
            return 0, (ROBOT + "\n").encode()
        if cmd == "systemctl is-active rosy-core":
            return 0, b"active\n"
        if cmd.endswith(" precheck"):
            if self.precheck_rc:
                return self.precheck_rc, b"Traceback: boom"
            out = f"hold by {run.HOLDER}: topic" if self.hold and self.precheck == "ok" else self.precheck
            return 0, out.encode()
        if " hold --holder" in cmd:
            self.hold = True
            return 0, b"{}"
        if cmd.endswith("release-hold"):
            if self.release_rc == 0:
                self.hold = False
            return self.release_rc, b"busy" if self.release_rc else b"{}"
        if cmd.startswith("pid=$(systemctl show"):
            return 0, f"pid={self.pid}\nactive=active\n{self.core_env}\nerrors={self.core_errors}\n".encode()
        if cmd == "sudo -n systemctl restart rosy-core":
            if self.restart_rc:
                return self.restart_rc, b""
            self.pid += 1
            return 0, b""
        if "sudo -n cat" in cmd:
            return (3, b"") if self.overlay is None else (0, self.overlay)
        if "cp -a" in cmd:
            return 0, b""
        if "sudo -n tee" in cmd:
            if self.fail_restore and stdin == ORIGINAL:
                return 1, b""
            self.tmp = stdin.replace(b"true", b"false") if self.corrupt_tee else stdin
            parsed = json.dumps(yaml.safe_load(self.tmp.decode("utf-8")), sort_keys=True)
            return 0, f"{hashlib.sha256(self.tmp).hexdigest()}\n{parsed}\n".encode()
        if "mv -f" in cmd:
            self.overlay = self.tmp.replace(b"bridge_enabled: true", b"bridge_enabled: false") \
                if self.mangle_after_mv else self.tmp
            self.tmp = None
            return 0, b""
        if cmd.startswith("sudo -n rm -f"):
            if cmd.endswith(".device-test.tmp"):
                self.tmp = None
            else:
                self.overlay = None
            return 0, b""
        raise AssertionError(f"unexpected ssh {cmd}")


def verdict(tmp_path, robot, **over):
    ev = tmp_path / "pre"
    ev.mkdir(exist_ok=True)
    frames = {}
    for name in ("before_overhead.jpg", "before_front.jpg"):
        (ev / name).write_bytes(b"\xff\xd8" + name.encode())
        frames[name] = run.sha(ev / name)
    v = {"captured_at": robot.t, "pose_at_capture": {"x": 0.0, "y": 0.0}, "robot_at_start": True,
         "robot_seen_is_target": True, "path_clear": True, "cable_seen": True, "cable_attached": False,
         "cable_in_path_or_wheels": False, "note": "cable behind the robot", "judged_by": "agent rosy-test",
         "frames": frames, **over}
    p = ev / "camera_verdict.json"
    p.write_text(json.dumps(v), encoding="utf-8")
    return p


def plan_file(tmp_path, overlay=None, **stop):
    plan = yaml.safe_load(PLAN.read_text(encoding="utf-8"))
    plan["stop"].update({"duration_s": 3, **stop})
    if overlay is not None:
        plan["overlay"] = overlay
    p = tmp_path / "plan.yaml"
    p.write_text(yaml.safe_dump(plan), encoding="utf-8")
    return p


def go(tmp_path, robot, *extra, verdict_path=None, plan=None, peer="ListAgents: none"):
    argv = ["--robot", ROBOT, "--plan", str(plan or plan_file(tmp_path)), "--peer-check-ok", peer,
            "--evidence-dir", str(tmp_path / "ev"), "--summary-dir", str(tmp_path / "docs"), *extra]
    if "--preflight-only" not in extra and "--dry-run" not in extra:
        argv += ["--camera-verdict", str(verdict_path or verdict(tmp_path, robot))]
    code = run.main(argv, robot=robot)
    path = tmp_path / "docs" / "summary.json"
    return code, json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def phases(summary):
    return [p["phase"] for p in summary["phases"]]


def marker(tmp_path):
    return (tmp_path / "ev" / run.MARKER).exists()


def assert_restored(robot, tmp_path):
    assert robot.overlay == ORIGINAL and robot.tmp is None and not robot.hold
    assert robot.lf_mode == "OFF" and not robot.rec and not marker(tmp_path)


def test_happy_path_phase_order_evidence_and_byte_exact_revert(tmp_path):
    robot = FakeRobot(reasons=["following"] * 5 + ["lane_bridge"] * 3)
    code, s = go(tmp_path, robot)
    assert code == 0, s["outcome"]
    assert phases(s) == ["peers", "identity", "health", "camera:start", "verdict", "hold", "overlay", "localized",
                         "record", "start", "stream", "cleanup:line-follow OFF", "cleanup:IDLE",
                         "cleanup:recording stop", "cleanup:overlay revert", "cleanup:hold release", "camera:after"]
    assert_restored(robot, tmp_path)
    assert robot.pid == 102                                          # restarted for apply and for restore
    assert s["observed"]["reasons"]["lane_bridge"] == 3 and s["missing_expected"] == []
    for name in ("status.jsonl", "events.jsonl", "start_overhead.jpg", "start_front.jpg", "after_overhead.jpg",
                 "overlay_before.yaml"):
        assert s["evidence"][name].startswith("sha256:")
    assert len((tmp_path / "ev" / "status.jsonl").read_text(encoding="utf-8").splitlines()) >= 29   # 10 Hz, 3 s
    assert (tmp_path / "docs" / "README.md").exists()
    assert s["phases"][4]["accepted_risk"].startswith("cable near the robot")


def test_abort_mid_stream_still_turns_off_reverts_and_releases(tmp_path):
    robot = FakeRobot(reasons=["following", "obstacle_ahead"])
    code, s = go(tmp_path, robot)
    assert code == 2 and "obstacle_ahead" in s["outcome"]
    assert_restored(robot, tmp_path)


def test_abort_event_and_missing_file_overlay_is_removed_again(tmp_path):
    robot = FakeRobot(overlay=None, events=[{"seq": 10, "type": "safety.estop", "data": {}}])
    code, s = go(tmp_path, robot)
    assert code == 2 and "safety.estop" in s["outcome"]
    assert robot.overlay is None and not robot.hold and not marker(tmp_path)


def test_overlay_readback_mismatch_aborts_before_motion_and_reverts(tmp_path):
    robot = FakeRobot(mangle_after_mv=True)
    code, s = go(tmp_path, robot)
    assert code == 2 and "readback mismatch" in s["outcome"]
    assert "PUT /line-follow/mode CAMERA_LINE" not in robot.log and "POST /recordings" not in robot.log
    assert robot.overlay == ORIGINAL and not robot.hold


def test_temp_file_that_does_not_validate_never_replaces_the_overlay(tmp_path):
    robot = FakeRobot(corrupt_tee=True)
    code, s = go(tmp_path, robot)
    assert code == 2 and "did not validate" in s["outcome"]
    assert robot.overlay == ORIGINAL and robot.tmp is None


@pytest.mark.parametrize("env, errors, why", [("ROSY_CONFIG=/tmp/other.yaml", "0", "CORE reads /tmp/other.yaml"),
                                              ("HOME=/var/lib/rosy/core", "2", "config errors"),
                                              ("HOME=/var/lib/rosy/core", "?", "could not be read")])
def test_core_effective_config_mismatch_aborts_and_restores(tmp_path, env, errors, why):
    robot = FakeRobot(core_env=env, core_errors=errors)
    code, s = go(tmp_path, robot)
    assert code == 2 and why in s["outcome"]
    assert "PUT /line-follow/mode CAMERA_LINE" not in robot.log


@pytest.mark.parametrize("precheck, why", [("hold by rosy-c5: G4 seal (until 2026-10-08T12:00:00Z)", "foreign or unclear"),
                                           ("hold.json unreadable (bad); release it with release-hold", "foreign or unclear"),
                                           ("claim held by fleet (seal)", "foreign or unclear")])
def test_peer_or_unclear_hold_aborts_without_touching_the_robot(tmp_path, precheck, why):
    robot = FakeRobot(precheck=precheck)
    code, s = go(tmp_path, robot)
    assert code == 2 and why in s["outcome"]
    assert not any(e.startswith(("POST /mode", "PUT", "ssh (sudo")) or " hold --holder" in e for e in robot.log)
    assert robot.overlay == ORIGINAL and not marker(tmp_path)


def test_own_stale_hold_points_to_restore(tmp_path):
    code, s = go(tmp_path, FakeRobot(precheck=f"hold by {run.HOLDER}: x (until z)"))
    assert code == 2 and "--restore" in s["outcome"]


@pytest.mark.parametrize("over, why", [({"cable_in_path_or_wheels": True}, "cable in the planned path"),
                                       ({"path_clear": False}, "path_clear"),
                                       ({"pose_at_capture": {"x": 0.3, "y": 0.0}}, "moved since"),
                                       ({"pose_at_capture": None}, "pose unknown"),
                                       ({"captured_at": 0}, "old"),
                                       ({"robot_at_start": None}, "true/false"),
                                       ({"judged_by": ""}, "judged_by"),
                                       ({"frames": {"before_front.jpg": "sha256:00"}}, "overhead"),
                                       ({"frames": {"before_overhead.jpg": "sha256:00", "before_front.jpg": "x"}},
                                        "changed since")])
def test_camera_verdict_gates_before_any_change(tmp_path, over, why):
    robot = FakeRobot()
    code, s = go(tmp_path, robot, verdict_path=verdict(tmp_path, robot, **over))
    assert code == 2 and why in s["outcome"], s["outcome"]
    assert not any("rosy_auto_update.py" in e or e.startswith(("POST /mode", "PUT")) for e in robot.log)


def test_current_pose_unknown_fails_closed(tmp_path):
    robot = FakeRobot(pose_none=True)
    code, s = go(tmp_path, robot)
    assert code == 2 and "pose unknown" in s["outcome"]


def test_pose_lost_while_driving_aborts_under_a_distance_cap(tmp_path):
    robot = FakeRobot()
    robot.on_call = lambda m, p, mode: setattr(robot, "pose_none", robot.lf_mode == "CAMERA_LINE")
    code, s = go(tmp_path, robot)
    assert code == 2 and "distance cap cannot be enforced" in s["outcome"]
    assert_restored(robot, tmp_path)


def test_unexplained_stop_is_an_abort_not_a_pass(tmp_path):
    robot = FakeRobot(default_reason="blocked_unexplained")
    code, s = go(tmp_path, robot, plan=plan_file(tmp_path, duration_s=20, still_s=2))
    assert code == 2 and "suspected contact" in s["outcome"]
    assert_restored(robot, tmp_path)


def test_listed_still_reason_ends_the_run(tmp_path):
    robot = FakeRobot(default_reason="blocked_unexplained", reasons=["lane_bridge"])
    code, s = go(tmp_path, robot, plan=plan_file(tmp_path, duration_s=20, still_s=2,
                                                 ok_still_reasons=["blocked_unexplained"]))
    assert code == 0 and s["outcome"] == "completed (still)"


def test_not_localized_aborts_before_any_change(tmp_path):
    robot = FakeRobot(localization={"state": "CANDIDATES", "pose_frame": "map"})
    code, s = go(tmp_path, robot)
    assert code == 2 and "not localized" in s["outcome"]
    assert not any(" hold --holder" in e for e in robot.log)


def test_start_refused_409_aborts_and_restores(tmp_path):
    robot = FakeRobot(start_status=409)
    code, s = go(tmp_path, robot)
    assert code == 2 and "CAMERA_LINE refused 409" in s["outcome"]
    assert_restored(robot, tmp_path)


def test_sigterm_mid_stream_runs_cleanup_and_clears_the_marker(tmp_path):
    robot = FakeRobot()
    seen = {"marker_during_run": False, "ticks": 0}

    def term(method, path, mode):
        if robot.lf_mode == "CAMERA_LINE" and path == "/line-follow":
            seen["ticks"] += 1
        if seen["ticks"] == 5:
            seen["marker_during_run"] = marker(tmp_path)
            robot.on_call = None
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
    robot.on_call = term
    code, s = go(tmp_path, robot)
    assert code == 2 and "SIGTERM" in s["outcome"]
    assert seen["marker_during_run"]
    assert_restored(robot, tmp_path)


def test_ctrl_c_during_cleanup_does_not_skip_later_steps(tmp_path):
    robot = FakeRobot(reasons=["following", "obstacle_ahead"])
    handlers = []
    before = signal.getsignal(signal.SIGINT)   # another suite may have installed its own

    def interrupt(method, path, mode):
        if method == "POST" and path == "/mode":
            handlers.append((signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM)))
            raise KeyboardInterrupt
    robot.on_call = interrupt
    code, s = go(tmp_path, robot)
    assert handlers == [(signal.SIG_IGN, signal.SIG_IGN)]            # signals ignored during cleanup
    assert code == 2 and "CLEANUP FAILED" in s["outcome"]
    assert {"cleanup:recording stop", "cleanup:overlay revert", "cleanup:hold release"} <= set(phases(s))
    assert robot.overlay == ORIGINAL and not robot.hold
    assert signal.getsignal(signal.SIGINT) is before   # restored to what it was, not forced to default


@pytest.mark.parametrize("field", ["off_status", "idle_status"])
def test_non_200_off_or_idle_is_a_cleanup_failure(tmp_path, field):
    robot = FakeRobot(**{field: 503})
    code, s = go(tmp_path, robot)
    assert code == 2 and "CLEANUP FAILED" in s["outcome"] and any("HTTP 503" in e for e in s["errors"])


def test_release_hold_busy_is_a_cleanup_failure(tmp_path):
    robot = FakeRobot(release_rc=4)
    code, s = go(tmp_path, robot)
    assert code == 2 and any("release-hold rc 4" in e for e in s["errors"]) and marker(tmp_path)


def test_failed_restore_keeps_hold_and_marker_then_restore_mode_finishes(tmp_path):
    robot = FakeRobot(fail_restore=True)
    code, s = go(tmp_path, robot)
    assert code == 2 and robot.hold and marker(tmp_path)
    assert robot.overlay != ORIGINAL and "cleanup:hold release" not in phases(s)
    assert any("hold KEPT" in e for e in s["errors"])
    robot.fail_restore = False
    code = run.main(["--robot", ROBOT, "--restore", str(tmp_path / "ev"), "--summary-dir", str(tmp_path / "r")],
                    robot=robot)
    assert code == 0
    assert robot.overlay == ORIGINAL and not robot.hold and not marker(tmp_path)


def test_summary_text_is_sanitized_but_digests_stay(tmp_path):
    peer = "ListAgents none; robot at 192.168.1.201, https://site:8443/x, Bearer abc, tok aB3dEfGhIjKlMnOpQrStUvWx12"
    code, s = go(tmp_path, FakeRobot(reasons=["lane_bridge"]), peer=peer)
    text = (tmp_path / "docs" / "summary.json").read_text(encoding="utf-8")
    assert "192.168" not in text and "https://" not in text and "aB3dEfGh" not in text and "Bearer abc" not in text
    assert all(len(v) == 71 for v in s["evidence"].values())          # "sha256:" + 64 hex untouched


def test_preflight_only_writes_frames_and_template_and_changes_nothing(tmp_path):
    robot = FakeRobot()
    code, s = go(tmp_path, robot, "--preflight-only")
    assert code == 0 and s["outcome"] == "preflight"
    template = json.loads((tmp_path / "ev" / "camera_verdict.json").read_text(encoding="utf-8"))
    assert template["robot_at_start"] is None and template["judged_by"] == ""
    assert set(template["frames"]) >= {"before_overhead.jpg", "before_front.jpg"}
    assert all(e.startswith(("GET", "ssh hostname", "ssh systemctl is-active")) for e in robot.log), robot.log


def test_dry_run_makes_no_calls(tmp_path, capsys):
    class Boom:
        def __getattr__(self, name):
            raise AssertionError(f"dry run touched {name}")
    code, s = go(tmp_path, Boom(), "--dry-run")
    assert code == 0 and s is None and not (tmp_path / "ev").exists()
    assert "bridge_enabled" in capsys.readouterr().out


@pytest.mark.parametrize("key, value, why", [
    ("cruise_speed", 0.2, "must be"), ("max_linear", True, "must be"),
    ("ir_guard_enabled", False, "the guard may only be turned on"),
    ("obstacle_stop_m", 0.05, "not an allowed"), ("obstacle_mode", "sector", "not an allowed"),
    ("teleop_timeout_ms", 900, "not an allowed"), ("min_confidence", 0.1, "not an allowed"),
    ("bridge_lookahead_m", 0.2, "not an allowed"),                 # no safer direction
    ("bridge_arm_confidence", 0.3, "must be"),                     # looser than the default 0.5
    ("bridge_arm_frames", 2, "must be"), ("bridge_arm_frames", 3.0, "must be"),
    ("bridge_distance_scale", 1.0, "must be"), ("bridge_time_margin_s", 0.2, "must be"),
    ("bridge_coast_m", 0.2, "must be"), ("bridge_enabled", "yes", "must be"),
    ("bridge_slow_m", 0.2, "the default"), ("bridge_slow_m", 0.3, "the default"),
    ("junction_turn_site_accepted", True, "accepted_risks")])
def test_plan_overlay_rules(tmp_path, key, value, why):
    p = plan_file(tmp_path, overlay={"line_follow": {"bridge_enabled": True, key: value}})
    with pytest.raises(SystemExit, match=why):
        run.load_plan(p)


def test_waiver_needs_a_named_dated_acceptance(tmp_path):
    plan = yaml.safe_load(PLAN.read_text(encoding="utf-8"))
    assert run.load_plan(PLAN)["accepted_risks"][0]["key"] == "line_follow.site_floor_map_id"
    for broken in ([], [{"key": "line_follow.site_floor_map_id", "date": "2026-10-08", "reason": "x"}]):
        plan["accepted_risks"] = broken
        p = tmp_path / "w.yaml"
        p.write_text(yaml.safe_dump(plan), encoding="utf-8")
        with pytest.raises(SystemExit, match="accepted_risks"):
            run.load_plan(p)


def test_plan_overlay_path_is_fixed(tmp_path):
    plan = yaml.safe_load(PLAN.read_text(encoding="utf-8"))
    plan["overlay_path"] = "/var/lib/rosy/core/.rosy/rosy.yaml; rm -rf /"
    p = tmp_path / "evil.yaml"
    p.write_text(yaml.safe_dump(plan), encoding="utf-8")
    with pytest.raises(SystemExit, match="overlay_path must be"):
        run.load_plan(p)


def test_plan_allows_test_keys(tmp_path):
    p = plan_file(tmp_path, overlay={"line_follow": {"bridge_enabled": True, "ir_guard_enabled": True,
                                                     "recovery_local_enabled": False, "cruise_speed": 0.06,
                                                     "bridge_arm_confidence": 0.7, "bridge_distance_scale": 1.2}})
    assert run.load_plan(p)["overlay"]["line_follow"]["cruise_speed"] == 0.06


def test_state_poll_failures_abort_within_half_a_second(tmp_path):
    robot = FakeRobot(state_fail=True)
    code, s = go(tmp_path, robot)
    assert code == 2 and f"failed {run.STATE_FAILS_MAX} times" in s["outcome"]
    assert run.STATE_FAILS_MAX * 0.1 <= 0.5
    assert_restored(robot, tmp_path)


def test_restart_failure_aborts_and_is_reported(tmp_path):
    robot = FakeRobot(restart_rc=1)
    code, s = go(tmp_path, robot)
    assert code == 2 and "systemctl restart rosy-core failed" in s["outcome"]
    assert "PUT /line-follow/mode CAMERA_LINE" not in robot.log


def test_hold_taken_over_mid_run_is_not_released(tmp_path):
    robot = FakeRobot()
    robot.on_call = lambda m, p, mode: setattr(robot, "precheck", "hold by rosy-c5: seal (until z)") \
        if mode == "CAMERA_LINE" else None
    code, s = go(tmp_path, robot)
    assert code == 2 and any("foreign or unclear" in e for e in s["errors"])
    assert robot.hold                                                   # not released by us


def test_unreachable_recorder_is_a_cleanup_failure(tmp_path):
    robot = FakeRobot(reasons=["lane_bridge"], rec_unreachable=True)
    code, s = go(tmp_path, robot)
    assert code == 2 and any("recorder state unknown" in e for e in s["errors"])


def _died_mid_run(tmp_path):
    """A run whose restore failed: overlay still the test one, hold ours, marker left."""
    robot = FakeRobot(fail_restore=True)
    go(tmp_path, robot)
    robot.fail_restore = False
    robot.log.clear()
    assert marker(tmp_path) and robot.hold and robot.overlay != ORIGINAL
    return robot


def _restore(tmp_path, robot):
    return run.main(["--robot", ROBOT, "--restore", str(tmp_path / "ev"), "--summary-dir", str(tmp_path / "r")],
                    robot=robot)


def _sent_nothing(robot):
    return not any(e.startswith(("POST /mode", "PUT")) or "tee" in e or "restart" in e or "release-hold" in e
                   for e in robot.log)


@pytest.mark.parametrize("change, why", [
    (lambda r: setattr(r, "precheck", "hold by rosy-c5: seal (until z)"), "foreign or unclear"),
    (lambda r: setattr(r, "precheck", "hold by rosy pilot: test (until z)"), "foreign or unclear"),
    (lambda r: setattr(r, "precheck", "hold.json unreadable (x); release it with release-hold"),
     "foreign or unclear"),
    (lambda r: setattr(r, "precheck", "claim held by fleet (seal)"), "foreign or unclear"),
    (lambda r: setattr(r, "precheck_rc", 1), "precheck failed"),
    (lambda r: setattr(r, "lf_mode", "CAMERA_LINE"), "someone is driving"),
    (lambda r: setattr(r, "overlay", b"line_follow:\n  bridge_enabled: false\n# peer edit\n"), "overlay changed")])
def test_restore_refuses_when_the_robot_is_no_longer_ours(tmp_path, change, why):
    robot = _died_mid_run(tmp_path)
    change(robot)
    with pytest.raises(SystemExit, match=why):
        _restore(tmp_path, robot)
    assert _sent_nothing(robot) and marker(tmp_path)


def test_restore_refuses_a_marker_with_another_overlay_path(tmp_path):
    robot = _died_mid_run(tmp_path)
    m = json.loads((tmp_path / "ev" / run.MARKER).read_text(encoding="utf-8"))
    m["overlay_path"] = "/x; sudo -n rm -rf /"
    (tmp_path / "ev" / run.MARKER).write_text(json.dumps(m), encoding="utf-8")
    with pytest.raises(SystemExit, match="restore by hand"):
        _restore(tmp_path, robot)
    assert not robot.log                                                # not even an ssh read


def test_summary_is_valid_json_sanitized_and_keeps_ids(tmp_path):
    robot = FakeRobot(reasons=["lane_bridge"])
    peer = 'ListAgents none; Bearer "abc", rec 20261008T120000Z-aB3dEfGhIjKlMn12, release 2026.10.07-051'
    go(tmp_path, robot, peer=peer)
    s = json.loads((tmp_path / "docs" / "summary.json").read_text(encoding="utf-8"))   # still valid JSON
    assert "abc" not in s["peer_check"] and "20261008T120000Z-aB3dEfGhIjKlMn12" in s["peer_check"]
    assert "2026.10.07-051" in s["peer_check"]
    assert run.sanitize({"id": "20261008T120000Z-aB3dEfGhIjKlMnOpQr12", "n": 3, "l": ["10.0.0.1"]}) == \
        {"id": "20261008T120000Z-aB3dEfGhIjKlMnOpQr12", "n": 3, "l": ["<ip>"]}


@pytest.mark.parametrize("precheck, rc", [("hold by rosy pilot: test (until z)", 0),
                                          ("hold.json unreadable (x); release it with release-hold", 0),
                                          ("", 1)])
def test_unclear_hold_at_cleanup_is_not_called_ours_or_none(tmp_path, precheck, rc):
    robot = FakeRobot()
    robot.on_call = lambda m, p, mode: robot.__dict__.update(precheck=precheck, precheck_rc=rc) \
        if mode == "CAMERA_LINE" else None
    code, s = go(tmp_path, robot)
    assert code == 2 and any(e.startswith("hold release") for e in s["errors"]) and marker(tmp_path)


def test_coast_above_slow_is_refused(tmp_path, monkeypatch):
    import plan_rules
    with pytest.raises(SystemExit, match="must be"):
        run.load_plan(plan_file(tmp_path, overlay={"line_follow": {"bridge_coast_m": 0.3}}))
    monkeypatch.setitem(plan_rules.RULES, "line_follow.bridge_coast_m", (lambda v: True, "any"))
    with pytest.raises(SystemExit, match="bridge_coast_m 0.3 > bridge_slow_m 0.25"):
        plan_rules.check_overlay({"line_follow.bridge_coast_m": 0.3})


@pytest.mark.parametrize("date", ["", "not-a-date", "2026-13-40", None])
def test_waiver_date_must_be_iso(tmp_path, date):
    plan = yaml.safe_load(PLAN.read_text(encoding="utf-8"))
    plan["accepted_risks"][0]["date"] = date
    p = tmp_path / "d.yaml"
    p.write_text(yaml.safe_dump(plan), encoding="utf-8")
    with pytest.raises(SystemExit, match="accepted_risks"):
        run.load_plan(p)


def test_observed_keys_are_sanitized_and_id_pattern_is_bounded():
    assert run.sanitize({"reasons": {"seen 10.0.0.7": 1}}) == {"reasons": {"seen <ip>": 1}}
    long_id = "20261008T120000Z-" + "aB3" * 30
    assert run.sanitize(long_id) == "<redacted>"


# --- D-512 tether guard (user decision 2026-10-08) ----------------------------------------------

LOCALIZED = {"state": "LOCALIZED", "pose_frame": "map"}
CALIB = {"source_id": "cam1", "map_id": "map_v2_fleet", "calibration_revision": "paint-abc",
         "map_to_image": [100.0, 0.0, 320.0, 0.0, -100.0, 240.0, 0.0, 0.0, 1.0],   # 100 px/m, map origin at (320, 240)
         "image": {"width": 640, "height": 480}, "use": "display-only"}


def overhead_jpeg(width=640, height=480):
    import cv2
    import numpy as np
    return cv2.imencode(".jpg", np.full((height, width, 3), 90, np.uint8))[1].tobytes()


def tether_check(robot, path, plan=PLAN):
    return run.main(["--robot", ROBOT, "--plan", str(plan), "--tether-check", str(path)], robot=robot)


def tethered(tmp_path, robot, charger, cable_m=2.0, check=True, plan=PLAN, **over):
    """A tethered verdict; check=True also runs --tether-check and records the agent's look."""
    t = {"cable_m": cable_m, "charger_robot_frame": charger, "how": "overhead: 2 m cable to the charger behind"}
    p = verdict(tmp_path, robot, **{"cable_attached": True, "tether": t, "pose_at_capture": {"x": 0.0, "y": 0.0, "yaw": 0.0},
                                    "localization_at_capture": LOCALIZED, "map_id_at_capture": "map_v2_fleet", **over})
    if check:
        v = json.loads(p.read_text(encoding="utf-8"))
        (p.parent / "before_overhead.jpg").write_bytes(overhead_jpeg())
        v["frames"]["before_overhead.jpg"] = run.sha(p.parent / "before_overhead.jpg")
        p.write_text(json.dumps(v), encoding="utf-8")
        assert tether_check(robot, p, plan) == 0
        v = json.loads(p.read_text(encoding="utf-8"))
        assert v["tether"]["visual_check_ok"] is False                 # the agent has not looked yet
        v["tether"]["visual_check_ok"] = True
        p.write_text(json.dumps(v), encoding="utf-8")
    return p


def tplan(tmp_path, duration_s=10, **policy):
    plan = yaml.safe_load(PLAN.read_text(encoding="utf-8"))
    plan["stop"].update(duration_s=duration_s, max_distance_m=20.0)
    if policy:
        plan["tether_policy"] = policy
    p = tmp_path / "tplan.yaml"
    p.write_text(yaml.safe_dump(plan), encoding="utf-8")
    return p


def tgo(tmp_path, robot, charger, duration_s=10, policy=None, **over):
    plan = tplan(tmp_path, duration_s, **(policy or {}))
    v = tethered(tmp_path, robot, charger, plan=plan, **over)
    return go(tmp_path, robot, plan=plan, verdict_path=v)


def moving_teleops(robot):
    return [t for t in robot.teleops if t != (0.0, 0.0)]


def test_charger_is_placed_in_the_start_pose_frame_and_yaw_unwraps(tmp_path):
    assert run.tether.place((2.0, 3.0, math.pi / 2), (1.0, 0.5)) == pytest.approx((1.5, 4.0))
    g = run.tether.Guard({"cable_attached": False, "tether": None}, {"margin_m": 0.3, "max_turn_deg": 360}, tmp_path)
    assert g._update(2.0, 3.0, math.pi / 2) is None                    # no tether: trail and turn only
    g._update(2.0, 3.0, math.pi - 0.1)
    g._update(2.0, 3.0, -math.pi + 0.1)                                 # across +-pi: +0.2 rad, not -6.08
    assert g.turn == pytest.approx(math.pi / 2 - 0.1 + 0.2)


def test_radius_trip_turns_off_then_retraces_the_trail_backwards(tmp_path):
    robot = FakeRobot()
    code, s = tgo(tmp_path, robot, [-1.5, 0.0])
    assert code == 2 and "tether trip tether_radius, retraced" in s["outcome"], s["outcome"]
    t = s["tether"]
    assert t["trip"] == "tether_radius" and t["retrace_completed"] and t["retrace_end"] == "unwound"
    assert t["max_charger_m"] >= 1.7 and t["final_charger_m"] <= 1.6 and t["retrace_m"] > 0.05
    assert t["declared"]["cable_m"] == 2.0 and t["policy"] == {"margin_m": 0.3, "max_turn_deg": 360}
    assert moving_teleops(robot) and all(lin == -run.tether.RETRACE_SPEED for lin, _ in moving_teleops(robot))
    assert 0.0 < robot.x <= 0.008 + 0.1 and abs(robot.y) < 0.01        # start pose x 0.008; slack at 1.6 m
    log = robot.log
    assert log.index("PUT /line-follow/mode OFF") < log.index("POST /mode MANUAL") < log.index("POST /teleop")
    ph = phases(s)
    assert ph.index("tether") < ph.index("tether:retrace") < ph.index("cleanup:line-follow OFF")
    assert s["evidence"]["trail.jsonl"].startswith("sha256:")
    assert_restored(robot, tmp_path)


def test_turn_trip_unwraps_across_pi_and_unwinds_below_the_threshold(tmp_path):
    robot = FakeRobot(yaw_rate=0.05)                                   # a 0.16 m circle, ~12.6 s per turn
    code, s = tgo(tmp_path, robot, [0.0, 0.0], duration_s=30)
    t = s["tether"]
    assert code == 2 and t["trip"] == "tether_turn", s["outcome"]
    assert t["max_turn_deg"] > 360                                     # unwrapped, not the +-180 pose yaw
    assert t["retrace_completed"] and abs(t["final_turn_deg"]) <= 360 - run.tether.UNWIND_TURN_DEG
    assert_restored(robot, tmp_path)


def test_exhausted_trail_stops_at_the_start_pose(tmp_path):
    robot = FakeRobot(yaw_rate=0.05)
    code, s = tgo(tmp_path, robot, [0.0, 0.0], duration_s=30, policy={"max_turn_deg": 91})   # unwind to 1 deg
    t = s["tether"]
    assert code == 2 and t["retrace_end"] == "trail end (start pose)" and t["retrace_completed"]
    start = json.loads((tmp_path / "ev" / "trail.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert abs(robot.x - start["x"]) <= run.tether.END_M + 1e-6


@pytest.mark.parametrize("attr, value, why", [("lidar_block", "rear", "rear body path blocked"),
                                              ("lidar_range", 0.1, "rear body path blocked"),
                                              ("pose_none", True, "pose unknown")])
def test_retrace_stops_on_rear_obstacle_or_pose_gap_without_moving(tmp_path, attr, value, why):
    robot = FakeRobot()
    robot.on_call = lambda m, p, mode: setattr(robot, attr, value) if mode == "MANUAL" else None
    code, s = tgo(tmp_path, robot, [-1.5, 0.0])
    t = s["tether"]
    assert code == 2 and t["retrace_end"].startswith(why) and not t["retrace_completed"], t
    assert "retrace stopped" in s["outcome"] and not moving_teleops(robot)
    assert robot.teleops == [(0.0, 0.0)] and "POST /mode IDLE" in robot.log


def test_retrace_leaves_the_trail_when_odom_diverges(tmp_path):
    robot = FakeRobot()
    robot.on_call = lambda m, p, mode: setattr(robot, "y", robot.y + 0.2) if mode == "MANUAL" else None
    code, s = tgo(tmp_path, robot, [-1.5, 0.0])
    assert code == 2 and s["tether"]["retrace_end"].startswith("off the driven trail") and not moving_teleops(robot)


def test_retrace_never_moves_before_line_follow_off_is_confirmed(tmp_path):
    robot = FakeRobot(off_status=503)
    code, s = tgo(tmp_path, robot, [-1.5, 0.0])
    assert code == 2 and "OFF not confirmed" in s["tether"]["retrace_end"]
    assert "POST /mode MANUAL" not in robot.log and not robot.teleops


@pytest.mark.parametrize("over, why", [
    ({"tether": None}, "cable attached but no tether"),
    ({"tether": {"cable_m": 3.0, "charger_robot_frame": [0.5, 0.0], "how": "x"}}, "cable_m must be one of"),
    ({"tether": {"cable_m": 2.0, "charger_robot_frame": [1.8, 0.0], "how": "x"}}, "over the 1.70 m limit"),
    ({"tether": {"cable_m": 2.0, "charger_robot_frame": [float("nan"), 0.0], "how": "x"}}, "[forward_m, left_m]"),
    ({"tether": {"cable_m": 2.0, "charger_robot_frame": [0.5, 0.0], "how": " "}}, "tether.how is empty"),
    ({"cable_attached": False}, "tether declared but cable_attached is false")])
def test_tether_declaration_gates_before_any_change(tmp_path, over, why):
    robot = FakeRobot()
    code, s = go(tmp_path, robot, verdict_path=tethered(tmp_path, robot, [0.5, 0.0], check=False, **over))
    assert code == 2 and why in s["outcome"], s["outcome"]
    assert not any("rosy_auto_update.py" in e or e.startswith(("POST /mode", "PUT")) for e in robot.log)


def test_own_tether_in_the_wheels_is_allowed_and_the_run_completes(tmp_path):
    robot = FakeRobot(reasons=["lane_bridge"])
    code, s = go(tmp_path, robot, verdict_path=tethered(tmp_path, robot, [-0.5, 0.0], cable_in_path_or_wheels=True))
    assert code == 0, s["outcome"]
    assert s["tether"]["trail_points"] > 1 and "trip" not in s["tether"]
    assert s["phases"][4]["tether"]["cable_m"] == 2.0


@pytest.mark.parametrize("policy, ok", [({"margin_m": 0.1}, False), ({"max_turn_deg": 400}, False),
                                        ({"max_turn_deg": 90}, False), ({"margin_m": 0.5, "max_turn_deg": 180}, True)])
def test_tether_policy_may_only_be_stricter(tmp_path, policy, ok):
    p = tplan(tmp_path, **policy)
    if ok:
        assert run.load_plan(p)["tether_policy"] == {"margin_m": 0.5, "max_turn_deg": 180}
    else:
        with pytest.raises(SystemExit, match="tether_policy"):
            run.load_plan(p)

def test_overlay_points_from_a_known_homography():
    pts = run.tether.overlay_points(CALIB["map_to_image"], (1.0, 0.0, math.pi / 2), [1.0, 0.0], 0.5)
    assert pts["charger"] == pytest.approx((420.0, 140.0))           # 1 m ahead of a robot facing +y: map (1, 1)
    assert pts["robot"] == pytest.approx((420.0, 240.0)) and pts["heading"] == pytest.approx((420.0, 230.0))
    assert pts["circle"][0] == pytest.approx((470.0, 140.0))
    assert all(math.hypot(u - 420.0, v - 140.0) == pytest.approx(50.0) for u, v in pts["circle"])
    behind = [0, 0, 0, 0, 0, 0, 0, 0, -1.0]                            # w <= 0: never a guessed pixel
    assert all(math.isnan(c) for c in run.tether.overlay_points(behind, (0, 0, 0), [0, 0], 1)["charger"])


def test_tether_check_draws_the_charger_and_binds_the_values(tmp_path):
    import cv2
    import numpy as np
    robot = FakeRobot()
    p = tethered(tmp_path, robot, [-1.5, 0.0])
    v = json.loads(p.read_text(encoding="utf-8"))
    img = p.parent / run.tether.CHECK_IMAGE
    assert v["frames"][run.tether.CHECK_IMAGE] == run.sha(img)
    assert v["tether"]["check"]["source_id"] == "cam1" and v["tether"]["check"]["map_id"] == "map_v2_fleet"
    b, g, r = cv2.imdecode(np.frombuffer(img.read_bytes(), np.uint8), cv2.IMREAD_COLOR)[240, 170]
    assert r > 180 and g < 90 and b < 90                               # red charger dot at map (-1.5, 0)
    sent = [e for e in robot.log if e.startswith(("POST", "PUT", "ssh"))]
    assert sent == ["POST /host/lamp/identify"]                       # only the lamp blink (D-512 amendment 2)


@pytest.mark.parametrize("change, why", [
    (lambda r, v: setattr(r, "calib", []), "no approved camera-to-map calibration"),
    (lambda r, v: setattr(r, "calib", None), "no approved camera-to-map calibration"),
    (lambda r, v: setattr(r, "calib", [{**CALIB, "source_id": "other"}]), "no approved camera-to-map calibration"),
    (lambda r, v: setattr(r, "calib", [{**CALIB, "image": {"width": 1280, "height": 720}}]), "matching the judged"),
    (lambda r, v: v.update(localization_at_capture=None), "not a localized map pose"),
    (lambda r, v: v.update(localization_at_capture={"state": "LOCALIZED", "pose_frame": "odom"}), "map pose"),
    (lambda r, v: v["tether"].update(cable_m=5.0, charger_robot_frame=[4.6, 0.0]), "outside the overhead picture")])
def test_tether_check_fails_closed(tmp_path, change, why):
    robot = FakeRobot()
    p = tethered(tmp_path, robot, [-1.5, 0.0], check=False)
    v = json.loads(p.read_text(encoding="utf-8"))
    (p.parent / "before_overhead.jpg").write_bytes(overhead_jpeg())
    v["frames"]["before_overhead.jpg"] = run.sha(p.parent / "before_overhead.jpg")
    change(robot, v)
    p.write_text(json.dumps(v), encoding="utf-8")
    with pytest.raises(SystemExit, match=why):
        tether_check(robot, p)
    assert not (p.parent / run.tether.CHECK_IMAGE).exists()


@pytest.mark.parametrize("edit", [lambda t: t.update(visual_check_ok=False),
                                  lambda t: t.update(charger_robot_frame=[-1.2, 0.3]),   # changed after the look
                                  lambda t: t.pop("check")])
def test_tethered_run_needs_the_visual_check_for_these_values(tmp_path, edit):
    robot = FakeRobot()
    p = tethered(tmp_path, robot, [-1.5, 0.0])
    v = json.loads(p.read_text(encoding="utf-8"))
    edit(v["tether"])
    p.write_text(json.dumps(v), encoding="utf-8")
    code, s = go(tmp_path, robot, plan=tplan(tmp_path), verdict_path=p)
    assert code == 2 and "run --tether-check" in s["outcome"], s["outcome"]
    assert not any("rosy_auto_update.py" in e or e.startswith(("POST /mode", "PUT")) for e in robot.log)


def test_retrace_reverses_with_only_the_front_blocked(tmp_path):
    robot = FakeRobot()
    robot.on_call = lambda m, p, mode: setattr(robot, "lidar_block", "front") if mode == "MANUAL" else None
    code, s = tgo(tmp_path, robot, [-1.5, 0.0])
    assert s["tether"]["retrace_end"] == "unwound" and moving_teleops(robot)


def test_retrace_stops_on_a_stale_scan(tmp_path):
    robot = FakeRobot()
    robot.on_call = lambda m, p, mode: setattr(robot, "lidar_frozen", True) if mode == "MANUAL" else None
    code, s = tgo(tmp_path, robot, [-1.5, 0.0])
    assert s["tether"]["retrace_end"].startswith("LiDAR scan not updated") and not s["tether"]["retrace_completed"]
    assert len(moving_teleops(robot)) <= run.tether.SCAN_STALE_S / run.tether.TICK_S + 1


def test_retrace_keeps_ten_hertz_and_stops_on_a_slow_period(tmp_path):
    robot = FakeRobot()
    code, s = tgo(tmp_path, robot, [-1.5, 0.0])
    assert s["tether"]["retrace_max_period_s"] == pytest.approx(run.tether.TICK_S)
    robot, seen = FakeRobot(), []

    def slow(m, p, mode):
        if p == "/teleop" and len(robot.teleops) == 3 and not seen:
            seen.append(1)
            robot.t += 0.35                                            # one stalled call
    robot.on_call = slow
    code, s = tgo(tmp_path, robot, [-1.5, 0.0])
    assert s["tether"]["retrace_end"].startswith("send period") and s["tether"]["retrace_max_period_s"] > 0.3


def test_retrace_samples_are_marked_in_the_trail(tmp_path):
    code, s = tgo(tmp_path, FakeRobot(), [-1.5, 0.0])
    rows = [json.loads(x) for x in (tmp_path / "ev" / "trail.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {r["phase"] for r in rows} == {"drive", "retrace"} and rows[0]["phase"] == "drive"


@pytest.mark.parametrize("attr, value", [("x", 0.1), ("yaw", math.radians(5))])
def test_first_driving_pose_must_be_the_checked_capture_pose(tmp_path, attr, value):
    robot = FakeRobot()
    robot.on_call = lambda m, p, mode: setattr(robot, attr, value) if mode == "CAMERA_LINE" else None
    code, s = tgo(tmp_path, robot, [-1.5, 0.0])
    assert code == 2 and "first driving pose" in s["outcome"] and not robot.teleops, s["outcome"]
    assert_restored(robot, tmp_path)


def test_charger_inside_the_retrace_slack_of_the_limit_is_refused(tmp_path):
    robot = FakeRobot()
    code, s = go(tmp_path, robot, verdict_path=tethered(tmp_path, robot, [-1.65, 0.0], check=False))
    assert code == 2 and "retrace slack" in s["outcome"]


def test_check_records_the_display_only_label_and_map(tmp_path):
    p = tethered(tmp_path, FakeRobot(), [-1.5, 0.0])
    c = json.loads(p.read_text(encoding="utf-8"))["tether"]["check"]
    assert c["use"] == "display-only" and c["mode"] == "map" and c["map_id"] == "map_v2_fleet"


def test_map_mode_needs_the_robots_map(tmp_path):
    robot = FakeRobot()
    with pytest.raises(SystemExit, match="not the robot's map at capture"):
        tethered(tmp_path, robot, [-1.5, 0.0], map_id_at_capture="other_map")


# --- pixel mode (pre-D-395 robots such as 9dfk: odom pose, no localization) ----------------------

CALIB_HD = {**CALIB, "map_to_image": [1000.0, 0.0, 640.0, 0.0, -1000.0, 360.0, 0.0, 0.0, 1.0],   # 1 mm/px
            "image": {"width": 1280, "height": 720}}
FRONT = run.tether.PINKY_PRO.front_x_m


def px(x, y):
    return [640.0 + 1000.0 * x, 360.0 - 1000.0 * y]


@pytest.mark.parametrize("front, charger, want_yaw, want", [
    ((FRONT, 0.0), (-0.3, 0.2), 0.0, [-0.3, 0.2]),
    ((0.0, FRONT), (-0.3, 0.2), 90.0, [0.2, 0.3])])
def test_pixels_give_the_charger_in_the_robot_frame(front, charger, want_yaw, want):
    pose, got, length = run.tether.from_pixels(CALIB_HD["map_to_image"], {
        "robot_center": px(0, 0), "robot_front": px(*front), "charger": px(*charger)}, (1280, 720))
    assert pose == pytest.approx((0.0, 0.0, math.radians(want_yaw))) and got == pytest.approx(want)
    assert length == pytest.approx(FRONT)


@pytest.mark.parametrize("h, pixels, why", [
    ([1, 2, 3, 2, 4, 6, 0, 0, 1], None, "singular"),
    (None, {"robot_front": [1300.0, 360.0]}, "inside the 1280x720 frame"),
    (None, {"robot_front": px(0.3, 0.0)}, "not within"),                 # 0.3 m: not the body front
    (None, {"robot_front": px(0.002, 0.0)}, "not within"),
    (None, {"charger": "here"}, r"charger must be \[u, v\]")])
def test_pixel_mode_fails_closed(h, pixels, why):
    base = {"robot_center": px(0, 0), "robot_front": px(FRONT, 0), "charger": px(-0.3, 0.2)}
    with pytest.raises(ValueError, match=why):
        run.tether.from_pixels(h or CALIB_HD["map_to_image"], {**base, **(pixels or {})}, (1280, 720))


def pixel_verdict(tmp_path, robot, **over):
    t = {"cable_m": 2.0, "how": "picked on before_overhead.jpg", "pixels": {
        "robot_center": px(0, 0), "robot_front": px(FRONT, 0), "charger": px(-0.3, 0.2)}}
    p = verdict(tmp_path, robot, **{"cable_attached": True, "tether": t, "localization_at_capture": None,
                                    "pose_at_capture": {"x": 0.0, "y": 0.0, "yaw": 0.0}, **over})
    v = json.loads(p.read_text(encoding="utf-8"))
    (p.parent / "before_overhead.jpg").write_bytes(overhead_jpeg(1280, 720))
    v["frames"]["before_overhead.jpg"] = run.sha(p.parent / "before_overhead.jpg")
    p.write_text(json.dumps(v), encoding="utf-8")
    return p


def test_pixel_mode_check_then_odom_run(tmp_path):
    robot = FakeRobot(calib=[CALIB_HD], reasons=["lane_bridge"])
    p = pixel_verdict(tmp_path, robot)
    assert tether_check(robot, p) == 0
    v = json.loads(p.read_text(encoding="utf-8"))
    t = v["tether"]
    assert t["charger_robot_frame"] == pytest.approx([-0.3, 0.2]) and t["check"]["mode"] == "pixels"
    assert t["from_pixels"]["heading_deg"] == 0.0 and t["from_pixels"]["robot_center_m"] == [0.0, 0.0]
    t["visual_check_ok"] = True
    p.write_text(json.dumps(v), encoding="utf-8")
    code, s = go(tmp_path, robot, verdict_path=p)                      # odom pose, no localization: allowed
    assert code == 0, s["outcome"]
    assert s["tether"]["max_charger_m"] == pytest.approx(math.hypot(-0.3 - robot.x, 0.2), abs=0.02)


def test_pixel_mode_needs_the_fleet_active_site_map(tmp_path):
    robot = FakeRobot(calib=[CALIB_HD], site_map_id="another_site")
    with pytest.raises(SystemExit, match="not the Fleet active SiteMap"):
        tether_check(robot, pixel_verdict(tmp_path, robot))
    robot.site_map_id = None
    with pytest.raises(SystemExit, match="not the Fleet active SiteMap"):
        tether_check(robot, pixel_verdict(tmp_path, robot))


# --- D-512 amendment 2: lamp identify proves the drawn robot is the target ------------------------

IDENT = run.tether.identify


def test_identify_blob_at_the_robot_passes_and_is_recorded(tmp_path):
    robot = FakeRobot()
    p = tethered(tmp_path, robot, [-1.5, 0.0])
    ident = json.loads(p.read_text(encoding="utf-8"))["tether"]["identity"]
    assert ident["request_id"] == "req1" and ident["color"] == "blue" and ident["distance_px"] <= 2.0
    assert ident["pick_px"] == [320.0, 240.0] and ident["radius_px"] == pytest.approx(100 * IDENT.RADIUS_M, 0.01)
    assert ident["blob_frames"] >= IDENT.MIN_FRAMES and ident["pixel_count"] > 0 and len(ident["blob_bbox"]) == 4
    frames = ident["frames"]
    assert all(f["sha256"].startswith("sha256:") for f in frames) and frames[0]["name"] == "identify_00.jpg"
    base = [f for f in frames if f["phase"] == "baseline"]
    assert len(base) == 11 and base[-1]["t"] == pytest.approx(IDENT.BASELINE_S)     # 2 s before the request
    assert [f["phase"] for f in frames[len(base):]] == ["blink"] * (len(frames) - len(base))
    assert all(a["t"] < b["t"] for a, b in zip(frames, frames[1:]))
    assert ident["blob_frames"] < len(frames) - len(base)                         # it blinked, not steady
    assert ident["colour_check"].startswith("hue 1") and ident["colour_check"].endswith("within 20 of blue")
    assert (p.parent / "identify_00.jpg").exists() and "POST /host/lamp/identify" in robot.log
    assert run.tether.check(json.loads(p.read_text(encoding="utf-8")), {"margin_m": 0.3, "max_turn_deg": 360})


@pytest.mark.parametrize("over, why", [
    ({"blink_at": [(560, 420)]}, "the lamp blob at"),                     # the lamp blinks at another robot
    ({"blink_at": []}, "no lamp change seen"),
    ({"blink_at": [(320, 240), (560, 420)]}, "another strong change|the lamp blob at"),   # two blobs: ambiguous
    ({"identify_status": [404]}, r"unavailable \(HTTP 404"),
    ({"identify_status": [409]}, "IDENTIFY_COLOR_UNSET"),
    ({"identify_status": [429, 429]}, "HTTP 429, HW_TEST_COOLDOWN"),
    ({"blink_s": 0.3}, "no lamp change seen"),                               # 2 frames: weak
    ({"light_change": True}, "larger than the body"),                        # whole-frame lighting change
    ({"led_at": [(320, 240)]}, "already changed in"),                        # a charge light at the pick
    ({"blink_bgr": (0, 170, 255)}, "from blue")])                            # an amber lamp, CORE said blue
def test_identify_refuses_the_tether_check(tmp_path, over, why):
    robot = FakeRobot(**over)
    with pytest.raises(SystemExit, match=why) as exc:
        tethered(tmp_path, robot, [-1.5, 0.0])
    assert "confirm the robot another way" in str(exc.value)
    assert not (tmp_path / "pre" / run.tether.CHECK_IMAGE).exists()
    v = json.loads((tmp_path / "pre" / "camera_verdict.json").read_text(encoding="utf-8"))
    ident = v["tether"]["identity"]                                         # the refusal is evidence too
    assert ident["refused"] == str(exc.value).removeprefix("tether check: ") and ident["frames"]
    assert v["tether"]["visual_check_ok"] is False
    with pytest.raises(ValueError, match="no lamp identify proved the robot"):
        run.tether.check({**v, "tether": {**v["tether"], "visual_check_ok": True}}, {"margin_m": 0.3})


def test_identify_refuses_a_radius_that_is_not_a_number(tmp_path):
    h = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0]                        # every floor point past the horizon
    assert math.isnan(IDENT.radius_px(h, (0.0, 0.0), run.tether._project))
    robot = FakeRobot()
    for radius in (float("nan"), float("inf"), 0.0):
        with pytest.raises(IDENT.Refused, match="not a positive number"):
            IDENT.identify(robot, (320.0, 240.0), radius, tmp_path)
    assert "POST /host/lamp/identify" not in robot.log


def test_an_old_verdict_without_identity_does_not_run(tmp_path):
    robot = FakeRobot()
    p = tethered(tmp_path, robot, [-1.5, 0.0])
    v = json.loads(p.read_text(encoding="utf-8"))
    del v["tether"]["identity"]
    p.write_text(json.dumps(v), encoding="utf-8")
    code, s = go(tmp_path, robot, verdict_path=p)
    assert code == 2 and "no lamp identify proved the robot" in s["outcome"]


def test_identify_waits_out_the_cooldown_once(tmp_path):
    robot = FakeRobot(identify_status=[429])
    t0 = robot.t
    p = tethered(tmp_path, robot, [-1.5, 0.0])
    assert robot.log.count("POST /host/lamp/identify") == 2 and robot.t - t0 >= IDENT.COOLDOWN_S
    base = [f for f in json.loads(p.read_text(encoding="utf-8"))["tether"]["identity"]["frames"]
            if f["phase"] == "baseline"]
    assert len(base) == 22 and base[11]["t"] >= IDENT.BASELINE_S + IDENT.COOLDOWN_S   # a fresh baseline after the wait


def test_pixel_mode_identify_uses_the_picked_center(tmp_path):
    robot = FakeRobot(calib=[CALIB_HD], blink_at=[(640 + 1000 * 0.5, 360)])  # lamp 0.5 m from the pick
    with pytest.raises(SystemExit, match="from the picked robot"):
        tether_check(robot, pixel_verdict(tmp_path, robot))


def test_policy_off_notice_does_not_abort_but_estop_does(tmp_path):
    robot = FakeRobot(reasons=["lane_bridge"], events=[{"seq": 10, "type": "safety.policy_off", "data": {}}])
    code, s = go(tmp_path, robot)
    assert code == 0, s["outcome"]
    assert s["observed"]["events"]["safety.policy_off"] == 1
    robot = FakeRobot(events=[{"seq": 10, "type": "safety.policy_off"}, {"seq": 11, "type": "safety.estop"}])
    code, s = go(tmp_path, robot)
    assert code == 2 and "safety.estop" in s["outcome"]


@pytest.mark.parametrize("ok", [["safety.estop"], ["safety.*"], "safety.policy_off", {"safety.policy_off": 1},
                                [["safety.policy_off"]]])
def test_ok_events_only_informational_names(tmp_path, ok):
    p = plan_file(tmp_path, ok_events=ok)
    with pytest.raises(SystemExit, match="ok_events"):
        run.load_plan(p)


def test_identify_on_real_frames_of_the_nw_robot_blue_blink():
    """2026-10-08 crops (100x60 at x80,y206 of the overhead frame): f00 before, f01..f13 during a blue
    blink of the NW-corner robot. The lamp looks nearly white to the ceiling camera (saturation ~18),
    so the colour is recorded as not judged; the position and the still baseline decide."""
    import cv2
    d = Path(__file__).resolve().parent / "data" / "identify_real"
    f = [cv2.imread(str(d / f"f{i:02d}.png")) for i in range(14)]
    found = IDENT.blobs(f[0], [f[0]], f[1:])
    ev = IDENT.judge(found, (130.0 - 80, 236.0 - 206), 40.0, 13, "blue")
    assert ev["blob_frames"] >= 10 and ev["distance_px"] < 10 and "not judged" in ev["colour_check"]
    with pytest.raises(IDENT.Refused, match="3 of 13|already changed|from the picked"):
        IDENT.judge(found, (90.0, 50.0), 20.0, 13, "blue")        # a pick on another robot
