#!/usr/bin/env python3
"""Run the 12 junction scenarios in headless Gazebo and score them.

Usage (WSL, sourced overlay):
  python3 junction_harness.py --mode centre --out /rosy_mapv2_ws/evidence/junctions_<id> \
      --graph src/runtime/control/map/map_v2_fleet/lane_graph.yaml [--only NW]
Per scenario: launch map_v2_fleet_lane at the scenario start, wait for it to
become ready (CORE's API answering and both /odom and /line/observation
flowing) up to BOOT_S, enable CAMERA_LINE through CORE's API, record /odom
(Gazebo ground truth) until the end point or TIMEOUT_S, then stop, score,
and write results.json plus the overlay MP4 (debug_overlay:=true). A
scenario that never boots, never reaches its end point, or raises is still
recorded with a `reason` and does not abort the remaining scenarios.

To re-score already-recorded evidence against a fixed junction_score.py
without re-running Gazebo, use junction_score.py's own `--graph --results
--tracks` CLI (its rescore()/`_rescore_cli`), not this file.

ROS imports (rclpy, nav_msgs, std_msgs) are deferred into wait_ready() and
run_one() so this module and its scenario/scoring logic can be imported and
exercised on a host without ROS 2 installed (e.g. the Windows dev host);
only actually running a scenario requires rclpy.
"""

import argparse
import json
import math
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import junction_score  # noqa: E402

#: Scenario budget in SIMULATION seconds (odom header stamps). A loaded host
#: slows Gazebo, so a wall-clock budget turned slow-but-correct runs into
#: timeouts (route_b smoke, 2026-09-23: 1.1 Hz camera at load 22 on 8 cores).
TIMEOUT_S = 90.0
#: Wall-clock backstop so a stalled simulation cannot hang the run.
WALL_CAP_S = 600.0
#: Upper bound on the readiness poll; a real boot is much faster, but this
#: is the point at which the scenario is given up on as "never came up".
#: 45 s lost 9 of 36 scenarios in r9-r11 (2026-09-24): under host load CORE
#: was still importing pydantic when the poll gave up. Boot time is not a
#: driving criterion, so the bound only has to rule out a launch that hangs.
BOOT_S = 150.0
READY_POLL_S = 0.5
STATUS_API = "http://127.0.0.1:8080/api/v1/line-follow"
MODE_API = "http://127.0.0.1:8080/api/v1/line-follow/mode"
VIEWER = {"Authorization": "Bearer rosy-dev-viewer"}
OPERATOR = {"Authorization": "Bearer rosy-dev-operator", "Content-Type": "application/json"}
SET_MODE_RETRIES = 5
SET_MODE_RETRY_DELAY_S = 1.0
# 409 DOCKING_ACTIVE: docking still holds the robot for a moment (an undock's
# last tick releases the mode). Short, and explicit — see set_mode.
SET_MODE_BUSY_DELAY_S = 0.2
#: How long to let the launch group exit cleanly after SIGINT before SIGKILL.
LAUNCH_STOP_TIMEOUT_S = 15.0
#: How long to let the recorder exit after a SIGINT before killing it. Longer
#: than a plain terminate: record_debug.py finalises overlay.mp4's moov atom
#: in its `finally` block, which needs a live process to run in.
RECORDER_STOP_TIMEOUT_S = 15.0
#: Gazebo/launch processes from this scenario's own ROS_DOMAIN_ID only, as
#: read from /proc/<pid>/environ -- narrower than a bare pattern match,
#: which would kill an unrelated Gazebo/domain/user's run on the same box.
LEFTOVER_PATTERNS = ("gz sim .*map_v2_fleet.world", "map_v2_fleet_lane.launch.py")
#: A realtime-clock step larger than this inside one scenario is logged. WSL
#: can step the clock by minutes (r4 scenario 09, 2026-09-23: -945 s on an
#: hv_utils TimeSync re-init); such a result is infrastructure evidence, not
#: follower evidence, and wants a rerun.
CLOCK_STEP_TOLERANCE_S = 1.0
#: How often (wall seconds) CORE's line-follow status is sampled into
#: core_status.jsonl, so a stop shows CORE's own state and reason.
STATUS_SAMPLE_S = 1.0


