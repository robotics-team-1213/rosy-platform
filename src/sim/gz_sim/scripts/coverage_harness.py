#!/usr/bin/env python3
"""Drive the all-lane coverage tour in headless Gazebo and score it.

Mission plan stage 2: lane_coverage's tour (every directed lane segment,
from the parking junction on west back to it), driven by one route
follower in ONE launch. Usage (WSL, sourced overlay):

  python3 coverage_harness.py --out /rosy_mapv2_ws/evidence/tour_<id> \
      --graph src/apps/control/map/map_v2_fleet/lane_graph.yaml [--mode route_ab]

Launch map_v2_fleet_lane once at the tour start with the whole route in the
existing `route` / `route_start` launch args, wait for readiness
(junction_harness.wait_ready, BOOT_S), enable CAMERA_LINE through CORE's
API, record /odom (Gazebo ground truth) until the true route coordinate
reaches the start point again on the last key (`Progress`), or the
simulation-time budget sized from the tour length (`budget_s`), or the
wall-clock cap; then stop, score with junction_score.score_route and write
results.json, track.json, core_status.jsonl (CORE's line-follow status once
per wall second) and the overlay MP4 (record_debug.py, debug_overlay:=true)
into --out. The result carries clock_step_s (a WSL wall-clock step during
the tour marks it infrastructure evidence, as in junction_harness).

Readiness, the mode API and process cleanup are junction_harness's, so the
two harnesses cannot drift apart. ROS imports are deferred into run_tour()
(as in junction_harness) so this module imports on a host without ROS 2.
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import junction_harness  # noqa: E402
import junction_score  # noqa: E402

#: CORE line_follow cruise (LineFollowConfig); the tour budget is the tour
#: length at BUDGET_SPEED_FRACTION of it. Offline the hybrid drove the
#: 16.874 m tour in 339 s of simulated time (0.62 of cruise).
CORE_CRUISE_M_S = 0.08
BUDGET_SPEED_FRACTION = 0.4
#: The budget never goes below this (a short test route still boots and
#: settles).
MIN_BUDGET_S = 120.0
#: Wall-clock cap as a multiple of the simulation budget: a loaded host
#: runs Gazebo well under real time (junction_harness: 1.1 Hz camera at
#: load 22), so the cap is generous; it only stops a stalled simulation.
WALL_CAP_FACTOR = 4.0
ROUTE_MODES = ("route_a", "route_b", "route_ab")
#: The tour ends once its route coordinate is this close to the end (the
#: start point on the last key): a sample exactly on the start may project
#: a hair short of it. Well inside score_route's ROUTE_END_MAX_M.
END_TOLERANCE_M = 0.005


def tour_plan(graph, start_xy=None):
    """(keys, start pose, length m) of lane_coverage's tour from `start_xy`
    (default: the parking spur's junction point, graph["parking"])."""
    from control.sensing.lane_coverage import coverage_route, tour_length, tour_start_pose

    start_xy = tuple(graph["parking"]["points"][0]) if start_xy is None else tuple(start_xy)
    keys = coverage_route(graph, start_xy)
    return keys, tour_start_pose(graph, keys, start_xy), tour_length(graph, keys, start_xy)


def budget_s(length_m):
    """Simulation-time budget for a route of `length_m`."""
    return max(MIN_BUDGET_S, length_m / (BUDGET_SPEED_FRACTION * CORE_CRUISE_M_S))


def launch_args(keys, pose, mode):
    """map_v2_fleet_lane launch arguments for one tour launch."""
    x, y, yaw = pose
    args = [f"spawn_x:={x}", f"spawn_y:={y}", f"spawn_yaw:={yaw}",
            f"camera_lane_mode:={mode}", "debug_overlay:=true"]
    if mode in ROUTE_MODES:
        # A YAML flow-list string, as junction_harness passes [into, out].
        args += [f"route:=[{', '.join(keys)}]", f"route_start:=[{x}, {y}, {yaw}]"]
    return args


class Progress:
    """The true route coordinate of a recorded track, as score_route and
    lane_scenarios.run_route compute it: anchored on the first key at the
    start, then searched within SEARCH_WINDOW_M of the previous point, so
    the tour's end (the start point, on the last key) is only reached after
    the whole route and not at the first sample."""

    def __init__(self, graph, keys, start_xy):
        self.path, self.arc, starts = junction_score.route_path(graph, keys)
        last = junction_score.directed_points(graph, keys[-1])
        self.end_s = float(starts[-2] + junction_score._nearest_on_path(
            last, junction_score._arc_length(last), start_xy)[0])
        self.s, _ = junction_score._nearest_on_path(
            self.path, self.arc, start_xy, (0.0, float(starts[1])))
        self.start_s = self.s

    def update(self, xy) -> bool:
        """Advance on a new sample; True once the tour's end is reached."""
        w = junction_score.SEARCH_WINDOW_M
        self.s, _ = junction_score._nearest_on_path(self.path, self.arc, xy,
                                                    (self.s - w, self.s + w))
        return self.s >= self.end_s - END_TOLERANCE_M


def run_tour(graph, keys, pose, mode, out_dir, domain, sim_budget_s, wall_cap_s):
    """ROS-only: launches Gazebo once, records ground-truth odometry over
    the whole tour, scores it. Always returns a result dict with at least
    `pass` and `reason`; never raises."""
    env = dict(os.environ, ROS_DOMAIN_ID=str(domain))
    launch = recorder = node = rclpy_module = log_file = None
    rclpy_started = False
    try:
        log_file = (out_dir / "launch.log").open("w")
        try:
            launch = subprocess.Popen(
                ["ros2", "launch", "gz_sim", "map_v2_fleet_lane.launch.py"]
                + launch_args(keys, pose, mode),
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
        node = Node("coverage_harness")

        boot_deadline = time.monotonic() + junction_harness.BOOT_S
        if not junction_harness.wait_ready(node, rclpy, boot_deadline):
            return {"pass": False, "reason": "boot_timeout"}

        recorder = subprocess.Popen(
            ["python3", str(Path(__file__).with_name("record_debug.py")), "--out", str(out_dir),
             "--seconds", str(wall_cap_s + 5)], env=env)

        track, stamps = [], []

        def on_odom(m):
            track.append((m.pose.pose.position.x, m.pose.pose.position.y))
            stamps.append(m.header.stamp.sec + m.header.stamp.nanosec * 1e-9)

        node.create_subscription(Odometry, "odom", on_odom, qos_profile_sensor_data)
        progress = Progress(graph, keys, pose[:2])
        junction_harness.set_mode("CAMERA_LINE")
        clock_offset = junction_harness.wall_clock_offset()
        wall_start = time.monotonic()
        wall_deadline = wall_start + wall_cap_s
        sim_start, seen = None, 0
        reached, reason = False, "wall_cap"
        status_log = (out_dir / "core_status.jsonl").open("w")
        next_status = wall_start
        while time.monotonic() < wall_deadline and not reached:
            rclpy.spin_once(node, timeout_sec=0.1)
            if time.monotonic() >= next_status:
                next_status = time.monotonic() + junction_harness.STATUS_SAMPLE_S
                status = junction_harness._api_get(junction_harness.STATUS_API,
                                                   junction_harness.VIEWER)
                status_log.write(json.dumps(
                    {"sim": stamps[-1] if stamps else None, "status": status}) + "\n")
            if stamps and sim_start is None:
                sim_start = stamps[-1]
            while seen < len(track):
                if progress.update(track[seen]):
                    reached, reason = True, "reached"
                    del track[seen + 1:]
                    break
                seen += 1
            if not reached and sim_start is not None and stamps[-1] - sim_start >= sim_budget_s:
                reason = "timeout"
                break
        status_log.close()
        wall_elapsed = time.monotonic() - wall_start
        step = junction_harness.clock_step_s(clock_offset, junction_harness.wall_clock_offset())
        sim_elapsed = (stamps[-1] - sim_start) if sim_start is not None else 0.0
        junction_harness.set_mode("OFF")
        result = junction_score.score_route(graph, keys, track or [pose[:2]])
        result["reason"] = reason
        result["sim_s"] = round(sim_elapsed, 2)
        result["wall_s"] = round(wall_elapsed, 2)
        result["real_time_factor"] = round(sim_elapsed / wall_elapsed, 3) if wall_elapsed else None
        result["clock_step_s"] = step
        if abs(step) > junction_harness.CLOCK_STEP_TOLERANCE_S:
            print(f"clock-step: wall clock stepped {step:+.1f} s during the tour; "
                  "infrastructure, rerun it", file=sys.stderr, flush=True)
        (out_dir / "track.json").write_text(json.dumps(track))
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
    parser.add_argument("--mode", default="route_ab", choices=ROUTE_MODES)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--domain", type=int, default=57)
    parser.add_argument("--budget-s", type=float, default=None,
                        help="simulation-time budget (default: sized from the tour length)")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the tour and the launch command, run nothing")
    args = parser.parse_args(argv)
    graph = yaml.safe_load(args.graph.read_text(encoding="utf-8"))
    keys, pose, length = tour_plan(graph)
    sim_budget = budget_s(length) if args.budget_s is None else float(args.budget_s)
    plan = {"keys": keys, "start": list(pose), "length_m": round(length, 3),
            "budget_s": round(sim_budget, 1), "mode": args.mode,
            "launch": ["ros2", "launch", "gz_sim", "map_v2_fleet_lane.launch.py"]
            + launch_args(keys, pose, args.mode)}
    print(json.dumps(plan), flush=True)
    if args.dry_run:
        return 0
    args.out.mkdir(parents=True, exist_ok=True)
    result = dict(plan, **run_tour(graph, keys, pose, args.mode, args.out, args.domain,
                                   sim_budget, WALL_CAP_FACTOR * sim_budget))
    (args.out / "results.json").write_text(json.dumps(result, indent=2))
    print(json.dumps({k: v for k, v in result.items() if k != "launch"}), flush=True)
    print("PASS" if result["pass"] else f"FAIL ({result['reason']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
