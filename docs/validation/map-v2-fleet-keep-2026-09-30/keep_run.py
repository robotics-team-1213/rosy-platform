#!/usr/bin/env python3
"""Closed-loop 'keep' lane run in the map_v2_fleet real-profile sim (D-364 5).

Runs inside the ROS box (WSL) next to map_v2_fleet_real.launch.py
camera_lane_mode:=keep. It optionally teleports the robot, starts CAMERA_LINE
through CORE REST with a driver hold (hold_s), keeps POSTing /hold at 10 Hz,
logs line-follow status + Gazebo ground-truth pose at ~5 Hz, saves camera
frames at --fps (sim time), and releases (mode OFF) after --duration sim s,
on LOST, or
when the mode drops. Then it scores the run (see analyze()).

  python3 keep_run.py --out /rosy_realprof_ws/keep/runs/A1 --spawn -1.26955,0.24255,-1.5708

Outputs in --out: log.csv (status + pose), frames/NNNN.png, frames.csv,
events.txt, metrics.json, trajectory.png. Needs rclpy, gz.transport13,
requests, opencv, yaml; matplotlib only for the plot.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import subprocess
import threading
import time

import cv2
import numpy as np
import requests
import yaml

WORLD = "map_v2_fleet"
MODEL = "rosy"
#: Lane geometry (lane_graph.py): lane half-width 92.5 mm, tape 25 mm.
LANE_HALF_M = 0.0925
TAPE_HALF_M = 0.0125
#: Pinky footprint half-width (~0.10 m wide).
ROBOT_HALF_M = 0.05
#: Lateral offset from the lane centre at which the footprint edge ...
TOUCH_M = LANE_HALF_M - TAPE_HALF_M - ROBOT_HALF_M   # 0.030: reaches the tape
CROSS_M = LANE_HALF_M - ROBOT_HALF_M                 # 0.0425: is past the line centre


def lane_polylines(graph: dict) -> dict:
    return {name: np.asarray(seg["points"], float) for name, seg in graph["segments"].items()}


def nearest_centre(polylines: dict, x: float, y: float):
    """(distance, signed offset left of travel direction, segment name)."""
    best = (math.inf, 0.0, "")
    p = np.array([x, y])
    for name, pts in polylines.items():
        a, b = pts[:-1], pts[1:]
        ab = b - a
        t = np.clip(np.einsum("ij,ij->i", p - a, ab) / np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-12), 0, 1)
        q = a + ab * t[:, None]
        d = np.hypot(*(p - q).T)
        k = int(np.argmin(d))
        if d[k] < best[0]:
            cross = ab[k, 0] * (p[1] - a[k, 1]) - ab[k, 1] * (p[0] - a[k, 0])
            best = (float(d[k]), float(math.copysign(d[k], cross)), name)
    return best


class GroundTruth:
    """Latest Gazebo pose of MODEL from /world/<w>/pose/info."""

    def __init__(self, world: str, model: str):
        from gz.msgs10.pose_v_pb2 import Pose_V
        from gz.transport13 import Node
        self.model = model
        self.pose = None
        self.node = Node()
        self.node.subscribe(Pose_V, f"/world/{world}/pose/info", self._cb)

    def _cb(self, msg):
        for pose in msg.pose:
            if pose.name == self.model:
                q = pose.orientation
                yaw = math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))
                stamp = msg.header.stamp.sec + msg.header.stamp.nsec * 1e-9
                self.pose = (pose.position.x, pose.position.y, yaw, stamp)
                return


def teleport(x: float, y: float, yaw: float):
    req = (f'name: "{MODEL}", position: {{x: {x}, y: {y}, z: 0.002}}, '
           f'orientation: {{x: 0, y: 0, z: {math.sin(yaw / 2)}, w: {math.cos(yaw / 2)}}}')
    return subprocess.run(["gz", "service", "-s", f"/world/{WORLD}/set_pose", "--reqtype", "gz.msgs.Pose",
                           "--reptype", "gz.msgs.Boolean", "--timeout", "3000", "--req", req],
                          capture_output=True, text=True).stdout.strip()


def run(args) -> dict:
    import rclpy
    from rclpy.node import Node
    from sensor_msgs.msg import Image

    os.makedirs(os.path.join(args.out, "frames"), exist_ok=True)
    truth = GroundTruth(WORLD, MODEL)
    if args.spawn:
        x, y, yaw = (float(v) for v in args.spawn.split(","))
        # Stop anything moving first, then place the robot.
        requests.put(f"{args.core}/api/v1/line-follow/mode", json={"mode": "OFF"},
                     headers={"Authorization": f"Bearer {args.token}"}, timeout=3)
        print("teleport", teleport(x, y, yaw), flush=True)
        time.sleep(3.0)

    rclpy.init()
    node = Node("keep_run")
    latest = {}

    def on_image(m):
        ch = 3 if m.encoding in ("rgb8", "bgr8") else 1
        a = np.frombuffer(m.data, np.uint8).reshape(m.height, m.width, ch)
        latest["img"] = a[:, :, ::-1].copy() if m.encoding == "rgb8" else a.copy()
        latest["t"] = m.header.stamp.sec + m.header.stamp.nanosec * 1e-9

    node.create_subscription(Image, "camera/front", on_image, 1)
    spin = threading.Thread(target=rclpy.spin, args=(node,), daemon=True)
    spin.start()

    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {args.token}"
    stop = threading.Event()
    events = open(os.path.join(args.out, "events.txt"), "w")

    def event(text):
        line = f"{time.time() - t0:7.2f} {text}"
        print(line, flush=True)
        events.write(line + "\n")
        events.flush()

    def hold_loop():
        while not stop.is_set():
            try:
                r = session.post(f"{args.core}/api/v1/line-follow/hold", timeout=0.5)
                if r.status_code != 200:
                    event(f"hold {r.status_code} {r.text[:120]}")
            except requests.RequestException as exc:
                event(f"hold error {exc}")
            stop.wait(0.1)

    t0 = time.time()
    for _ in range(50):
        if truth.pose and "img" in latest:
            break
        time.sleep(0.2)
    event(f"start pose {truth.pose} frame {'img' in latest}")
    r = session.put(f"{args.core}/api/v1/line-follow/mode",
                    json={"mode": "CAMERA_LINE", "hold_s": args.hold_s}, timeout=3)
    event(f"mode PUT {r.status_code} {r.text[:300]}")
    holder = threading.Thread(target=hold_loop, daemon=True)
    holder.start()

    log = open(os.path.join(args.out, "log.csv"), "w", newline="")
    frames = open(os.path.join(args.out, "frames.csv"), "w", newline="")
    lw = csv.writer(log)
    fw = csv.writer(frames)
    lw.writerow(["t", "sim_t", "state", "reason", "error", "confidence", "linear", "angular", "x", "y", "yaw"])
    fw.writerow(["frame", "t", "sim_t", "state", "reason", "error", "x", "y", "yaw"])
    last_state, last_frame_t, frame_k, status = None, -1e9, 0, {}
    sim0 = truth.pose[3] if truth.pose else 0.0
    end_reason = "duration"
    while time.time() - t0 < args.wall_max:
        try:
            status = session.get(f"{args.core}/api/v1/line-follow", timeout=0.5).json()
        except (requests.RequestException, ValueError) as exc:
            event(f"status error {exc}")
            time.sleep(0.2)
            continue
        now = time.time() - t0
        pose = truth.pose or (math.nan, math.nan, math.nan, sim0)
        sim_t = pose[3] - sim0
        if sim_t >= args.duration:
            break
        state, reason = status.get("state"), status.get("reason")
        lw.writerow([f"{now:.2f}", f"{sim_t:.2f}", state, reason, status.get("error"), status.get("confidence"),
                     status.get("linear"), status.get("angular"),
                     f"{pose[0]:.4f}", f"{pose[1]:.4f}", f"{pose[2]:.4f}"])
        if (state, reason) != last_state:
            event(f"state {state} {reason} err={status.get('error')} pose=({pose[0]:.3f},{pose[1]:.3f})")
            last_state = (state, reason)
        if "img" in latest and latest["t"] - last_frame_t >= 1.0 / args.fps:
            name = f"{frame_k:04d}.png"
            cv2.imwrite(os.path.join(args.out, "frames", name), latest["img"])
            fw.writerow([name, f"{now:.2f}", f"{sim_t:.2f}", state, reason, status.get("error"),
                         f"{pose[0]:.4f}", f"{pose[1]:.4f}", f"{pose[2]:.4f}"])
            frame_k += 1
            last_frame_t = latest["t"]
        if state == "LOST":
            end_reason = f"LOST {reason}"
            break
        if status.get("mode") == "OFF" and now > 5.0:
            end_reason = f"mode OFF {reason}"
            break
        time.sleep(0.2)
    stop.set()
    r = session.put(f"{args.core}/api/v1/line-follow/mode", json={"mode": "OFF"}, timeout=3)
    event(f"end {end_reason}; release {r.status_code} {r.json().get('state') if r.ok else r.text[:120]}")
    log.close()
    frames.close()
    events.close()
    node.destroy_node()
    rclpy.shutdown()
    return {"end": end_reason}


def analyze(out: str, graph_path: str, end: str = "") -> dict:
    graph = yaml.safe_load(open(graph_path))
    polylines = lane_polylines(graph)
    rows = list(csv.DictReader(open(os.path.join(out, "log.csv"))))
    xy, lat, seg, t = [], [], [], []
    for row in rows:
        x, y = float(row["x"]), float(row["y"])
        if math.isnan(x):
            continue
        d, _, name = nearest_centre(polylines, x, y)
        xy.append((x, y))
        lat.append(d)
        seg.append(name)
        t.append(float(row["sim_t"]))
    if not xy:
        return {"samples": len(rows), "end": end, "error": "no ground-truth pose"}
    xy = np.asarray(xy)
    lat = np.asarray(lat)
    step = np.hypot(*np.diff(xy, axis=0).T) if len(xy) > 1 else np.zeros(0)
    moving = np.concatenate(([False], step > 0.002))
    states = [(r["sim_t"], r["state"], r["reason"]) for r in rows]
    stops, previous = [], None
    for tt, state, reason in states:
        if state != "TRACKING" and (previous is None or previous[1] == "TRACKING"):
            stops.append(f"sim {tt}s {state} {reason}")
        previous = (tt, state)

    def spans(threshold):
        above = lat > threshold
        return int(np.sum(above[1:] & ~above[:-1]) + (above[0] if len(above) else 0))

    metrics = {
        "samples": len(rows),
        "sim_duration_s": round(t[-1] - t[0], 1) if t else 0.0,
        "wall_duration_s": round(float(rows[-1]["t"]) - float(rows[0]["t"]), 1) if rows else 0.0,
        "distance_m": round(float(step.sum()), 3),
        "lateral_mean_m": round(float(lat[moving].mean()) if moving.any() else float(lat.mean()), 4),
        "lateral_max_m": round(float(lat.max()), 4),
        "lateral_p95_m": round(float(np.percentile(lat, 95)), 4),
        "touch_tape_events": spans(TOUCH_M),
        "cross_line_events": spans(CROSS_M),
        "centre_off_lane_events": spans(LANE_HALF_M),
        "time_over_line_s": round(float(np.sum(np.diff(t, prepend=t[0])[lat > CROSS_M])), 1) if t else 0.0,
        "segments": sorted(set(seg)),
        "tracking_fraction": round(sum(1 for s in states if s[1] == "TRACKING") / max(1, len(states)), 3),
        "stops": stops[:20],
        "end": end,
    }
    json.dump(metrics, open(os.path.join(out, "metrics.json"), "w"), indent=1)
    plot(out, polylines, xy, lat, metrics)
    return metrics


def plot(out, polylines, xy, lat, metrics):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return
    fig, ax = plt.subplots(figsize=(12, 5.6))
    for name, pts in polylines.items():
        d = np.gradient(pts, axis=0)
        n = np.stack([-d[:, 1], d[:, 0]], axis=1) / np.maximum(np.hypot(*d.T), 1e-9)[:, None]
        ax.plot(*pts.T, color="0.75", lw=0.8, ls="--")
        for s in (1, -1):
            ax.plot(*(pts + s * LANE_HALF_M * n).T, color="0.35", lw=2.2, alpha=0.6)
    if len(xy):
        sc = ax.scatter(xy[:, 0], xy[:, 1], c=lat * 1000, cmap="viridis_r", s=6, vmin=0, vmax=60)
        fig.colorbar(sc, ax=ax, label="lateral distance from lane centre (mm)")
        ax.plot(*xy[0], "go", ms=8)
        ax.plot(*xy[-1], "bs", ms=8)
    ax.set_aspect("equal")
    ax.set_title(f"{os.path.basename(out)}: {metrics['distance_m']} m, lateral mean "
                 f"{metrics['lateral_mean_m'] * 1000:.1f} / max {metrics['lateral_max_m'] * 1000:.1f} mm, "
                 f"line crossings {metrics['cross_line_events']}, end: {metrics['end']}")
    ax.set_xlabel("x (m)")
    ax.set_ylabel("y (m)")
    fig.tight_layout()
    fig.savefig(os.path.join(out, "trajectory.png"), dpi=110)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", required=True)
    p.add_argument("--core", default="http://127.0.0.1:8093")
    p.add_argument("--token", default="rosy-dev-operator")
    p.add_argument("--graph", default="/rosy_realprof_ws/install/control/share/control/map/map_v2_fleet/lane_graph.yaml")
    p.add_argument("--spawn", help="x,y,yaw teleport before the run")
    p.add_argument("--duration", type=float, default=180.0, help="sim seconds")
    p.add_argument("--wall-max", type=float, default=3600.0, help="wall-clock cap, s")
    p.add_argument("--hold-s", type=float, default=0.5)
    p.add_argument("--fps", type=float, default=2.0)
    p.add_argument("--analyze-only", action="store_true")
    args = p.parse_args()
    end = ""
    if not args.analyze_only:
        end = run(args)["end"]
    elif os.path.exists(os.path.join(args.out, "metrics.json")):
        end = json.load(open(os.path.join(args.out, "metrics.json"))).get("end", "")
    print(json.dumps(analyze(args.out, args.graph, end), indent=1))


if __name__ == "__main__":
    main()
