"""D-512 device test runner on a fake robot (no network, no SSH, virtual clock)."""
import json
import math
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import run  # noqa: E402

ROBOT = "rosy-pinky-test"
PLAN = Path(__file__).resolve().parents[1] / "plans" / "d476_bridge_9dfk.yaml"
ORIGINAL = b"robot:\n  name: Rosy 26\nline_follow:\n  bridge_enabled: false\n"


class FakeCore:
    def __init__(self, robot):
        self.robot, self.calls = robot, []

    def call(self, method, path, body=None, raw=False, timeout=3.0):
        r = self.robot
        self.calls.append((method, path, body))
        r.log.append(f"{method} {path.split('?')[0]}" + (f" {body.get('mode')}" if isinstance(body, dict)
                                                          and "mode" in body else ""))
        key = (method, path.split("?")[0])
        if key == ("GET", "/system/info"):
            return 200, {"robot_id": "rosy_26", "robot_name": "Rosy 26"}
        if key == ("GET", "/robot/state"):
            return 200, {"online": True, "mode": "IDLE", "battery": {"percent": 80},
                         "safety": {"estop": False}, "pose": {"x": r.x, "y": 0.0, "yaw": 0.0}}
        if key == ("GET", "/line-follow"):
            if r.lf_mode == "OFF":
                return 200, {"mode": "OFF", "state": "IDLE", "reason": "off", "linear": 0.0}
            r.x += 0.008
            reason = r.reasons.pop(0) if r.reasons else "following"
            state = "RECOVERING" if reason == "lane_bridge" else "TRACKING"
            return 200, {"mode": "CAMERA_LINE", "state": state, "reason": reason, "linear": 0.08, "angular": 0.0}
        if key == ("PUT", "/line-follow/mode"):
            r.lf_mode = body["mode"]
            return 200, {"mode": body["mode"]}
        if key in (("POST", "/line-follow/hold"), ("POST", "/mode")):
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
    def __init__(self, overlay=ORIGINAL, precheck="ok", corrupt=False, reasons=(), events=()):
        self.t, self.x, self.lf_mode, self.rec = 1000.0, 0.0, "OFF", False
        self.overlay, self.precheck, self.corrupt = overlay, precheck, corrupt
        self.reasons, self.events, self.log = list(reasons), list(events), []
        self.core = FakeCore(self)

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s

    def overhead(self):
        return b"\xff\xd8overhead\xff\xd9"

    def ssh(self, cmd, stdin=b""):
        self.log.append("ssh " + cmd.split(" ")[0] + " " + " ".join(cmd.split(" ")[1:3]))
        if cmd == "hostname":
            return 0, ROBOT + "\n"
        if cmd == "systemctl is-active rosy-core":
            return 0, "active\n"
        if cmd.endswith("precheck"):
            return 0, self.precheck + "\n"
        if "rosy_auto_update.py hold" in cmd or cmd.endswith("release-hold") or "cp -a" in cmd \
                or "systemctl restart" in cmd:
            return 0, "{}"
        if cmd.startswith("if sudo -n test -e"):
            return (3, "") if self.overlay is None else (0, self.overlay.decode())
        if cmd.startswith("sudo -n install -d"):
            assert yaml.safe_load(stdin.decode("utf-8")) is not None
            self.overlay = stdin.replace(b"bridge_enabled: true", b"bridge_enabled: false") if self.corrupt else stdin
            return 0, ""
        if cmd.startswith("sudo -n rm -f"):
            self.overlay = None
            return 0, ""
        raise AssertionError(f"unexpected ssh {cmd}")


def verdict(tmp_path, robot, **over):
    v = {"captured_at": robot.t, "pose_at_capture": {"x": 0.0, "y": 0.0}, "robot_at_start": True,
         "robot_seen_is_target": True, "path_clear": True, "cable_seen": True,
         "cable_in_path_or_wheels": False, "note": "cable behind the robot", **over}
    p = tmp_path / "verdict.json"
    p.write_text(json.dumps(v), encoding="utf-8")
    return p


def plan_file(tmp_path, **stop):
    plan = yaml.safe_load(PLAN.read_text(encoding="utf-8"))
    plan["stop"].update({"duration_s": 3, **stop})
    p = tmp_path / "plan.yaml"
    p.write_text(yaml.safe_dump(plan), encoding="utf-8")
    return p


def go(tmp_path, robot, *extra, verdict_path=None, plan=None):
    argv = ["--robot", ROBOT, "--plan", str(plan or plan_file(tmp_path)), "--peer-check-ok", "ListAgents: none",
            "--evidence-dir", str(tmp_path / "ev"), "--summary-dir", str(tmp_path / "docs"), *extra]
    if "--preflight-only" not in extra and "--dry-run" not in extra:
        argv += ["--camera-verdict", str(verdict_path or verdict(tmp_path, robot))]
    code = run.main(argv, robot=robot)
    summary = json.loads((tmp_path / "docs" / "summary.json").read_text(encoding="utf-8")) \
        if (tmp_path / "docs" / "summary.json").exists() else None
    return code, summary


def phases(summary):
    return [p["phase"] for p in summary["phases"]]


