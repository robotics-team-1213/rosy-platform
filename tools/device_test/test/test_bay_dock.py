"""bay_dock on a fake robot (no network, no SSH, virtual clock)."""
import importlib.util
import json
import math
import sys
from pathlib import Path

import pytest

_TOOL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_TOOL))
_spec = importlib.util.spec_from_file_location("device_test_bay_dock", _TOOL / "bay_dock.py")
bd = importlib.util.module_from_spec(_spec)
sys.modules["device_test_bay_dock"] = bd
_spec.loader.exec_module(bd)

ROBOT = "rosy-pinky-test"
VERDICT = {"bay_id": "C2", "judged_by": "agent", "in_bay_line": True, "rear_toward_bay": True, "cable_absent": True}


def obs(n=14, a=True, x=0.2, y=0.01, yaw=math.pi, **kw):
    rows = [{"visible": True, "x": x, "y": y, "yaw": yaw, "lateral_measured": a, **kw} for _ in range(n)]
    return rows


# --- pure ---------------------------------------------------------------------------------

def test_obs_errors_straight_back():
    along, lateral, heading = bd.obs_errors({"x": 0.3, "y": 0.0, "yaw": math.pi})
    assert along == pytest.approx(-0.3) and lateral == pytest.approx(0.0, abs=1e-9)
    assert heading == pytest.approx(0.0, abs=1e-9)
    _, lateral, _ = bd.obs_errors({"x": 0.0, "y": 0.1, "yaw": math.pi})
    assert lateral == pytest.approx(0.1, abs=1e-9)


def test_summarize_observations_rules():
    ok = bd.summarize_observations(obs() + obs(a=False, yaw=math.pi + 0.05))
    assert ok["ok"] and ok["bay_line"] == 14 and ok["aisle_line"] == 14 and ok["line_diff_deg"] < 10
    assert not bd.summarize_observations(obs(5))["ok"]                        # too few
    assert "aisle line" in bd.summarize_observations(obs(a=False))["reason"]    # X only
    far = bd.summarize_observations(obs() + obs(a=False, yaw=math.pi - 0.3))
    assert not far["ok"] and "differ" in far["reason"]
    assert not bd.summarize_observations([{"visible": False}] * 20)["ok"]
    wrapped = bd.summarize_observations(obs(yaw=math.pi - 0.01)[:7] + obs(yaw=-math.pi + 0.01)[:7])
    assert abs(abs(wrapped["median"]["yaw"]) - math.pi) < 0.02                   # median across +-pi


def test_dock_pose_composes():
    p = bd.dock_pose({"x": 1.0, "y": 2.0, "yaw": math.pi / 2}, {"x": 0.3, "y": 0.1, "yaw": math.pi / 2})
    assert (p["x"], p["y"]) == pytest.approx((0.9, 2.3)) and abs(p["yaw"]) == pytest.approx(math.pi)


def test_retry_and_approval_rules():
    assert bd.trial_should_retry({"state": "invalid", "reason": "measured speed exceeds the commissioning envelope"}, None)
    assert not bd.trial_should_retry({}, {"code": "CLEARANCE_TOO_SMALL"})
    assert not bd.trial_should_retry({"reason": "WHEELS_NOT_MOVING_BODY"}, None)
    assert bd.approval_needed(None, "r1") and bd.approval_needed({"valid": False}, "r1")
    assert bd.approval_needed({"valid": True, "measured_release_id": "r0"}, "r1")
    assert not bd.approval_needed({"valid": True, "measured_release_id": "r1"}, "r1")


@pytest.mark.parametrize("patch", [{"bay_id": ""}, {"in_bay_line": False}, {"rear_toward_bay": None},
                                   {"cable_absent": False}, {"judged_by": ""}])
def test_verdict_fails_closed(patch):
    with pytest.raises(ValueError):
        bd.check_bay_verdict({**VERDICT, **patch})
    assert bd.check_bay_verdict(VERDICT)


# --- fake robot ---------------------------------------------------------------------------

