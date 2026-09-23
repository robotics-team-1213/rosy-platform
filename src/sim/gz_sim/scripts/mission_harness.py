#!/usr/bin/env python3
"""Drive the lane-network mission (undock -> tour -> park) in headless Gazebo.

Mission plan stage 3 (docs/plans/2026-09-23-lane-network-parking-design.md).
ONE launch of map_v2_fleet_lane with the robot spawned on the parking spot
(-1.0, 0, 0), the route follower initialised there too (route_start: the
localiser and the follower follow the undock by odometry to the tour start),
the whole tour in `route`, and the dock observer on. Usage (WSL, sourced
overlay):

  python3 mission_harness.py --out /rosy_mapv2_ws/evidence/mission_<id> \
      --graph install/control/share/control/map/map_v2_fleet/lane_graph.yaml

Phases, each on a simulation-time budget, all through CORE's API:
  confirm  POST /docking/dock at the spot -> DOCKED (CORE only undocks a
           docked robot; this also proves the tag is seen)
  undock   POST /docking/undock -> UNDOCKED (0.27 m back, +90 deg onto west:f)
  tour     PUT /line-follow/mode CAMERA_LINE until the true route coordinate
           reaches the tour's end (coverage_harness.Progress, anchored on the
           first sample of the tour) or CORE reports LOST (CoreLease)
  park     PUT /line-follow/mode OFF, POST /docking/dock -> DOCKED
Scored: the tour with score_route (coverage_harness.score_tour), the final
pose against the spot on Gazebo's /odom ground truth (dx, dy, dyaw), and no
LOST. results.json, track.json (x, y, yaw, sim, phase per sample),
core_status.jsonl (CORE's line-follow and docking status once per wall
second) and the overlay MP4 go to --out; the result carries clock_step_s
as the other harnesses do.

Readiness, the mode API and process cleanup are junction_harness's, the
tour's scoring and lease coverage_harness's, so the harnesses cannot drift
apart. ROS imports are deferred into run_mission() so this module imports
on a host without ROS 2.
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
import coverage_harness  # noqa: E402
import junction_harness  # noqa: E402

DOCKING_API = "http://127.0.0.1:8080/api/v1/docking"
#: Simulation-time budgets per phase. confirm: look (0.5 s) + settle
#: (0.6 s) at a standstill. undock: 0.27 m at 0.08 m/s plus a 90 deg turn at
#: <= 0.5 rad/s. park: the -90 deg entry turn, a <= 0.2 m creep at 0.03 m/s,
#: the ~0.1 m tag approach at <= 0.05 m/s, align, settle, room for the
#: three reseats of max_retries. The tour's is coverage_harness.budget_s.
CONFIRM_BUDGET_S = 30.0
UNDOCK_BUDGET_S = 40.0
PARK_BUDGET_S = 150.0
#: Acceptance at the spot (design §6), on /odom ground truth.
PARK_POSITION_TOLERANCE_M = 0.020
PARK_HEADING_TOLERANCE_RAD = math.radians(5.0)
#: Docking status is polled at most this often (wall seconds).
DOCK_POLL_S = 0.25
PHASES = ("confirm", "undock", "tour", "park")


def mission_plan(graph):
    """(keys, spot pose, tour start pose, tour length m)."""
    keys, tour_start, length = coverage_harness.tour_plan(graph)
    spot = tuple(float(v) for v in graph["parking"]["spot"]) if "spot" in graph["parking"] \
        else _spot_from_points(graph)
    return keys, spot, tour_start, length


def _spot_from_points(graph):
    """The spur's last point, facing along it (lane_graph.yaml's `parking`
    carries points, not the rule's spot)."""
    (x0, y0), (x1, y1) = graph["parking"]["points"][-2], graph["parking"]["points"][-1]
    return (float(x1), float(y1), math.atan2(y1 - y0, x1 - x0))


def budgets(length_m):
    """Simulation-time budget per phase."""
    return {"confirm": CONFIRM_BUDGET_S, "undock": UNDOCK_BUDGET_S,
            "tour": coverage_harness.budget_s(length_m), "park": PARK_BUDGET_S}


def launch_args(keys, spot, mode):
    """map_v2_fleet_lane arguments: spawn AND route start on the spot."""
    x, y, yaw = spot
    return [f"spawn_x:={x}", f"spawn_y:={y}", f"spawn_yaw:={yaw}",
            f"camera_lane_mode:={mode}", "debug_overlay:=true", "dock_observer:=true",
            f"route:=[{', '.join(keys)}]", f"route_start:=[{x}, {y}, {yaw}]"]


