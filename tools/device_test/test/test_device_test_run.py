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
            pose = None if r.pose_none else {"x": r.x, "y": 0.0, "yaw": 0.0}
            return 200, {"online": True, "mode": "IDLE", "battery": {"percent": 80}, "safety": {"estop": False},
                         "pose": pose, "localization": r.localization}
        if key == ("GET", "/line-follow"):
            if r.lf_mode == "OFF":
                return 200, {"mode": "OFF", "state": "IDLE", "reason": "off", "linear": 0.0}
            reason = r.reasons.pop(0) if r.reasons else r.default_reason
            moving = reason not in ("blocked_unexplained",)
            r.x += 0.008 if moving else 0.0
            state = "RECOVERING" if reason == "lane_bridge" else "TRACKING"
            return 200, {"mode": "CAMERA_LINE", "state": state, "reason": reason,
                         "linear": 0.08 if moving else 0.0, "angular": 0.0}
        if key == ("PUT", "/line-follow/mode"):
            status = r.start_status if mode == "CAMERA_LINE" else r.off_status
            if status == 200:
                r.lf_mode = mode
            return status, {"mode": mode} if status == 200 else {"code": "NOT_LOCALIZED"}
        if key == ("POST", "/mode"):
            return r.idle_status, {}
        if key == ("POST", "/line-follow/hold"):
            return 200, {}
        if key == ("GET", "/vision/front/status"):
            return 200, {"sequence": 1}
        if key == ("GET", "/vision/front/frame"):
            return 200, b"\xff\xd8front\xff\xd9"
        if key == ("GET", "/sensors/lidar"):
            return 200, {"ranges": [1.5] * 360, "angle_min": -math.pi, "angle_increment": 2 * math.pi / 360,
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
        self.__dict__.update(kw)
        self.core = FakeCore(self)

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s

    def overhead(self):
        return b"\xff\xd8overhead\xff\xd9"

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
         "robot_seen_is_target": True, "path_clear": True, "cable_seen": True,
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
    assert run.load_plan(PLAN)["accepted_risks"][0]["key"] == "line_follow.bridge_site_no_dropoffs"
    for broken in ([], [{"key": "line_follow.bridge_site_no_dropoffs", "date": "2026-10-08", "reason": "x"}]):
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