class Core:
    def __init__(self, r):
        self.r = r

    def call(self, method, path, body=None, raw=False, timeout=3.0, attempts=2):
        r = self.r
        r.log.append(f"{method} {path}")
        if r.on_call:
            r.on_call(method, path)
        if r.active and r.now() - r.last_hold > 0.4:      # hold gap: CORE ends the trial
            r.finish_trial(stopped=False)
        key = (method, path)
        if key == ("GET", "/system/info"):
            return 200, {"release_id": r.release}
        if key == ("GET", "/robot/state"):
            loc = {"state": "LOCALIZED" if r.localized else "UNKNOWN"}
            return 200, {"battery": {"percent": 80}, "battery_status": {"charging": r.charging}, "safety": {"estop": False},
                         "pose": dict(r.pose), "localization": loc}
        if key == ("GET", "/line-follow"):
            return 200, {"mode": "OFF"}
        if key == ("GET", "/sensors/lidar"):
            ranges = [1.0] * 360
            if r.front_gap is not None:
                ranges[0] = ranges[359] = r.front_gap                      # LiDAR 0 deg is the rear: index 0/359 are the nose
            return 200, {"ranges": ranges, "angle_min": -math.pi, "angle_increment": 2 * math.pi / 360, "range_min": 0.05}
        if key == ("GET", "/navigation/approval"):
            return 200, {"phase": r.phase, "runtime_mode": "motor", "reason": "", "approval": r.approval,
                         "os_update_stops_navigation": r.os_stops,
                         "trials": [dict(t) for t in r.rows], "trial": {"active": r.active, "last": r.last}}
        if key == ("POST", "/navigation/approval/begin"):
            if r.held:
                return 409, {"error": "an update hold is on this robot: release it before measuring"}
            r.events.append("begin")
            r.phase = "MEASURING"
            return 200, {}
        if key == ("POST", "/navigation/approval/cancel"):
            r.phase = "IDLE"
            return 200, {}
        if key == ("POST", "/navigation/approval/seal"):
            r.phase, r.approval = "IDLE", {"valid": True, "measured_release_id": r.release}
            r.events.append("seal")
            return 200, {}
        if key == ("POST", "/navigation/approval/navigation-start"):
            r.localized = r.localize_ok
            return 200, {}
        if key == ("POST", "/navigation/approval/trial/start"):
            r.starts.append((body["direction"], body["stop_cause"]))
            if r.fatal:
                return 409, {"error": {"code": r.fatal}}
            r.active, r.last_hold = (body["direction"], body["stop_cause"]), r.now()
            return 200, {}
        if key == ("POST", "/navigation/approval/trial/hold"):
            r.last_hold = r.now()
            return 200, {"accepted": True}
        if key == ("POST", "/navigation/approval/trial/stop"):
            r.finish_trial(stopped=True)
            return 200, {}
        if key == ("GET", "/docking/types"):
            return 200, {"types": []}
        if key == ("POST", "/docking/types") or key == ("POST", "/docking/docks"):
            r.registered.append((path, body))
            return 201, {}
        if method == "DELETE":
            return 404, {}
        if key == ("POST", "/docking/dock"):
            r.docking, r.dock_t = True, r.now()
            return 200, {}
        if key == ("GET", "/docking/status"):
            if r.dock_never_ends:
                return 200, {"state": "DOCKING", "phase": "APPROACH"}
            if r.now() - r.dock_t < 3:
                return 200, {"state": "DOCKING", "phase": "APPROACH"}
            return 200, {"state": r.dock_end, "phase": "DONE", "error": None}
        if key == ("POST", "/teleop"):
            r.teleops.append(body["linear"])
            r.pose["x"] += body["linear"] * 0.2                           # the loop sleeps 0.2 s per step
            return 200, {}
        if key in (("POST", "/docking/cancel"), ("POST", "/mode")):
            return 200, {}
        raise AssertionError(f"unexpected call {method} {path}")


class Robot:
    def __init__(self, **kw):
        self.t, self.log, self.on_call = 1000.0, [], None
        self.release, self.charging, self.localized, self.localize_ok = "rel2", False, False, True
        self.phase, self.approval = "IDLE", {"valid": False, "measured_release_id": None}
        self.rows = [{"direction": d, "stop_cause": c, "state": "missing"} for d, c in bd.TRIALS]
        self.active = self.last = None
        self.last_hold, self.starts, self.registered = 0.0, [], []
        self.envelope_fails, self.fatal, self.obs = 0, None, obs()
        self.pose, self.front_gap, self.os_stops, self.timer = {"x": 1.0, "y": 2.0, "yaw": 0.0}, None, False, True
        self.events, self.cmds, self.teleops, self.timer_stop_rc = [], [], [], 0
        self.held, self.docking, self.dock_t, self.dock_end, self.dock_never_ends = False, False, 0.0, "DOCKED", False
        self.__dict__.update(kw)
        self.core = Core(self)

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s

    def overhead(self):
        return None

    def finish_trial(self, stopped):
        d, c = self.active
        self.active = None
        row = next(t for t in self.rows if (t["direction"], t["stop_cause"]) == (d, c))
        if self.envelope_fails > 0:
            self.envelope_fails -= 1
            row.update(state="invalid", reason="measured speed exceeds the commissioning envelope")
            self.last = {"state": "recorded"}
        else:
            row["state"] = "valid"
            self.last = {"state": "recorded"}

    def ssh(self, command, stdin=b""):
        self.log.append("ssh " + command.split()[0] if command.split() else "ssh")
        self.cmds.append(command)
        if command == "systemctl is-active rosy-os-update.timer":
            return 0, (b"active\n" if self.timer else b"inactive\n")
        if command == "sudo -n systemctl stop rosy-os-update.timer":
            self.timer = self.timer and self.timer_stop_rc != 0
            return self.timer_stop_rc, b""
        if command == "sudo -n systemctl start rosy-os-update.timer":
            self.timer = True
            return 0, b""
        if command == "hostname":
            return 0, (ROBOT + "\n").encode()
        if "ros2 topic echo" in command:
            return 0, "".join(json.dumps(json.dumps(o)) + "\n---\n" for o in self.obs).encode()
        if " hold " in command:
            self.held = True
            self.events.append("hold")
            return 0, b""
        if "release-hold" in command:
            self.held = False
            return 0, b""
        if "precheck" in command:
            return 0, b"hold by agent-device-test: reason\n" if self.held else b""
        raise AssertionError(command)


