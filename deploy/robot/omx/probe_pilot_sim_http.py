"""One-shot host probe of an already running, isolated Pilot Gazebo container.

Consumes the container's one-time pairing code. Prints no code or token.

Modes:
  (default)  joint1 jog, a paced absolute gripper goal (readback + 0.02 rad), close then open,
             and an explicit cancel. Every goal must end SUCCEEDED with a matching readback.
  --stall    D-411 C blocking ROS-SIM gate for "holding": open, jog the arm to a top-down grasp
             pose, spawn a cube between the fingers, close on it and record the terminal status,
             result code, time to terminal, gripper readback and peak per-joint speed over the
             last 0.5 s; then three joint1 jogs while holding (each SUCCEEDED, state stays holding).

Usage: probe_pilot_sim_http.py [container|--inside] [--stall] [--cube-size M] [--grasp-z M] [--pace-margin F]
"""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4

REPO = Path(__file__).resolve().parents[3]
BASE = "http://127.0.0.1:8088/api/v1/sim/omx"
TERMINAL = {"SUCCEEDED", "REJECTED", "CANCELED", "UNKNOWN_HOLD"}
GRIPPER_MIN_S, GRIPPER_MAX_S = 0.2, 2.0      # OmxSimGripperGoal duration bounds
GRIPPER_READBACK_TOLERANCE = 0.05            # mimic readback error near closed is ~0.011 rad
GRIPPER_STILL_RAD, GRIPPER_STILL_S, GRIPPER_SETTLE_S = 0.002, 0.2, 1.5
# Same single retry as Pilot arm.js RETRYABLE: a new /joint_states between GET /state and POST.
RETRYABLE = ("joint_state_sequence_mismatch", "readback_not_recently_served")
WORLD = "omx_pilot_workcell"
CUBE = "rosy_probe_cube"


def request(path: str, *, method: str = "GET", token: str = "", body=None, base: str = BASE):
    data = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.load(response) if response.status != 204 else None
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"{path}: HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')}") from exc


def terminal_facts(goal: dict) -> dict:
    """ROS terminal status / result code as the SIM receipt reports them."""
    if goal["state"] == "SUCCEEDED":
        return {"status": 4, "result_code": 0}
    match = re.fullmatch(r"terminal_status_(-?\d+)_result_(-?\d+|None)", goal.get("reason", ""))
    if match:
        code = match.group(2)
        return {"status": int(match.group(1)), "result_code": None if code == "None" else int(code)}
    return {"status": None, "result_code": None}


def peak_speeds(samples: list[tuple[float, dict]], window_s: float = 0.5) -> dict[str, float]:
    """Largest |dq/dt| per joint between consecutive readbacks in the last ``window_s``."""
    if not samples:
        return {}
    end = samples[-1][0]
    recent = [sample for sample in samples if end - sample[0] <= window_s]
    peaks: dict[str, float] = {}
    for (t0, q0), (t1, q1) in zip(recent, recent[1:]):
        if t1 <= t0:
            continue
        for name in q1:
            if name in q0:
                peaks[name] = max(peaks.get(name, 0.0), abs(q1[name] - q0[name]) / (t1 - t0))
    return {name: round(value, 4) for name, value in peaks.items()}