def _request(url, method, headers, body=None, timeout=5.0):
    """(HTTP status, JSON body or None); status None on a transport failure."""
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read() or b"null")
        except ValueError:
            return exc.code, None
    except (urllib.error.URLError, OSError, ValueError):
        return None, None


class CoreApi:
    """CORE's HTTP API as the mission loop uses it."""

    def dock(self):
        return _request(f"{DOCKING_API}/dock", "POST", junction_harness.OPERATOR,
                        {"dock": "parking"})

    def undock(self):
        return _request(f"{DOCKING_API}/undock", "POST", junction_harness.OPERATOR, {})

    def set_line(self, mode):
        return junction_harness.set_mode(mode)

    def docking_status(self):
        return junction_harness._api_get(f"{DOCKING_API}/status", junction_harness.VIEWER)

    def line_status(self):
        return junction_harness._api_get(junction_harness.STATUS_API, junction_harness.VIEWER)


def record_mission(graph, keys, track, stamps, *, spin, api, monotonic, status_log,
                   budgets_s, wall_cap_s, status_period_s=None, dock_poll_s=DOCK_POLL_S,
                   lease=None):
    """The mission loop of run_mission, ROS-free. `spin()` delivers odometry
    (appending (x, y, yaw) to `track` and its simulation stamp to `stamps`);
    `api` is a CoreApi; `monotonic()` the wall clock. Each wall second one
    JSON line {"sim", "phase", "line", "docking"} goes to `status_log`.

    Returns a dict: `reason` ("parked", or "<phase>_failed" / "<phase>_timeout",
    "lost", "wall_cap", "no_odometry"), `phases` (name, sim_start, sim_end,
    outcome, first/last track index) and `tour_track` (the tour's (x, y)
    samples, from its first sample, cut after the one that reached the end)."""
    period = junction_harness.STATUS_SAMPLE_S if status_period_s is None else status_period_s
    lease = coverage_harness.CoreLease() if lease is None else lease
    wall_deadline = monotonic() + wall_cap_s
    next_status = monotonic()
    phases, tour_track = [], []
    state = {"phase": None, "since": None, "index": 0, "progress": None,
             "next_poll": monotonic(), "docking": None, "seen": 0}

    def sim():
        return stamps[-1] if stamps else None

    def close(outcome):
        record = phases[-1]
        record.update(sim_end=sim(), outcome=outcome, last_index=len(track) - 1)

    def begin(name):
        state.update(phase=name, since=sim(), index=len(track))
        phases.append({"name": name, "sim_start": sim(), "first_index": len(track)})

    def finish(reason):
        return {"reason": reason, "phases": phases, "tour_track": tour_track}

    def docking_state():
        if monotonic() >= state["next_poll"]:
            state["next_poll"] = monotonic() + dock_poll_s
            state["docking"] = api.docking_status()
        status = state["docking"]
        return status.get("state") if isinstance(status, dict) else None

    while monotonic() < wall_deadline and not stamps:
        spin()
    if not stamps:
        return finish("no_odometry")

    begin("confirm")
    status, _ = api.dock()
    if status != 200:
        close(f"http_{status}")
        return finish("confirm_failed")

    while monotonic() < wall_deadline:
        spin()
        phase = state["phase"]
        if monotonic() >= next_status:
            next_status = monotonic() + period
            line = api.line_status()
            status_log.write(json.dumps({"sim": sim(), "phase": phase, "line": line,
                                         "docking": state["docking"]}) + "\n")
            if phase == "tour" and lease.update(sim(), line):
                close("lost")
                return finish("lost")
        elapsed = sim() - state["since"]

        if phase == "tour":
            while state["seen"] < len(track):
                point = track[state["seen"]][:2]
                if state["progress"] is None:
                    state["progress"] = coverage_harness.Progress(graph, keys, point)
                tour_track.append(point)
                reached = state["progress"].update(point)
                state["seen"] += 1
                if reached:
                    close("reached")
                    api.set_line("OFF")
                    begin("park")
                    status, _ = api.dock()
                    if status != 200:
                        close(f"http_{status}")
                        return finish("park_failed")
                    state["docking"] = None
                    break
            else:
                if elapsed >= budgets_s["tour"]:
                    close("timeout")
                    api.set_line("OFF")
                    return finish("tour_timeout")
            continue

        docked = docking_state()
        target = {"confirm": "DOCKED", "undock": "UNDOCKED", "park": "DOCKED"}[phase]
        if docked == target and elapsed > 0.0:
            close(docked.lower())
            if phase == "confirm":
                begin("undock")
                status, _ = api.undock()
                if status != 200:
                    close(f"http_{status}")
                    return finish("undock_failed")
                state["docking"] = None
            elif phase == "undock":
                begin("tour")
                state["seen"] = len(track)
                api.set_line("CAMERA_LINE")
            else:
                return finish("parked")
        elif docked == "DOCK_FAILED":
            close("dock_failed")
            return finish(f"{phase}_failed")
        elif elapsed >= budgets_s[phase]:
            close("timeout")
            return finish(f"{phase}_timeout")
    if phases and "outcome" not in phases[-1]:
        close("wall_cap")
    return finish("wall_cap")