def test_happy_path_phase_order_evidence_and_byte_exact_revert(tmp_path):
    robot = FakeRobot(reasons=["following"] * 5 + ["lane_bridge"] * 3)
    code, s = go(tmp_path, robot)
    assert code == 0, s["outcome"]
    assert phases(s)[:10] == ["peers", "identity", "health", "camera:before", "verdict", "hold", "overlay",
                              "record", "start", "stream"]
    assert phases(s)[10:] == ["cleanup:line-follow OFF", "cleanup:IDLE", "cleanup:recording stop",
                              "cleanup:overlay revert", "cleanup:hold release", "camera:after",
                              "cleanup:after frames"]
    assert robot.overlay == ORIGINAL and robot.lf_mode == "OFF" and not robot.rec
    assert s["observed"]["reasons"]["lane_bridge"] == 3 and s["missing_expected"] == []
    for name in ("status.jsonl", "events.jsonl", "before_overhead.jpg", "before_front.jpg", "after_overhead.jpg",
                 "overlay_before.yaml"):
        assert s["evidence"][name].startswith("sha256:")
    rows = (tmp_path / "ev" / "status.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(rows) >= 29                                           # 10 Hz over 3 s
    assert (tmp_path / "docs" / "README.md").exists()
    assert s["phases"][4]["accepted_risk"].startswith("cable near the robot")


def test_abort_mid_stream_still_turns_off_reverts_and_releases(tmp_path):
    robot = FakeRobot(reasons=["following", "obstacle_ahead"])
    code, s = go(tmp_path, robot)
    assert code == 2 and "obstacle_ahead" in s["outcome"]
    assert {"cleanup:line-follow OFF", "cleanup:IDLE", "cleanup:overlay revert",
            "cleanup:hold release"} <= set(phases(s))
    assert robot.overlay == ORIGINAL and robot.lf_mode == "OFF" and not robot.rec


def test_abort_event_and_missing_file_overlay_is_removed_again(tmp_path):
    robot = FakeRobot(overlay=None, events=[{"seq": 10, "type": "safety.estop", "data": {}}])
    code, s = go(tmp_path, robot)
    assert code == 2 and "safety.estop" in s["outcome"]
    assert robot.overlay is None                                     # there was no file: removed again


def test_overlay_readback_mismatch_aborts_before_motion_and_reverts(tmp_path):
    robot = FakeRobot(corrupt=True)
    code, s = go(tmp_path, robot)
    assert code == 2 and "readback mismatch" in s["outcome"]
    assert "PUT /line-follow/mode CAMERA_LINE" not in robot.log and "POST /recordings" not in robot.log
    assert robot.overlay == ORIGINAL and "cleanup:overlay revert" in phases(s)


def test_peer_hold_aborts_without_touching_the_robot(tmp_path):
    robot = FakeRobot(precheck="hold by rosy-c5: G4 seal (until 2026-10-08T12:00:00Z)")
    code, s = go(tmp_path, robot)
    assert code == 2 and "peer conflict" in s["outcome"]
    assert not any(e.startswith(("POST /mode", "PUT", "ssh sudo -n install")) for e in robot.log)
    assert robot.overlay == ORIGINAL


@pytest.mark.parametrize("over, why", [({"cable_in_path_or_wheels": True}, "cable in the planned path"),
                                       ({"path_clear": False}, "path_clear"),
                                       ({"pose_at_capture": {"x": 0.3, "y": 0.0}}, "moved since"),
                                       ({"captured_at": 0}, "old"),
                                       ({"robot_at_start": None}, "true/false")])
def test_camera_verdict_gates_before_any_change(tmp_path, over, why):
    robot = FakeRobot()
    code, s = go(tmp_path, robot, verdict_path=verdict(tmp_path, robot, **over))
    assert code == 2 and why in s["outcome"]
    assert not any("rosy_auto_update.py" in e or e.startswith(("POST /mode", "PUT")) for e in robot.log)


def test_missing_expected_reason_exits_1(tmp_path):
    code, s = go(tmp_path, FakeRobot())
    assert code == 1 and s["missing_expected"] == ["states:RECOVERING", "reasons:lane_bridge"]


def test_preflight_only_writes_frames_and_template_and_changes_nothing(tmp_path):
    robot = FakeRobot()
    code, s = go(tmp_path, robot, "--preflight-only")
    assert code == 0 and s["outcome"] == "preflight"
    template = json.loads((tmp_path / "ev" / "camera_verdict.json").read_text(encoding="utf-8"))
    assert template["robot_at_start"] is None and template["pose_at_capture"]["x"] == 0.0
    assert all(e.startswith(("GET", "ssh hostname", "ssh systemctl is-active")) for e in robot.log), robot.log


def test_dry_run_makes_no_calls(tmp_path, capsys):
    class Boom:
        def __getattr__(self, name):
            raise AssertionError(f"dry run touched {name}")
    code, s = go(tmp_path, Boom(), "--dry-run")
    assert code == 0 and s is None and not (tmp_path / "ev").exists()
    assert "bridge_enabled" in capsys.readouterr().out


def test_plan_refuses_speed_above_cap(tmp_path):
    plan = yaml.safe_load(PLAN.read_text(encoding="utf-8"))
    plan["overlay"]["line_follow"]["cruise_speed"] = 0.2
    p = tmp_path / "fast.yaml"
    p.write_text(yaml.safe_dump(plan), encoding="utf-8")
    with pytest.raises(SystemExit, match="cruise_speed"):
        run.load_plan(p)