class Probe:
    def __init__(self, token: str, seat: str, *, base: str = BASE, stop: threading.Event | None = None,
                 log=print, pace_margin: float = 0.9) -> None:
        if not 0 < pace_margin <= 1:
            raise ValueError("pace margin must be in (0, 1]")
        self.token, self.seat, self.base, self.log = token, seat, base, log
        self.pace_margin = pace_margin
        self.stop = stop or threading.Event()
        self.target = self.call("/target")
        items = {item["kind"]: item for item in (self.target.get("controls") or {}).get("items", [])}
        self.jog = items.get("joint_jog")
        self.gripper = items.get("gripper")

    def call(self, path: str, **kwargs):
        return request(path, token=self.token, base=self.base, **kwargs)

    def ready_state(self, timeout_s: float = 30.0) -> dict:
        until = time.monotonic() + timeout_s
        while time.monotonic() < until and not self.stop.is_set():
            current = self.call("/state")
            if current["ready"]:
                return current
            time.sleep(0.05)
        raise RuntimeError("owner did not return to ready between goals")

    def _post(self, path: str, fields: dict, current: dict) -> str:
        def post(state: dict) -> tuple[str, dict]:
            command_id = str(uuid4())
            return command_id, self.call(path, method="POST", body={
                "instance_id": state["instance_id"], "seat_id": self.seat, "request_id": command_id,
                **fields, "state_sequence": state["state_sequence"],
                "expires_at_ms": int(time.time() * 1000) + 5000})

        try:
            command_id, goal = post(current)
        except RuntimeError as exc:
            if not any(reason in str(exc) for reason in RETRYABLE):
                raise
            self.log(f"retry_after={next(reason for reason in RETRYABLE if reason in str(exc))}")
            command_id, goal = post(self.ready_state())
        if goal["state"] != "LOCAL_ACCEPTED":
            raise RuntimeError(f"{path} {fields}: local command was not accepted: {goal}")
        return command_id

    def follow(self, command_id: str, samples: list | None = None, timeout_s: float = 60.0) -> tuple[dict, float]:
        started = time.monotonic()
        while time.monotonic() - started < timeout_s and not self.stop.is_set():
            goal = self.call(f"/goals/{command_id}")
            if samples is not None:
                state = self.call("/state")
                samples.append((time.monotonic(), dict(state["positions"])))
            if goal["state"] in TERMINAL:
                return goal, time.monotonic() - started
            time.sleep(0.05)
        raise RuntimeError(f"goal {command_id} did not reach a terminal state")

    def settle_gripper(self) -> dict:
        """/state once the gripper readback is still (< 0.002 rad over 0.2 s), or after 1.5 s.

        The Gazebo gripper goal tolerance is 0.0, so a gripper goal can end SUCCEEDED before the
        fingers arrive (gate 2026-10-03: open read 0.027-0.056 rad short).
        """
        joint = self.gripper["joint"]
        samples: list[tuple[float, float]] = []
        started = time.monotonic()
        while True:
            state = self.call("/state")
            now = time.monotonic()
            position = state["positions"].get(joint)
            if position is not None:
                samples.append((now, position))
            recent = [value for at, value in samples if now - at <= GRIPPER_STILL_S]
            if (samples and now - samples[0][0] >= GRIPPER_STILL_S
                    and max(recent) - min(recent) < GRIPPER_STILL_RAD):
                return state
            if now - started >= GRIPPER_SETTLE_S:
                return state
            time.sleep(0.05)

    def run_jog(self, joint: str, delta: float, *, duration_s: float = 0.4, check: bool = True) -> dict:
        current = self.ready_state()
        before = current["positions"][joint]
        command_id = self._post("/goals", {"joint": joint, "delta_rad": delta, "duration_s": duration_s},
                                current)
        goal, _ = self.follow(command_id)
        after_state = self.call("/state")
        after = after_state["positions"].get(joint)
        if check:
            self.log(f"{joint}_goal={goal['state']} reason={goal.get('reason', '')} "
                     f"ros_id_present={bool(goal.get('ros_goal_id'))} before={before:.4f} after={after:.4f} "
                     f"owner={after_state['owner_state']}")
            moved = None if after is None else after - before
            if (goal["state"] != "SUCCEEDED" or moved is None or moved * delta <= 0
                    or abs(moved) < 0.005 or abs(moved - delta) > 0.01):
                raise RuntimeError(f"{joint} ROS action or independent readback did not meet probe")
        return {"goal": goal, "state": after_state}

    def gripper_goal(self, target: float, readback: float) -> tuple[float, float]:
        """One paced absolute goal toward ``target``: at most pace_margin x max_velocity, 0.2-2.0 s.

        Within reach the exact target is sent (so the caller can tell it arrived); a clipped
        intermediate position is rounded.
        """
        stroke_speed = abs(self.gripper["open"] - self.gripper["closed"]) / GRIPPER_MAX_S
        speed = float(self.gripper.get("max_velocity") or stroke_speed) * getattr(self, "pace_margin", 0.9)
        reach = speed * GRIPPER_MAX_S
        if abs(target - readback) <= reach:
            position = target
        else:
            position = round(readback + math.copysign(reach, target - readback), 4)
        duration = math.ceil(abs(position - readback) / speed * 100 - 1e-9) / 100
        return position, min(max(duration, GRIPPER_MIN_S), GRIPPER_MAX_S)

    def move_gripper(self, target: float, *, samples: list | None = None, attempts: int = 3) -> dict:
        joint = self.gripper["joint"]
        first = None
        for attempt in range(1, attempts + 1):
            current = self.ready_state()
            readback = current["positions"][joint]
            first = readback if first is None else first
            position, duration = self.gripper_goal(target, readback)
            command_id = self._post("/gripper", {"position": position, "duration_s": duration}, current)
            goal, elapsed = self.follow(command_id, samples)
            state = self.settle_gripper() if goal["state"] == "SUCCEEDED" else self.call("/state")
            # "before" is the readback before the FIRST goal of this move, not of the last attempt.
            result = {"goal": goal, "elapsed_s": round(elapsed, 3), "position": position, "duration_s": duration,
                      "before": first, "after": state["positions"].get(joint), "state": state,
                      "goals": attempt}
            if goal["state"] != "SUCCEEDED" or position == target:
                return result
        return result

    def check_gripper(self, label: str, result: dict, target: float, expect_state: str | None) -> None:
        goal, after, state = result["goal"], result["after"], result["state"]
        grip = state.get("gripper", {}).get("state")
        self.log(f"gripper_{label}={goal['state']} reason={goal.get('reason', '')} target={target:.4f} "
                 f"sent={result['position']:.4f}/{result['duration_s']}s before={result['before']:.4f} "
                 f"after={after:.4f} grip={grip}")
        if goal["state"] != "SUCCEEDED" or after is None or abs(after - target) > GRIPPER_READBACK_TOLERANCE:
            raise RuntimeError(f"gripper {label}: goal or readback did not meet probe")
        if abs(after - result["before"]) < 0.005:
            raise RuntimeError(f"gripper {label}: readback did not change")
        if expect_state is not None:
            settled = self.settled_gripper_state()
            if settled != expect_state:
                raise RuntimeError(f"gripper {label}: state {settled}, expected {expect_state}")

    def settled_gripper_state(self, timeout_s: float = 3.0) -> str | None:
        """The gripper state once the 0.5 s motion window has passed (moving -> settled)."""
        until = time.monotonic() + timeout_s
        grip = None
        while time.monotonic() < until:
            grip = self.call("/state").get("gripper", {}).get("state")
            if grip not in {None, "moving"}:
                return grip
            time.sleep(0.1)
        return grip

    def basic(self) -> None:
        self.run_jog("joint1", 0.02)
        if self.gripper is None:
            raise RuntimeError("target announces no gripper control (server before D-411 C)")
        joint = self.gripper["joint"]
        readback = self.ready_state()["positions"][joint]
        nudge = readback + 0.02
        self.check_gripper("nudge", self.move_gripper(nudge), nudge, None)
        closed, open_ = self.gripper["closed"], self.gripper["open"]
        self.check_gripper("close", self.move_gripper(closed), closed, "closed")
        self.check_gripper("open", self.move_gripper(open_), open_, "open")
        self.cancel_probe()

    def cancel_probe(self) -> None:
        current = self.ready_state()
        cancel_id = self._post("/goals", {"joint": "joint1", "delta_rad": 0.05, "duration_s": 1.0}, current)
        canceled = self.call(f"/goals/{cancel_id}/cancel?seat_id={self.seat}", method="POST")
        self.log(f"cancel_request={canceled['state']}")
        if canceled["state"] != "CANCEL_REQUESTED":
            raise RuntimeError("cancel request was not accepted")
        finish = time.monotonic() + 30
        while time.monotonic() < finish:
            canceled = self.call(f"/goals/{cancel_id}")
            if canceled["state"] in {"CANCELED", "UNKNOWN_HOLD"}:
                break
            time.sleep(0.2)
        self.log(f"cancel_terminal={canceled['state']} ros_id_present={bool(canceled.get('ros_goal_id'))}")
        if canceled["state"] != "CANCELED":
            raise RuntimeError("ROS cancel terminal readback was not observed")

    def jog_to(self, targets: dict[str, float], tolerance: float = 0.005) -> None:
        """Round-robin bounded jogs (one joint, <= max_step each) toward ``targets``: an
        approximately straight joint-space path, every goal SUCCEEDED."""
        step = float(self.jog["max_step_rad"])
        ranges = {joint["name"]: (joint["lower"], joint["upper"]) for joint in self.jog["joints"]}
        for name, value in targets.items():
            if not ranges[name][0] <= value <= ranges[name][1]:
                raise RuntimeError(f"grasp pose {name}={value:.3f} outside the offered range {ranges[name]}")
        for _ in range(400):
            positions = self.ready_state()["positions"]
            pending = {name: value - positions[name] for name, value in targets.items()
                       if abs(value - positions[name]) > tolerance}
            if not pending:
                return
            for name, error in pending.items():
                delta = math.copysign(min(abs(error), step), error)
                result = self.run_jog(name, delta, check=False)
                if result["goal"]["state"] != "SUCCEEDED":
                    raise RuntimeError(f"approach jog {name} ended {result['goal']}")
        raise RuntimeError("grasp pose not reached")

    def stall(self, spawn, *, cube_size: float, grasp_z: float, x: float = 0.18, y: float = 0.0) -> dict:
        sys.path[:0] = [str(REPO / "middleware/apps/device/omx/adapter"), str(REPO / "src/contracts/foundation")]
        from omx_adapter.kinematics import OmxKinematics, TopDownPose
        from omx_adapter.pose_plan import CellPlanningProfile

        kinematics = OmxKinematics.load()
        cell = CellPlanningProfile.load(REPO / "deploy/robot/omx/sim/cell_profile.yaml")
        solved = kinematics.solve_top_down(TopDownPose(x, y, grasp_z, 0.0), cell.ik_limits())
        if not solved.ok:
            raise RuntimeError(f"grasp pose IK failed: {solved.reason} {solved.detail}")
        open_, closed = self.gripper["open"], self.gripper["closed"]
        opened = self.move_gripper(open_)
        self.check_gripper("open", opened, open_, None)
        self.jog_to(dict(zip(("joint1", "joint2", "joint3", "joint4", "joint5"), solved.joints)))
        positions = self.ready_state()["positions"]
        tcp = kinematics.fk([positions[f"joint{i}"] for i in range(1, 6)])
        spawn(cube_size, tcp.x, tcp.y, cube_size / 2, tcp.yaw)
        time.sleep(1.0)                                    # let the cube settle on the ground
        samples: list = []
        # A paced stroke may need two goals (reach = pace x max_velocity x 2.0 s); the fingers stop on
        # the cube during one of them and the last one, aimed at closed, is the close that is judged.
        close = self.move_gripper(closed, samples=samples)
        facts = terminal_facts(close["goal"])
        report = {"terminal_state": close["goal"]["state"], "reason": close["goal"].get("reason", ""),
                  "status": facts["status"], "result_code": facts["result_code"],
                  "time_to_terminal_s": close["elapsed_s"], "sent": close["position"],
                  "duration_s": close["duration_s"], "gripper_readback": close["after"],
                  "peak_speed_last_0_5s": peak_speeds(samples), "cube_size_m": cube_size,
                  "grasp_z_m": grasp_z, "tcp": [round(tcp.x, 4), round(tcp.y, 4), round(tcp.z, 4)],
                  "open_readback": opened["after"], "pace_margin": self.pace_margin}
        report["close_goals"] = close["goals"]
        report["gripper_state"] = self.settled_gripper_state()
        report["hold_target"] = None
        report["holding_jogs"] = []
        if report["terminal_state"] == "SUCCEEDED" and report["gripper_state"] == "holding":
            # The runtime re-issues a holding close at stall + preload; wait for it before jogging.
            report["hold_target"] = self.ready_state()["gripper"].get("hold_target")
            for _ in range(3):
                result = self.run_jog("joint1", 0.05, check=False)
                result["state"] = self.settle_gripper()
                grip = self.settled_gripper_state()
                report["holding_jogs"].append({"state": result["goal"]["state"],
                                               "reason": result["goal"].get("reason", ""), "gripper_state": grip,
                                               "gripper_readback": result["state"]["positions"].get(
                                                   self.gripper["joint"]),
                                               "hold_target": result["state"].get("gripper", {}).get("hold_target")})
                if result["goal"]["state"] != "SUCCEEDED" or grip != "holding":
                    break
        # Follow-up (not gating yet): how far the held fingers opened over the jogs (+ = toward open).
        opening = math.copysign(1.0, open_ - closed)
        last = report["holding_jogs"][-1]["gripper_readback"] if report["holding_jogs"] else None
        report["holding_drift_rad"] = (None if last is None or report["gripper_readback"] is None
                                       else round((last - report["gripper_readback"]) * opening, 6))
        report["passed"] = (report["terminal_state"] == "SUCCEEDED" and report["gripper_state"] == "holding"
                            and len(report["holding_jogs"]) == 3
                            and all(jog["state"] == "SUCCEEDED" and jog["gripper_state"] == "holding"
                                    for jog in report["holding_jogs"]))
        self.log("stall_probe=" + json.dumps(report, sort_keys=True))
        return report