def park_error(pose, spot):
    """(dx, dy, dyaw, position error m) of the final pose against the spot."""
    dx, dy = pose[0] - spot[0], pose[1] - spot[1]
    dyaw = math.atan2(math.sin(pose[2] - spot[2]), math.cos(pose[2] - spot[2]))
    return dx, dy, dyaw, math.hypot(dx, dy)


def score_mission(graph, keys, spot, track, recorded):
    """The mission's verdict: the tour (score_tour), the final pose at the
    spot and the reason. Passes only when parked within tolerance after a
    reached tour."""
    phases = {p["name"]: p for p in recorded["phases"]}
    tour_reason = phases.get("tour", {}).get("outcome", "not_run")
    tour_track = recorded["tour_track"]
    tour = coverage_harness.score_tour(graph, keys, tour_track,
                                       tour_track[0] if tour_track else spot[:2], tour_reason)
    result = {"reason": recorded["reason"], "tour": tour,
              "phases": recorded["phases"]}
    if track:
        dx, dy, dyaw, position = park_error(track[-1], spot)
        result.update(final_pose=[round(v, 4) for v in track[-1]],
                      park_dx_m=round(dx, 4), park_dy_m=round(dy, 4),
                      park_dyaw_deg=round(math.degrees(dyaw), 2),
                      park_error_m=round(position, 4))
        parked_ok = (position <= PARK_POSITION_TOLERANCE_M
                     and abs(dyaw) <= PARK_HEADING_TOLERANCE_RAD)
    else:
        parked_ok = False
    result["lost"] = recorded["reason"] == "lost" or bool(tour.get("lost"))
    result["pass"] = (recorded["reason"] == "parked" and bool(tour["pass"])
                      and parked_ok and not result["lost"])
    return result