def run(tmp_path, robot, verdict=VERDICT, **kw):
    vp = tmp_path / "verdict.json"
    vp.write_text(json.dumps(verdict), encoding="utf-8")
    argv = ["--robot", ROBOT, "--insecure", "--token-file", "x", "--peer-check-ok", "ListAgents: none", "--bay-verdict",
            str(vp), "--dock-id", "bay_c2", "--evidence-dir", str(tmp_path / "ev"), "--summary-dir", str(tmp_path / "sum"),
            *kw.get("extra", [])]
    code = bd.main(argv, robot=robot)
    return code, json.loads((tmp_path / "ev" / "summary.json").read_text(encoding="utf-8"))


def calls(robot, prefix):
    return [c for c in robot.log if c.startswith(prefix)]


def cleaned(robot):
    assert robot.log[-1] != "x" and "POST /mode" in robot.log and not robot.held       # IDLE + hold released
    assert calls(robot, "POST /teleop")


# --- stages -------------------------------------------------------------------------------

def test_happy_path_orders_steps_and_registers(tmp_path):
    r = Robot()
    code, s = run(tmp_path, r)
    assert code == 0 and s["outcome"] == "completed (DOCKED)"
    assert r.starts == list(bd.TRIALS)
    order = [c for c in r.log if c in ("POST /navigation/approval/begin", "POST /navigation/approval/seal",
                                       "POST /navigation/approval/navigation-start", "POST /docking/docks", "POST /docking/dock")]
    assert order == ["POST /navigation/approval/begin", "POST /navigation/approval/seal",
                     "POST /navigation/approval/navigation-start", "POST /docking/docks", "POST /docking/dock"]
    path, body = r.registered[-1]
    assert body["id"] == "bay_c2" and body["type"] == "bay_line_c"
    assert body["x"] == pytest.approx(1.2, abs=0.01) and body["y"] == pytest.approx(2.01, abs=0.01)   # pose + obs at yaw 0
    assert [p for p, _ in r.registered][0] == "/docking/types"
    assert not r.held and "POST /mode" in r.log and "POST /docking/cancel" not in r.log
    assert s["bay_dock"]["final"] == "DOCKED" and s["release_id"] == "rel2"
    assert [t["state"] for t in s["trials"]] == ["valid"] * 5 and s["trials"][0]["before"]["lidar"]


def test_valid_approval_skips_measuring(tmp_path):
    r = Robot(approval={"valid": True, "measured_release_id": "rel2"})
    code, s = run(tmp_path, r)
    assert code == 0 and not r.starts and "POST /navigation/approval/begin" not in r.log
    assert s["approval"]["refreshed"] is False


def test_envelope_failure_retries_then_passes(tmp_path):
    r = Robot(envelope_fails=2)
    code, s = run(tmp_path, r)
    assert code == 0 and len(r.starts) == 7 and r.starts[:3] == [("forward", "button_release")] * 3


def test_command_loss_ends_by_silence(tmp_path):
    r = Robot()
    run(tmp_path, r)
    i = r.log.index("POST /navigation/approval/trial/start", r.log.index("POST /navigation/approval/trial/start") + 1)
    assert "POST /navigation/approval/trial/stop" not in r.log[i:r.log.index("POST /navigation/approval/trial/start", i + 1)]