def gz_spawner(container: str):
    """Spawn/remove a dynamic cube through the Gazebo transport service (inside the container)."""
    # A non-login docker exec has no ROS/Gazebo environment (gz -> exit 127): source it first.
    prefix = ([] if container == "--inside" else ["docker", "exec", container]) + [
        "bash", "-c", 'source /opt/ros/jazzy/setup.bash; exec "$@"', "gz"]

    def gz(service: str, reqtype: str, req: str) -> None:
        subprocess.run([*prefix, "gz", "service", "-s", f"/world/{WORLD}/{service}", "--reqtype", reqtype,
                        "--reptype", "gz.msgs.Boolean", "--timeout", "3000", "--req", req],
                       check=True, capture_output=True, text=True)

    def spawn(size: float, x: float, y: float, z: float, yaw: float) -> None:
        mass = 0.03
        inertia = mass * size * size / 6
        sdf = (f"<sdf version='1.9'><model name='{CUBE}'><pose>{x} {y} {z} 0 0 {yaw}</pose><link name='link'>"
               f"<inertial><mass>{mass}</mass><inertia><ixx>{inertia}</ixx><iyy>{inertia}</iyy>"
               f"<izz>{inertia}</izz></inertia></inertial>"
               f"<collision name='c'><geometry><box><size>{size} {size} {size}</size></box></geometry>"
               f"<surface><friction><ode><mu>1.0</mu><mu2>1.0</mu2></ode></friction></surface></collision>"
               f"<visual name='v'><geometry><box><size>{size} {size} {size}</size></box></geometry></visual>"
               f"</link></model></sdf>")
        gz("create", "gz.msgs.EntityFactory", f'sdf: "{sdf}"')

    def remove() -> None:
        gz("remove", "gz.msgs.Entity", f'name: "{CUBE}" type: MODEL')

    return spawn, remove