def _api_ok(url, headers):
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


def _api_get(url, headers):
    """GET a JSON document, or None on any transport or decode failure."""
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=0.2) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, OSError, ValueError):
        return None


def wall_clock_offset():
    """Realtime minus monotonic: constant unless the wall clock is stepped."""
    return time.time() - time.monotonic()


def clock_step_s(start_offset, end_offset):
    """How far the wall clock was stepped between two wall_clock_offset()s."""
    return round(end_offset - start_offset, 1)


def _error_code(exc):
    """The ERR-101 `error.code` of an HTTP error response, or None."""
    try:
        return json.loads(exc.read() or b"null")["error"]["code"]
    except (ValueError, TypeError, KeyError, OSError):
        return None


def set_mode(mode):
    """PUT the CAMERA_LINE/OFF mode. Two refusals are retried, each on
    purpose and with its own delay:

    * a refused connection — the API server may not be listening yet on the
      very first calls after boot (SET_MODE_RETRY_DELAY_S);
    * HTTP 409 DOCKING_ACTIVE — docking still holds the robot for a moment
      right after an undock (SET_MODE_BUSY_DELAY_S).

    Any other HTTP error is a real refusal and is raised at once. (HTTPError
    subclasses URLError, so it is caught first — the old single `except`
    retried every HTTP refusal by accident.)"""
    req_body = json.dumps({"mode": mode}).encode()
    last_error = None
    for attempt in range(SET_MODE_RETRIES):
        try:
            req = urllib.request.Request(MODE_API, data=req_body, method="PUT", headers=OPERATOR)
            with urllib.request.urlopen(req, timeout=5) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            if exc.code != 409 or _error_code(exc) != "DOCKING_ACTIVE":
                raise
            last_error, delay = exc, SET_MODE_BUSY_DELAY_S
        except (urllib.error.URLError, OSError) as exc:
            last_error, delay = exc, SET_MODE_RETRY_DELAY_S
        if attempt < SET_MODE_RETRIES - 1:
            time.sleep(delay)
    raise last_error


def wait_ready(node, rclpy_module, deadline):
    """Poll CORE's status API and spin `node` until an /odom message and a
    /line/observation message have both arrived, or `deadline` passes.
    Returns True once ready, False on timeout (a "boot_timeout")."""
    seen = {"odom": False, "line": False}

    def mark(key):
        def _cb(_msg):
            seen[key] = True
        return _cb

    from nav_msgs.msg import Odometry
    from rclpy.qos import qos_profile_sensor_data
    from std_msgs.msg import String

    node.create_subscription(Odometry, "odom", mark("odom"), qos_profile_sensor_data)
    node.create_subscription(String, "line/observation", mark("line"), 10)

    next_poll = 0.0
    api_ready = False
    while time.monotonic() < deadline:
        rclpy_module.spin_once(node, timeout_sec=0.1)
        now = time.monotonic()
        if not api_ready and now >= next_poll:
            api_ready = _api_ok(STATUS_API, VIEWER)
            next_poll = now + READY_POLL_S
        if api_ready and seen["odom"] and seen["line"]:
            return True
    return False


def _append_log(out_dir, lines):
    if out_dir is None or not lines:
        return
    try:
        with (out_dir / "launch.log").open("a") as fh:
            fh.write("\n".join(lines) + "\n")
    except OSError:
        pass