def test_fatal_trial_stops_and_cancels_approval(tmp_path):
    r = Robot(fatal="CLEARANCE_TOO_SMALL")
    code, s = run(tmp_path, r)
    assert code == 2 and "aborted at refresh_approval" in s["outcome"] and len(r.starts) == 1
    assert "POST /navigation/approval/cancel" in r.log and "POST /navigation/approval/navigation-start" not in r.log
    cleaned(r)


def test_no_observations_refuses_before_dock(tmp_path):
    r = Robot(obs=[], approval={"valid": True, "measured_release_id": "rel2"})
    code, s = run(tmp_path, r)
    assert code == 2 and "aborted at line_view" in s["outcome"]
    assert "POST /docking/dock" not in r.log and "POST /docking/docks" not in r.log
    cleaned(r)


def test_not_localized_aborts(tmp_path):
    r = Robot(localize_ok=False, approval={"valid": True, "measured_release_id": "rel2"})
    code, s = run(tmp_path, r)
    assert code == 2 and "aborted at navigation_start" in s["outcome"] and "LOCALIZED" in s["outcome"]
    cleaned(r)


def test_dock_failed_cancels(tmp_path):
    r = Robot(dock_end="DOCK_FAILED", approval={"valid": True, "measured_release_id": "rel2"})
    code, s = run(tmp_path, r)
    assert code == 1 and s["outcome"] == "completed (DOCK_FAILED)" and "POST /docking/cancel" in r.log
    cleaned(r)


def test_dock_timeout_cancels(tmp_path):
    r = Robot(dock_never_ends=True, approval={"valid": True, "measured_release_id": "rel2"})
    code, s = run(tmp_path, r)
    assert code == 2 and "aborted at dock" in s["outcome"] and "POST /docking/cancel" in r.log
    cleaned(r)


def test_exception_during_dock_cancels_and_idles(tmp_path):
    def boom(method, path):
        if (method, path) == ("GET", "/docking/status"):
            raise KeyboardInterrupt
    r = Robot(on_call=boom, approval={"valid": True, "measured_release_id": "rel2"})
    code, s = run(tmp_path, r)
    assert code == 2 and "POST /docking/cancel" in r.log
    cleaned(r)


@pytest.mark.parametrize("verdict", [{**VERDICT, "in_bay_line": False}, {**VERDICT, "bay_id": ""}])
def test_bad_verdict_moves_nothing(tmp_path, verdict):
    r = Robot()
    code, s = run(tmp_path, r, verdict=verdict)
    assert code == 2 and "aborted at preflight" in s["outcome"]
    assert not r.starts and not r.held and not any(c.startswith("POST") for c in r.log)


def test_charging_refused_before_hold(tmp_path):
    r = Robot(charging=True)
    code, s = run(tmp_path, r)
    assert code == 2 and not r.held and not any(c.startswith("POST") for c in r.log)


def test_remove_dock_option(tmp_path):
    r = Robot(approval={"valid": True, "measured_release_id": "rel2"})
    run(tmp_path, r, extra=["--remove-dock"])
    assert r.log.count("DELETE /docking/docks/bay_c2") == 2


# --- 2026-11-19 field defects --------------------------------------------------------------------

def test_hold_comes_after_the_approval_and_a_hold_present_at_start_is_refused(tmp_path):
    r = Robot()
    code, _ = run(tmp_path, r)
    assert code == 0 and r.events == ["begin", "seal", "hold"]          # the approval refuses to measure under a hold
    r = Robot(held=True)
    (tmp_path / "again").mkdir()
    code, s = run(tmp_path / "again", r)
    assert code == 2 and "already on the robot" in s["outcome"] and not any(c.startswith("POST") for c in r.log)


def test_os_update_timer_stopped_after_the_hold_and_restored(tmp_path):
    r = Robot(os_stops=True, approval={"valid": True, "measured_release_id": "rel2"})
    code, s = run(tmp_path, r)
    assert code == 0 and r.timer
    stop, start = ("sudo -n systemctl stop rosy-os-update.timer", "sudo -n systemctl start rosy-os-update.timer")
    assert r.cmds.index(stop) < r.cmds.index(start) and r.events == ["hold"]
    assert not r.held and "POST /mode" in r.log


def test_os_update_timer_left_alone_when_it_does_not_stop_navigation(tmp_path):
    r = Robot(approval={"valid": True, "measured_release_id": "rel2"})
    run(tmp_path, r)
    assert not [c for c in r.cmds if "systemctl" in c]