def pairing_code(container: str, deadline: float) -> str:
    while time.monotonic() < deadline:
        if container == "--inside":
            path = Path("/run/rosy-omx-pilot/pairing-code")
            if path.is_file() and path.read_text(encoding="utf-8").strip():
                return path.read_text(encoding="utf-8").strip()
        else:
            result = subprocess.run(["docker", "exec", container, "cat", "/run/rosy-omx-pilot/pairing-code"],
                                    capture_output=True, text=True)
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        time.sleep(1)
    raise RuntimeError("pairing code did not appear")


def main(argv: list[str] | None = None, *, base: str = BASE, code: str | None = None, spawner=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("container", nargs="?", default="rosy-omx-pilot-sim")
    parser.add_argument("--inside", action="store_true", help="run inside the container (no docker exec)")
    parser.add_argument("--stall", action="store_true", help="D-411 C holding gate (spawns a cube)")
    parser.add_argument("--cube-size", type=float, default=0.025, help="cube edge, m (nominal; tune)")
    parser.add_argument("--grasp-z", type=float, default=0.015, help="TCP height for the grasp, m (nominal)")
    parser.add_argument("--pace-margin", type=float, default=0.9,
                        help="gripper goals move at this fraction of max_velocity (readback drift margin)")
    args = parser.parse_args(argv)
    if args.inside:
        args.container = "--inside"
    deadline = time.monotonic() + 1800
    code = code or pairing_code(args.container, deadline)
    while time.monotonic() < deadline:
        try:
            request("/target", base=base)
            break
        except (OSError, ConnectionError):
            time.sleep(1)
    else:
        raise RuntimeError("Pilot HTTP target did not become available")
    token = request("/pair", method="POST", body={"code": code}, base=base)["token"]
    code = None
    seat = request("/seat", method="POST", token=token, base=base)["seat_id"]
    stop = threading.Event()
    renew_errors = []

    def renew():
        while not stop.wait(0.8):
            try:
                request(f"/seat/{seat}", method="PUT", token=token, base=base)
            except Exception as exc:
                renew_errors.append(str(exc))
                if "HTTP 409" in str(exc) or "HTTP 401" in str(exc):
                    stop.set()

    thread = threading.Thread(target=renew, daemon=True)
    thread.start()
    remove = None
    try:
        while time.monotonic() < deadline and not stop.is_set():
            state = request("/state", token=token, base=base)
            if state["ready"]:
                break
            time.sleep(1)
        else:
            raise RuntimeError(f"SIM never ready: owner={state['owner_state']}, "
                               f"seq={state['state_sequence']}, age_ms={state['joint_age_ms']}, "
                               f"action_server_ready={state.get('action_server_ready')}, "
                               f"last_renew_error={renew_errors[-1] if renew_errors else 'none'}")
        probe = Probe(token, seat, base=base, stop=stop, pace_margin=args.pace_margin)
        if not args.stall:
            probe.basic()
            return 0
        if probe.gripper is None or probe.jog is None:
            raise RuntimeError("target must announce joint_jog and gripper controls")
        spawn, remove = spawner or gz_spawner(args.container)
        return 0 if probe.stall(spawn, cube_size=args.cube_size, grasp_z=args.grasp_z)["passed"] else 2
    finally:
        stop.set()
        thread.join(timeout=2)
        if remove is not None:
            try:
                remove()
            except Exception:
                pass
        try:
            request(f"/seat/{seat}", method="DELETE", token=token, base=base)
        except Exception:
            pass


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"probe failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