def run_mission(graph, keys, spot, mode, out_dir, domain, budgets_s, wall_cap_s):
    """ROS-only: launches Gazebo once, records ground-truth odometry over the
    whole mission, scores it. Always returns a result dict with at least
    `pass` and `reason`; never raises."""
    env = dict(os.environ, ROS_DOMAIN_ID=str(domain))
    launch = recorder = node = rclpy_module = log_file = None
    rclpy_started = False
    try:
        log_file = (out_dir / "launch.log").open("w")
        try:
            launch = subprocess.Popen(
                ["ros2", "launch", "gz_sim", "map_v2_fleet_lane.launch.py"]
                + launch_args(keys, spot, mode),
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
        node = Node("mission_harness")

        boot_deadline = time.monotonic() + junction_harness.BOOT_S
        if not junction_harness.wait_ready(node, rclpy, boot_deadline):
            return {"pass": False, "reason": "boot_timeout"}

        recorder = subprocess.Popen(
            ["python3", str(Path(__file__).with_name("record_debug.py")), "--out", str(out_dir),
             "--seconds", str(wall_cap_s + 5)], env=env)

        track, stamps = [], []

        def on_odom(m):
            q = m.pose.pose.orientation
            yaw = math.atan2(2.0 * (q.w * q.z + q.x * q.y), 1.0 - 2.0 * (q.y * q.y + q.z * q.z))
            track.append((m.pose.pose.position.x, m.pose.pose.position.y, yaw))
            stamps.append(m.header.stamp.sec + m.header.stamp.nanosec * 1e-9)

        node.create_subscription(Odometry, "odom", on_odom, qos_profile_sensor_data)
        clock_offset = junction_harness.wall_clock_offset()
        wall_start = time.monotonic()
        lease = coverage_harness.CoreLease()
        with (out_dir / "core_status.jsonl").open("w") as status_log:
            recorded = record_mission(
                graph, keys, track, stamps,
                spin=lambda: rclpy.spin_once(node, timeout_sec=0.1),
                api=CoreApi(), monotonic=time.monotonic, status_log=status_log,
                budgets_s=budgets_s, wall_cap_s=wall_cap_s, lease=lease)
        wall_elapsed = time.monotonic() - wall_start
        step = junction_harness.clock_step_s(clock_offset, junction_harness.wall_clock_offset())
        sim_elapsed = (stamps[-1] - stamps[0]) if stamps else 0.0
        junction_harness.set_mode("OFF")
        result = score_mission(graph, keys, spot, track, recorded)
        result["sim_s"] = round(sim_elapsed, 2)
        result["wall_s"] = round(wall_elapsed, 2)
        result["real_time_factor"] = round(sim_elapsed / wall_elapsed, 3) if wall_elapsed else None
        result["clock_step_s"] = step
        # Diagnostic only: the lease is lost on CORE's LOST, never on this.
        result["longest_stall_s"] = round(lease.longest_stall_s, 2)
        if abs(step) > junction_harness.CLOCK_STEP_TOLERANCE_S:
            print(f"clock-step: wall clock stepped {step:+.1f} s during the mission; "
                  "infrastructure, rerun it", file=sys.stderr, flush=True)
        phase_of = [None] * len(track)
        for record in recorded["phases"]:
            last = record.get("last_index", len(track) - 1)
            for k in range(record["first_index"], min(last, len(track) - 1) + 1):
                phase_of[k] = record["name"]
        (out_dir / "track.json").write_text(json.dumps(
            [[x, y, yaw, t, p] for (x, y, yaw), t, p in zip(track, stamps, phase_of)]))
        return result
    except Exception as exc:  # noqa: BLE001 - always return a recorded result
        return {"pass": False, "reason": f"error:{type(exc).__name__}"}
    finally:
        # Same order as junction_harness.run_one: launch group, rclpy, the
        # recorder (SIGINT so it finalises the MP4), leftovers, the log.
        if launch is not None:
            try:
                os.killpg(launch.pid, signal.SIGINT)
            except Exception:
                pass
            try:
                launch.wait(timeout=junction_harness.LAUNCH_STOP_TIMEOUT_S)
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
                recorder.wait(timeout=junction_harness.RECORDER_STOP_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                try:
                    recorder.kill()
                except Exception:
                    pass
            except Exception:
                pass
        try:
            junction_harness._kill_leftover_processes(out_dir, domain)
        except Exception:
            pass
        if log_file is not None:
            try:
                log_file.close()
            except Exception:
                pass


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", default="route_ab", choices=coverage_harness.ROUTE_MODES)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--domain", type=int, default=57)
    parser.add_argument("--dry-run", action="store_true",
                        help="print the plan and the launch command, run nothing")
    args = parser.parse_args(argv)
    graph = yaml.safe_load(args.graph.read_text(encoding="utf-8"))
    keys, spot, tour_start, length = mission_plan(graph)
    budgets_s = budgets(length)
    total = sum(budgets_s.values())
    plan = {"keys": keys, "spot": list(spot), "tour_start": list(tour_start),
            "length_m": round(length, 3),
            "budgets_s": {k: round(v, 1) for k, v in budgets_s.items()},
            "budget_total_s": round(total, 1), "mode": args.mode,
            "launch": ["ros2", "launch", "gz_sim", "map_v2_fleet_lane.launch.py"]
            + launch_args(keys, spot, args.mode)}
    print(json.dumps(plan), flush=True)
    if args.dry_run:
        return 0
    args.out.mkdir(parents=True, exist_ok=True)
    result = dict(plan, **run_mission(graph, keys, spot, args.mode, args.out, args.domain,
                                      budgets_s, coverage_harness.WALL_CAP_FACTOR * total))
    (args.out / "results.json").write_text(json.dumps(result, indent=2))
    print(json.dumps({k: v for k, v in result.items() if k not in ("launch", "phases")}),
          flush=True)
    print("PASS" if result["pass"] else f"FAIL ({result['reason']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