def test_os_update_timer_restored_after_an_abort(tmp_path):
    r = Robot(os_stops=True, dock_never_ends=True, approval={"valid": True, "measured_release_id": "rel2"})
    code, _ = run(tmp_path, r)
    assert code == 2 and r.timer and "POST /docking/cancel" in r.log
    cleaned(r)


def test_os_update_timer_stop_failure_aborts_and_restores(tmp_path):
    r = Robot(os_stops=True, timer_stop_rc=1, approval={"valid": True, "measured_release_id": "rel2"})
    code, s = run(tmp_path, r)
    assert code == 2 and "aborted at os_update_guard" in s["outcome"] and r.timer and "POST /navigation/approval/navigation-start" not in r.log
    cleaned(r)


def test_observation_read_loads_the_runtime_environment(tmp_path):
    r = Robot(approval={"valid": True, "measured_release_id": "rel2"})
    run(tmp_path, r)
    cmd = next(c for c in r.cmds if "ros2 topic echo" in c)
    assert cmd.startswith("sudo -n bash -c '") and "/etc/rosy/runtime.env" in cmd and "jazzy" in cmd and cmd.endswith("'")


def test_a_missing_lateral_measured_key_reads_as_measured():
    rows = [{"visible": True, "x": 0.2, "y": 0.01, "yaw": math.pi} for _ in range(14)]
    s = bd.summarize_observations(rows)
    assert s["ok"] and s["bay_line"] == 14 and s["aisle_line"] == 0


def test_start_at_the_stop_face_drives_out_then_docks(tmp_path):
    r = Robot(obs=obs(x=-0.08, yaw=math.pi), approval={"valid": True, "measured_release_id": "rel2"})
    code, s = run(tmp_path, r)
    assert code == 0 and r.teleops[0] == 0.05 and set(r.teleops) == {0.05, 0.0}
    assert r.pose["x"] - 1.0 >= 0.26 - 1e-9                              # staging 0.32 - along 0.08 + 0.02
    assert r.log.index("POST /docking/docks") < r.log.index("POST /teleop") < r.log.index("POST /docking/dock")


def test_leave_bay_refuses_with_something_in_front(tmp_path):
    r = Robot(obs=obs(x=-0.08, yaw=math.pi), front_gap=0.10, approval={"valid": True, "measured_release_id": "rel2"})
    code, s = run(tmp_path, r)
    assert code == 2 and "aborted at leave_bay" in s["outcome"] and "in front" in s["outcome"]
    assert 0.05 not in r.teleops and "POST /docking/dock" not in r.log
    cleaned(r)


def test_no_exit_when_the_bay_line_is_far(tmp_path):
    r = Robot(approval={"valid": True, "measured_release_id": "rel2"})        # default obs: along -0.2, nowhere near the face
    run(tmp_path, r)
    assert not r.teleops[:-1] and r.pose["x"] == 1.0


def test_cycles_leave_and_dock_again(tmp_path):
    r = Robot(approval={"valid": True, "measured_release_id": "rel2"})
    code, s = run(tmp_path, r, extra=["--cycles", "2"])
    assert code == 0 and [c["final"] for c in s["cycles"]] == ["DOCKED", "DOCKED"] and [c["cycle"] for c in s["cycles"]] == [1, 2]
    assert r.log.count("POST /docking/dock") == 2 and r.pose["x"] - 1.0 >= 0.29 - 1e-9     # 0.32 - 0.05 + 0.02
    assert r.log.index("POST /teleop") > r.log.index("POST /docking/dock")                 # the exit is between the docks


def test_cycles_stop_at_the_first_failure(tmp_path):
    r = Robot(dock_end="DOCK_FAILED", approval={"valid": True, "measured_release_id": "rel2"})
    code, s = run(tmp_path, r, extra=["--cycles", "3"])
    assert code == 1 and len(s["cycles"]) == 1 and r.log.count("POST /docking/dock") == 1


def test_cycles_must_be_positive(tmp_path):
    with pytest.raises(SystemExit):
        run(tmp_path, Robot(), extra=["--cycles", "0"])


def test_address_host_keeps_the_robot_name_as_the_tls_name(tmp_path):
    import argparse
    live = importlib.import_module("live_transport")
    token = tmp_path / "t"
    token.write_text("x", encoding="utf-8")
    args = argparse.Namespace(host="192.0.2.7", robot=ROBOT, token_file=str(token), port=8080, ca_file=None, insecure=True,
                              site_url=None, site_ca_file=None, site_insecure=False, overhead_source=None, tls_host=f"{ROBOT}.local")
    assert live.Live(args).core.tls_host == f"{ROBOT}.local"
    args.tls_host = None
    assert live.Live(args).core.tls_host is None                         # unchanged without --tls-host or --ca-file