def _kill_leftover_processes(out_dir, domain):
    """Best-effort cleanup of any process from THIS scenario's launch group
    that survived the group kill (e.g. a grandchild that detached into its
    own session). Scoped to processes whose environment carries this
    scenario's ROS_DOMAIN_ID (via /proc/<pid>/environ), so a different
    domain, a different user, or a developer's own Gazebo run elsewhere on
    the box is never touched. /proc is Linux-only; this harness only ever
    runs under WSL/Linux, but skips gracefully elsewhere. Always logs what
    it found (or didn't) so a leak is visible in launch.log."""
    if not sys.platform.startswith("linux"):
        _append_log(out_dir, ["leftover-check: skipped (not Linux)"])
        return
    needle = f"ROS_DOMAIN_ID={domain}".encode()
    log_lines = []
    for pattern in LEFTOVER_PATTERNS:
        try:
            found = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True)
        except FileNotFoundError:
            log_lines.append(f"leftover-check: pgrep unavailable, skipped {pattern!r}")
            continue
        matched = []
        for pid in found.stdout.split():
            try:
                environ = Path(f"/proc/{pid}/environ").read_bytes()
            except OSError:
                continue
            if needle in environ.split(b"\0"):
                matched.append(pid)
        if matched:
            log_lines.append(f"leftover: killing {pattern!r} pids={matched} (domain {domain})")
            subprocess.run(["kill", "-9", *matched])
        else:
            log_lines.append(f"leftover: none for {pattern!r} in domain {domain}")
    _append_log(out_dir, log_lines)


