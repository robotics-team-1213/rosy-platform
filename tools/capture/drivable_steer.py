"""D-592 drivable steering field test: camera frame -> drivable model -> CORE teleop (MANUAL).

    drivable_steer.py --robot <robot-ip> --token-file FILE (--ca-file CA | --insecure)
                      --model DIR [--source ros|stream] [--topic /<ns>/camera/front]
                      [--drive] [--max-s 60] [--linear 0.03] [--max-angular 0.4] [--gain 0.6]
                      [--min-fraction 0.10] [--max-age-s 0.5] [--record] --out DIR

Each cycle takes the newest front frame, runs the ONNX model in DIR (model_manifest.json +
its files, sha256 checked), keeps the drivable region of the bottom 40 % that the robot can
reach without crossing a lane line (lane_mask.lane_bounded_drivable with the D-576 boundary,
D-566 item 4) plus the inner half of each boundary line (D-554 item 10). When that region is
split into branches, the rightmost branch is followed (keep right, D-384 decision 2). The
branch centroid's lateral error e in [-1, 1] (positive: right of centre) gives
w = clip(-gain * e, +-max_angular) (positive w turns left, REP 103).

Stops (zero sent, run ends with `--drive`): drivable fraction of the band below
--min-fraction, frame older than --max-age-s at command time, RobotBody LiDAR guard refusal
(shared core_common.robot_body; a stale scan counts as refusal), --max-s reached. Without
--drive nothing is sent to CORE (dry run, D-592 item 3) and the stop reasons are only logged.
With --drive the run ends with zero teleop and mode IDLE. CORE stays the only /cmd_vel
publisher; its body stop and 500 ms teleop watchdog stay on.

Host: the robot itself by default (D-592 amended 2026-10-10), `--source ros` subscribes to
the raw camera Image topic (needs the ROS env and rclpy); off-board, `--source stream` reads
the driver MJPEG stream (GET /vision/front/stream?overlay=false, the preview rate).
Per-cycle rows go to OUT/cycles.jsonl, the processed frames to OUT/frames/<seq>.jpg.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "middleware" / "perception"))
sys.path.insert(0, str(REPO / "contracts" / "foundation"))

from core_common.robot_body import PINKY_PRO  # noqa: E402
from control.sensing.perception.learned import lane_mask  # noqa: E402
from control.sensing.perception.learned.manifest import load_manifest, verify_files  # noqa: E402
from edge_drive import TOKEN_ENV, Core, lidar_forward_deg, rec_start, rec_stop, tls_context  # noqa: E402

PERIOD_S = 0.15          # cycle; well inside CORE's 500 ms teleop watchdog
GUARD_PERIOD_S = 0.2
GUARD_STALE_S = 0.5


@dataclass(frozen=True)
class Limits:
    linear: float = 0.03
    max_angular: float = 0.4
    gain: float = 0.6
    min_fraction: float = 0.10
    max_age_s: float = 0.5
    max_s: float = 60.0


# --- steering math (pure) -------------------------------------------------------------------

def near_target(labels: np.ndarray, classes) -> tuple[np.ndarray, float]:
    """(drivable target in the bottom 40 % band, its fraction of the band).

    The lane_evidence drivable branch without its lane_marking fallback: line-bounded drivable
    with the D-576 boundary, crosswalk/speed-bump paint passable, plus the inner line halves."""
    h = labels.shape[0]
    band = labels[int(h * (1 - lane_mask.NEAR_FIELD_FRACTION)):]
    roles, names = {}, {c.name: c.index for c in classes}
    for c in classes:
        roles.setdefault(c.role, []).append(c.index)
    if "drivable" not in roles:
        raise ValueError("model has no drivable class")
    boundary = (names["lane_left"], names["lane_right"]) if {"lane_left", "lane_right"} <= set(names) else None
    drivable = lane_mask.lane_bounded_drivable(band, roles["drivable"][0], roles.get("lane_marking", ()),
                                               through_idxs=roles.get("ignore", ()), boundary=boundary)
    target = lane_mask._drop_small(lane_mask._with_inner_line_half(drivable, band, classes),
                                   lane_mask.MIN_COMPONENT_PX)
    return target, float(target.mean())


def pick_branch(target: np.ndarray) -> tuple[np.ndarray, int]:
    """(rightmost 8-connected component by centroid x, number of components). Keep right."""
    n, comp, _, cent = cv2.connectedComponentsWithStats(target.astype(np.uint8), connectivity=8)
    if n <= 2:
        return target, n - 1
    return comp == 1 + int(np.argmax(cent[1:, 0])), n - 1


def lateral_error(mask: np.ndarray) -> float | None:
    """(centroid x - centre) / half width in [-1, 1]; positive = right of centre; None if empty."""
    _, xs = np.nonzero(mask)
    if not xs.size:
        return None
    w = mask.shape[1]
    return float(np.clip((xs.mean() - (w - 1) / 2.0) / (w / 2.0), -1.0, 1.0))


def command(fraction: float, error: float | None, age_s: float | None, guard_ok: bool,
            elapsed_s: float, lim: Limits) -> tuple[float, float, str | None]:
    """(linear, angular, stop reason or None). Any stop reason means zero."""
    if elapsed_s >= lim.max_s:
        return 0.0, 0.0, "time_cap"
    if age_s is None or age_s > lim.max_age_s:
        return 0.0, 0.0, "stale"
    if not guard_ok:
        return 0.0, 0.0, "guard"
    if error is None or fraction < lim.min_fraction:
        return 0.0, 0.0, "drivable_low"
    w = max(-lim.max_angular, min(lim.max_angular, -lim.gain * error))
    return lim.linear, w, None


def guard_check(scan: dict, linear: float, forward_deg: float, body=PINKY_PRO) -> tuple[bool, dict]:
    """RobotBody LiDAR gate for one forward cycle: gap >= travel in the watchdog window + stop gap."""
    view = body.scan_view(scan, forward_deg=forward_deg)
    need = abs(linear) * 0.5 + body.stop_gap_m(abs(linear))
    gap = body.translation_gap(view.points)
    unknown = bool(body.unknown_blocks(view))
    ok = (gap is None or gap >= need) and not unknown
    return ok, {"gap_m": None if gap is None else round(gap, 3), "need_m": round(need, 3), "unknown": unknown}


# --- frame sources --------------------------------------------------------------------------

class Latest:
    def __init__(self):
        self.lock, self.item = threading.Lock(), None

    def put(self, item):
        with self.lock:
            self.item = item

    def get(self):
        with self.lock:
            return self.item


class RosFrames(threading.Thread):
    """Raw sensor_msgs/Image on the robot; (seq, capture stamp s, BGR). Same clock as the loop."""

    def __init__(self, topic):
        super().__init__(daemon=True)
        import rclpy
        from rclpy.qos import qos_profile_sensor_data
        from sensor_msgs.msg import Image
        rclpy.init()
        self.rclpy, self.latest, self.seq = rclpy, Latest(), 0
        self.node = rclpy.create_node("d592_drivable_steer")
        self.node.create_subscription(Image, topic, self._on, qos_profile_sensor_data)

    def _on(self, m):
        img = np.frombuffer(m.data, np.uint8).reshape(m.height, m.step)[:, :m.width * 3].reshape(m.height, m.width, 3)
        bgr = img[..., ::-1] if m.encoding == "rgb8" else img
        self.seq += 1
        self.latest.put((self.seq, m.header.stamp.sec + m.header.stamp.nanosec * 1e-9, np.ascontiguousarray(bgr)))

    def run(self):
        self.rclpy.spin(self.node)


class StreamFrames(threading.Thread):
    """Driver MJPEG stream parts; (X-Rosy-Camera-Sequence, Captured-At, BGR). Robot clock."""

    HDR = re.compile(rb"X-Rosy-Camera-Sequence: (\d+)\r\n.*?X-Rosy-Camera-Captured-At: ([\d.]+)", re.S)

    def __init__(self, core):
        super().__init__(daemon=True)
        self.core, self.latest = core, Latest()

    def run(self):
        conn = self.core._connection(5.0)
        conn.request("GET", "/api/v1/vision/front/stream?overlay=false", headers=self.core._headers())
        r = conn.getresponse()
        if r.status != 200:
            print("stream refused", r.status, r.read(300), flush=True)
            return
        buf = b""
        while True:
            chunk = r.read1(16384)
            if not chunk:
                return
            buf += chunk
            while True:
                m = self.HDR.search(buf)
                a = buf.find(b"\xff\xd8", m.end()) if m else -1
                b = buf.find(b"\xff\xd9", a + 2) if a >= 0 else -1
                if b < 0:
                    break
                bgr = cv2.imdecode(np.frombuffer(buf[a:b + 2], np.uint8), cv2.IMREAD_COLOR)
                if bgr is not None:
                    self.latest.put((int(m.group(1)), float(m.group(2)), bgr))
                buf = buf[b + 2:]


class Guard(threading.Thread):
    """Polls GET /sensors/lidar on its own connection; latest (ok, detail, time)."""

    def __init__(self, core, linear, forward_deg):
        super().__init__(daemon=True)
        self.core, self.linear, self.forward_deg, self.latest = core, linear, forward_deg, Latest()

    def run(self):
        while True:
            s, scan = self.core.call("GET", "/sensors/lidar", timeout=1.0, attempts=1)
            if s == 200 and isinstance(scan, dict):
                ok, detail = guard_check(scan, self.linear, self.forward_deg)
                self.latest.put((ok, detail, time.time()))
            time.sleep(GUARD_PERIOD_S)


# --- loop -----------------------------------------------------------------------------------

class Model:
    def __init__(self, model_dir, threads=2):
        import onnxruntime as ort
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads   # Pi 4 cores under the robot's load: 2 was fastest
        self.manifest = load_manifest(model_dir)
        verify_files(self.manifest)
        path = self.manifest.onnx_file()
        self.session = ort.InferenceSession(str(path), options, providers=["CPUExecutionProvider"])
        self.input = self.session.get_inputs()[0].name
        self.classes = self.manifest.classes

    def labels(self, bgr):
        x = lane_mask.preprocess(bgr, self.manifest.input)
        logits = self.session.run(None, {self.input: x})[0]
        return logits[0].argmax(axis=0)


def run(args, core, model, lim):
    out = Path(args.out)
    (out / "frames").mkdir(parents=True, exist_ok=True)
    deg, source = lidar_forward_deg(args.device, args.lidar_forward_deg)
    print(f"LiDAR forward {deg:.1f} deg from {source}", flush=True)
    frames = RosFrames(args.topic) if args.source == "ros" else StreamFrames(core.clone())
    guard = Guard(core.clone(), lim.linear, deg)
    frames.start()
    guard.start()
    rows, last_seq, result, recording, driving = [], None, None, False, False
    log = open(out / "cycles.jsonl", "a", encoding="utf-8")
    try:
        t_wait = time.time()
        while frames.latest.get() is None or guard.latest.get() is None:
            if time.time() - t_wait > 10:
                raise SystemExit("no frame or LiDAR scan within 10 s")
            time.sleep(0.05)
        if args.record:
            rec_start(core)
            recording = True
        if args.drive:
            s, b = core.call("POST", "/mode", {"mode": "MANUAL"})
            if s != 200:
                raise SystemExit(f"MANUAL refused {s} {b}")
            driving = True
        t0 = time.time()
        while True:
            tc = time.time()
            seq, stamp, bgr = frames.latest.get()
            infer_ms = None
            if seq != last_seq:
                ti = time.time()
                labels = model.labels(bgr)
                infer_ms = (time.time() - ti) * 1e3
                target, fraction = near_target(labels, model.classes)
                branch, branches = pick_branch(target)
                result = (seq, stamp, fraction, lateral_error(branch), branches)
                cv2.imwrite(str(out / "frames" / f"{seq}.jpg"), bgr)
                last_seq = seq
            seq, stamp, fraction, error, branches = result
            g_ok, g_detail, g_t = guard.latest.get()
            guard_ok = g_ok and time.time() - g_t <= GUARD_STALE_S
            age = time.time() - stamp
            v, w, reason = command(fraction, error, age, guard_ok, time.time() - t0, lim)
            sent = None
            if args.drive:
                sent = core.call("POST", "/teleop", {"linear": v, "angular": w}, timeout=0.4, attempts=1)[0]
                if sent != 200 and reason is None:
                    reason = f"teleop_{sent}"
            row = {"t": round(tc - t0, 3), "seq": seq, "age_ms": round(age * 1e3), "infer_ms":
                   None if infer_ms is None else round(infer_ms, 1), "fraction": round(fraction, 3),
                   "error": None if error is None else round(error, 3), "branches": branches,
                   "v": v, "w": round(w, 3), "guard": guard_ok, **g_detail, "sent": sent, "reason": reason}
            rows.append(row)
            log.write(json.dumps(row) + "\n")
            log.flush()
            print(json.dumps(row), flush=True)
            if reason == "time_cap" or (args.drive and reason):
                break
            time.sleep(max(0.0, PERIOD_S - (time.time() - tc)))
    finally:
        if driving:
            core.call("POST", "/teleop", {"linear": 0.0, "angular": 0.0})
            for _ in range(3):
                code = core.call("POST", "/mode", {"mode": "IDLE"})[0]
                if code == 200:
                    break
                time.sleep(0.5)
            print("mode IDLE", code, flush=True)
        if recording:
            rec_stop(core)
        log.close()
    return rows


def summary(rows):
    def pct(vals, q):
        vals = sorted(v for v in vals if v is not None)
        return None if not vals else vals[min(len(vals) - 1, int(q * len(vals)))]
    reasons = {}
    for r in rows:
        reasons[r["reason"]] = reasons.get(r["reason"], 0) + 1
    return {"cycles": len(rows), "frames": len({r["seq"] for r in rows}),
            "infer_ms_p50": pct([r["infer_ms"] for r in rows], 0.5), "infer_ms_p95": pct([r["infer_ms"] for r in rows], 0.95),
            "age_ms_p50": pct([r["age_ms"] for r in rows], 0.5), "age_ms_p95": pct([r["age_ms"] for r in rows], 0.95),
            "fraction_p50": pct([r["fraction"] for r in rows], 0.5), "error_p50": pct([r["error"] for r in rows], 0.5),
            "reasons": reasons}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--robot", default="127.0.0.1", help="CORE address (default: on the robot)")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--token-file", help=f"Operator token file (env {TOKEN_ENV})")
    tls = ap.add_mutually_exclusive_group(required=True)
    tls.add_argument("--ca-file")
    tls.add_argument("--insecure", action="store_true")
    ap.add_argument("--model", required=True, help="folder with model_manifest.json and the ONNX file")
    ap.add_argument("--source", choices=("ros", "stream"), default="ros")
    ap.add_argument("--topic", help="raw Image topic for --source ros, e.g. /<ns>/camera/front")
    ap.add_argument("--drive", action="store_true", help="send the commands (default: dry run)")
    ap.add_argument("--record", action="store_true", help="CORE recording for the run")
    ap.add_argument("--max-s", type=float, default=Limits.max_s)
    ap.add_argument("--linear", type=float, default=Limits.linear)
    ap.add_argument("--max-angular", type=float, default=Limits.max_angular)
    ap.add_argument("--gain", type=float, default=Limits.gain)
    ap.add_argument("--min-fraction", type=float, default=Limits.min_fraction)
    ap.add_argument("--max-age-s", type=float, default=Limits.max_age_s)
    ap.add_argument("--threads", type=int, default=2, help="ONNX Runtime intra-op threads")
    ap.add_argument("--device", help="robot name in the PC calibration store")
    ap.add_argument("--lidar-forward-deg", type=float)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    if not 0 < args.linear <= 0.03 or not 0 < args.max_angular <= 0.4 or not 0 < args.max_s <= 120:
        ap.error("D-592 limits: 0 < linear <= 0.03 m/s, 0 < max-angular <= 0.4 rad/s, max-s <= 120")
    if args.source == "ros" and not args.topic:
        ap.error("--source ros needs --topic")
    token_file = args.token_file or os.environ.get(TOKEN_ENV)
    if not token_file:
        ap.error(f"pass --token-file or set {TOKEN_ENV}")
    lim = Limits(args.linear, args.max_angular, args.gain, args.min_fraction, args.max_age_s, args.max_s)
    core = Core(args.robot, Path(token_file).read_text(encoding="utf-8").strip(), args.port,
                tls_context(args.ca_file, args.insecure))
    model = Model(args.model, args.threads)
    rows = run(args, core, model, lim)
    s = summary(rows)
    Path(args.out, "summary.json").write_text(json.dumps({"args": vars(args), **s}, indent=1), encoding="utf-8")
    print("SUMMARY", json.dumps(s), flush=True)


if __name__ == "__main__":
    main()