def run_one(scenario, graph, mode, out_dir, domain):
    """ROS-only: launches Gazebo, records ground-truth odometry, scores it.

    Always returns a result dict with at least `pass` and `reason`; never
    raises (`main` relies on that so one bad scenario does not abort the
    rest of the run). Every cleanup step below is isolated in its own
    try/except so one failing step (e.g. a process already gone) does not
    skip the others.
    """
    x, y, yaw = scenario["start"]
    env = dict(os.environ, ROS_DOMAIN_ID=str(domain))
    launch = None
    recorder = None
    rclpy_started = False
    node = None
    rclpy_module = None
    log_file = None
    try:
        log_file = (out_dir / "launch.log").open("w")
        try:
            # route_a/route_b/route_ab only: a YAML flow-list string, which the launch
            # file's ParameterValue(value_type=List[str]/List[float]) parses
            # into the node's declared route/route_start array parameters.
            route_args = [
                f"route:=[{scenario['into']}, {scenario['out']}]",
                f"route_start:=[{x}, {y}, {yaw}]",
            ] if mode in ("route_a", "route_b", "route_ab") else []
            launch = subprocess.Popen(
                ["ros2", "launch", "gz_sim", "map_v2_fleet_lane.launch.py",
                 f"spawn_x:={x}", f"spawn_y:={y}", f"spawn_yaw:={yaw}",
                 f"camera_lane_mode:={mode}", "debug_overlay:=true"] + route_args,
                env=env, stdout=log_file, stderr=subprocess.STDOUT, start_new_session=True)
        except OSError as exc:
            return {"pass": False, "reason": f"error:{type(exc).__name__}"}

        import rclpy
        from nav_msgs.msg import Odometry
        from rclpy.node import Node
        from rclpy.qos import qos_profile_sensor_data
        rclpy_module = rclpy

        os.environ["ROS_DOMAIN_ID"] = str(domain)
        rclpy.init()
        rclpy_started = True
        node = Node("junction_harness")

        boot_deadline = time.monotonic() + BOOT_S
        if not wait_ready(node, rclpy, boot_deadline):
            return {"pass": False, "reason": "boot_timeout"}

        recorder = subprocess.Popen(
            ["python3", str(Path(__file__).with_name("record_debug.py")), "--out", str(out_dir),
             "--seconds", str(WALL_CAP_S + 5)], env=env)

        track, stamps = [], []

        def on_odom(m):
            track.append((m.pose.pose.position.x, m.pose.pose.position.y))
            stamps.append(m.header.stamp.sec + m.header.stamp.nanosec * 1e-9)

        node.create_subscription(Odometry, "odom", on_odom, qos_profile_sensor_data)
        set_mode("CAMERA_LINE")
        end = junction_score.directed_points(graph, scenario["out"])
        s = junction_score._arc_length(end)
        end_point = end[int(s.searchsorted(junction_score.END_AFTER_M))]
        clock_offset = wall_clock_offset()
        wall_start = time.monotonic()
        wall_deadline = wall_start + WALL_CAP_S
        sim_start = None
        reason = "wall_cap"
        status_log = (out_dir / "core_status.jsonl").open("w")
        next_status = wall_start
        while time.monotonic() < wall_deadline:
            rclpy.spin_once(node, timeout_sec=0.1)
            if time.monotonic() >= next_status:
                next_status = time.monotonic() + STATUS_SAMPLE_S
                status = _api_get(STATUS_API, VIEWER)
                status_log.write(json.dumps(
                    {"sim": stamps[-1] if stamps else None, "status": status}) + "\n")
            if stamps and sim_start is None:
                sim_start = stamps[-1]
            if track and math.dist(track[-1], end_point) < 0.05:
                reason = "reached"
                break
            if sim_start is not None and stamps[-1] - sim_start >= TIMEOUT_S:
                reason = "timeout"
                break
        status_log.close()
        wall_elapsed = time.monotonic() - wall_start
        step = clock_step_s(clock_offset, wall_clock_offset())
        sim_elapsed = (stamps[-1] - sim_start) if sim_start is not None else 0.0
        set_mode("OFF")
        result = junction_score.score(graph, scenario, track or [scenario["start"][:2]])
        result["reason"] = reason
        result["sim_s"] = round(sim_elapsed, 2)
        result["wall_s"] = round(wall_elapsed, 2)
        result["real_time_factor"] = round(sim_elapsed / wall_elapsed, 3) if wall_elapsed else None
        result["clock_step_s"] = step
        if abs(step) > CLOCK_STEP_TOLERANCE_S:
            # stderr, not launch.log: the launch group still holds that file
            # open at its own offset and would overwrite an appended line.
            print(f"clock-step: {out_dir.name}: wall clock stepped {step:+.1f} s during "
                  "this scenario; infrastructure, rerun it", file=sys.stderr, flush=True)
        (out_dir / "track.json").write_text(json.dumps(track))
        return result
    except Exception as exc:  # noqa: BLE001 - one scenario's failure must not abort the rest
        return {"pass": False, "reason": f"error:{type(exc).__name__}"}
    finally:
        # Stop the launch group first (before touching rclpy), then rclpy,
        # then the recorder (SIGINT so it finalises the MP4, not SIGKILL),
        # then anything that still survives, then close the log. Each step
        # is isolated so one failure does not skip the rest.
        if launch is not None:
            try:
                os.killpg(launch.pid, signal.SIGINT)
            except Exception:
                pass
            try:
                launch.wait(timeout=LAUNCH_STOP_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(launch.pid, signal.SIGKILL)
                except Exception:
                    pass
            except Exception:
                pass
        if node is not None:
            try:
                node.destroy_node()
            except Exception:
                pass
        if rclpy_started and rclpy_module is not None:
            try:
                rclpy_module.shutdown()
            except Exception:
                pass
        if recorder is not None:
            try:
                recorder.send_signal(signal.SIGINT)
            except Exception:
                pass
            try:
                recorder.wait(timeout=RECORDER_STOP_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                try:
                    recorder.kill()
                except Exception:
                    pass
            except Exception:
                pass
        try:
            _kill_leftover_processes(out_dir, domain)
        except Exception:
            pass
        if log_file is not None:
            try:
                log_file.close()
            except Exception:
                pass


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", default="centre")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--only", default="")
    parser.add_argument("--domain", type=int, default=57)
    args = parser.parse_args(argv)
    graph = yaml.safe_load(args.graph.read_text(encoding="utf-8"))
    results = []
    for k, scenario in enumerate(junction_score.scenarios(graph)):
        if args.only and scenario["node"] != args.only:
            continue
        out_dir = args.out / f"{k:02d}_{scenario['node']}_{scenario['into']}_to_{scenario['out']}".replace(":", "")
        out_dir.mkdir(parents=True, exist_ok=True)
        result = dict(scenario, **run_one(scenario, graph, args.mode, out_dir, args.domain))
        results.append(result)
        print(json.dumps(result), flush=True)
    (args.out / "results.json").write_text(json.dumps(results, indent=2))
    passed = sum(r["pass"] for r in results)
    print(f"{passed}/{len(results)} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
