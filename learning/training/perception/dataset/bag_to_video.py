"""Turn a recording session's camera topic into a lossy video plus a per-frame sidecar.

Usage: bag_to_video.py <session> [--out data/teleop/learning] [--codec hevc|h264] [--crf N]

<session> is a folder with session.json and bag/*.mcap (D-356 recording). Writes
    <out>/teleop_<device>_<UTC stamp>.mp4       every camera frame, native size, CFR
    <out>/teleop_<device>_<UTC stamp>.jsonl     one row per video frame, same order
    <out>/teleop_<device>_<UTC stamp>.json      session.json + conversion metadata
    <out>/teleop_<device>_<UTC stamp>.scan.npz  latest LiDAR scan per frame (if recorded)
The video is CFR at the mean camera rate. The camera may be raw (camera/front) or JPEG
(camera/front/compressed). extract.py reads this set like a session.

Sidecar row i (JSON, one line) describes decoded frame i. Two clocks: the camera header
stamp (when the image was captured) and the bag log time (when the recorder got it).
    index     int     decoded frame number, 0-based, = mp4 frame order
    t         float   camera header stamp, seconds
    stamp_ns  int     camera header stamp, ns
    log_ns    int     bag log time of the image, ns
    side      dict    per side topic, null when no message qualifies:
      cmd_vel                     {"linear" m/s, "angular" rad/s}
      teleop/intent               CORE's teleop decision (rosy.teleop.intent/1 JSON, D-411)
      odom                        {"x" m, "y" m, "yaw" rad}
      scan                        {"stamp_ns"}; the ranges are row i of .scan.npz
      line/keep_debug            selected boundaries, strategy, target and paint source
                                  (unreviewed diagnostics, never ground truth)
      ir_sensor/range             {"left", "centre", "right"} raw floor-IR ADC counts
                                  (0-4095). Not the ultrasonic range.
      line/observation,
      perception/learned/shadow   the decoded JSON payload plus "stamp_ns" (int ns, the
                                  payload's own "stamp", = its source image's header stamp)
    dt        dict    per side topic: side log time - frame log time, seconds, or null
    motion    dict    {"moving", "commanded", "v" m/s, "w" rad/s} from the odom of the
                      MOTION_WINDOW_S before the frame's log time and the current cmd_vel
Which side message a frame gets (two classes, agreed with the D-356/D-373 owner):
  stamped evidence (STAMPED_TOPICS) is published after inference on a given image, so it
    attaches to the frame whose header stamp equals the payload stamp within STAMP_TOL_NS
    (1 us: the payload stamp is float seconds, ~240 ns resolution at epoch; real CAMERA_LINE
    stamps match within 256 ns while IR_LINE stamps fall 0.05-0.78 ms away), only from the
    source named in STAMPED_SOURCES (line/observation: CAMERA_LINE, the one extract.py keeps),
    and only when it is logged after that frame's capture (header stamp) and at most
    EVIDENCE_WINDOW_S after the frame's log time. The lower bound is the capture, not the
    frame's log time: on 8kcn 45 of 2258 observations reach the recorder 37-61 us before
    their own image does (2026-09-30), and nothing can be computed before the capture;
  every other topic takes the latest message at or before the frame's log time, no older
    than --max-gap (dt <= 0), so no later sample leaks into a frame.
"""
import argparse
import bisect
import json
import math
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np

import extract
from control.recording import (
    CAMERA_TOPIC, IR_RANGE_TOPIC, KEEP_DEBUG_TOPIC, SHADOW_TOPIC, SIDE_TOPICS, ir_range_sample)

SCHEMA = "rosy.teleop.video/1"
ODOM_TOPIC = "odom"
SCAN_TOPIC = "scan"
# D-411 Pilot recordings: CORE's teleop decision per command (core_common.protocol.recording;
# not imported, and not in control.recording SIDE_TOPICS, the snapshot recorder's contract).
INTENT_TOPIC = "teleop/intent"
PIX_FMT = "yuv420p"
# Evidence stamped with its source image's header stamp (see the module docstring).
STAMPED_TOPICS = ("line/observation", SHADOW_TOPIC, KEEP_DEBUG_TOPIC)
STAMP_TOL_NS = 1_000             # payload stamp vs frame header stamp
# Only this payload "source" is a frame's stamped evidence (IR_LINE shares the topic).
STAMPED_SOURCES = {"line/observation": "CAMERA_LINE"}
EVIDENCE_WINDOW_S = 0.5          # evidence log time may trail its frame's by this much
# Chosen by the D-356 codec study (2026-09-30 addendum): H.265 for archive, H.264 when a
# player or decoder without HEVC must read it. accurate_rnd halves the BGR->YUV rounding
# bias of the default swscale path at no size cost.
SWS = "scale=flags=accurate_rnd+full_chroma_int"
CODECS = {
    "hevc": {"encoder": "libx265", "crf": 24, "preset": "slow",
             "extra": ["-tag:v", "hvc1", "-x265-params", "log-level=error"]},
    "h264": {"encoder": "libx264", "crf": 23, "preset": "slow", "extra": []},
}
DEFAULT_OUT = Path(__file__).resolve().parents[4] / "data" / "teleop" / "learning"
# Moving vs idle: odom displacement over MOTION_WINDOW_S around the frame, or a command.
# Teleop runs at 0.03 m/s and 0.1 rad/s; idle odom noise on 8kcn stays below
# 0.005 m/s and 0.008 rad/s at p99 (2026-09-30 sessions).
MOTION_WINDOW_S = 0.5
MOVING_V = 0.01    # m/s
MOVING_W = 0.03    # rad/s
CMD_V = 0.01       # m/s
CMD_W = 0.05       # rad/s


def _twist(msg):
    return {"linear": msg.linear.x, "angular": msg.angular.z}


def _pose(msg):
    p, q = msg.pose.pose.position, msg.pose.pose.orientation
    yaw = math.atan2(2.0 * (q.w * q.z + q.x * q.y), 1.0 - 2.0 * (q.y * q.y + q.z * q.z))
    return {"x": p.x, "y": p.y, "yaw": yaw}


def _stamp_ns(msg) -> int:
    return msg.header.stamp.sec * 1_000_000_000 + msg.header.stamp.nanosec


def _side_name(topic: str):
    return next((n for n in (*SIDE_TOPICS, KEEP_DEBUG_TOPIC, ODOM_TOPIC, SCAN_TOPIC,
                             INTENT_TOPIC, IR_RANGE_TOPIC)
                 if extract._topic_is(topic, n)), None)


def _side_payload(name, schema, msg):
    if name == "cmd_vel":
        return _twist(msg)
    if name == ODOM_TOPIC:
        return _pose(msg)
    if name == IR_RANGE_TOPIC:
        return ir_range_sample(getattr(msg, "data", ()))
    return extract._side_value(schema, msg)


def _is_camera(topic: str) -> bool:
    return extract._topic_is(topic, CAMERA_TOPIC) or \
        extract._topic_is(topic, CAMERA_TOPIC + "/compressed")


def _messages(files, camera_only: bool):
    """Yields (relative topic, log ns, schema name, decoded msg) in bag order."""
    from mcap.reader import make_reader
    from mcap_ros2.decoder import DecoderFactory
    for f in files:
        with open(f, "rb") as fh:
            reader = make_reader(fh, decoder_factories=[DecoderFactory()])
            for schema, ch, message, msg in reader.iter_decoded_messages():
                if _is_camera(ch.topic):
                    yield CAMERA_TOPIC, message.log_time, schema.name, msg
                elif not camera_only:
                    name = _side_name(ch.topic)
                    if name is not None:
                        yield name, message.log_time, schema.name, msg


def _frame(schema: str, msg):
    """bgr ndarray from an Image or CompressedImage, or None when the payload is malformed."""
    if schema.endswith("CompressedImage"):
        return cv2.imdecode(np.frombuffer(bytes(msg.data), np.uint8), cv2.IMREAD_COLOR)
    try:
        return extract.image_to_bgr(msg.encoding, msg.width, msg.height, msg.step, bytes(msg.data))
    except ValueError:
        return None


def _camera_frames(files, camera_only: bool):
    """Valid, log-time-monotonic frames as (log ns, schema, msg, bgr); others as bgr None."""
    last = None
    for name, log_ns, schema, msg in _messages(files, camera_only):
        if name != CAMERA_TOPIC:
            yield name, log_ns, schema, msg, None
            continue
        bgr = _frame(schema, msg)
        if bgr is None or (last is not None and log_ns < last):
            yield CAMERA_TOPIC, log_ns, schema, msg, None
            continue
        last = log_ns
        yield CAMERA_TOPIC, log_ns, schema, msg, bgr


def first_pass(files):
    """Frame stamps (kept frames only), side-topic series and LiDAR scans."""
    frames, side, skipped, size = [], {}, 0, None
    scans = {"log_ns": [], "stamp_ns": [], "ranges": [], "meta": None}
    for name, log_ns, schema, msg, bgr in _camera_frames(files, camera_only=False):
        if name == SCAN_TOPIC:
            scans["log_ns"].append(log_ns)
            scans["stamp_ns"].append(_stamp_ns(msg))
            scans["ranges"].append(np.asarray(msg.ranges, np.float16))
            if scans["meta"] is None:
                scans["meta"] = {k: float(getattr(msg, k)) for k in
                                 ("angle_min", "angle_max", "angle_increment",
                                  "range_min", "range_max")}
            continue
        if name != CAMERA_TOPIC:
            value = _side_payload(name, schema, msg)
            if name == IR_RANGE_TOPIC and value is None:
                continue  # not three ADC counts: do not invent a sample
            series = side.setdefault(name, ([], []))
            series[0].append(log_ns)
            series[1].append(value)
            continue
        if bgr is None:
            skipped += 1
            continue
        if size is None:
            size = bgr.shape[1], bgr.shape[0]
        elif (bgr.shape[1], bgr.shape[0]) != size:
            raise SystemExit(f"camera size changed mid-session: {size} -> {bgr.shape[1::-1]}")
        frames.append({"log_ns": log_ns, "stamp_ns": _stamp_ns(msg)})
    return frames, side, skipped, size, (scans if scans["log_ns"] else None)


def latest(times, t, max_gap_ns):
    """Index of the last element of sorted `times` at or before t, or None if there is none
    or it is older than max_gap_ns."""
    j = bisect.bisect_right(times, t) - 1
    if j < 0 or t - times[j] > max_gap_ns:
        return None
    return j


def motion(t_ns, odom, cmd):
    """{"moving", "commanded", "v", "w"} over the MOTION_WINDOW_S of odom up to t_ns (no
    later samples); odom speeds are null without two samples in the window."""
    v = w = None
    if odom is not None:
        times, poses = odom
        a = bisect.bisect_left(times, t_ns - int(MOTION_WINDOW_S * 1e9))
        b = bisect.bisect_right(times, t_ns) - 1
        if b > a and times[b] > times[a]:
            dt = (times[b] - times[a]) / 1e9
            p, q = poses[a], poses[b]
            v = math.hypot(q["x"] - p["x"], q["y"] - p["y"]) / dt
            dyaw = (q["yaw"] - p["yaw"] + math.pi) % (2 * math.pi) - math.pi
            w = abs(dyaw) / dt
    commanded = cmd is not None and (abs(cmd["linear"]) > CMD_V or abs(cmd["angular"]) > CMD_W)
    moving = commanded or (v is not None and (v > MOVING_V or w > MOVING_W))
    return {"moving": moving, "commanded": commanded,
            "v": None if v is None else round(v, 4), "w": None if w is None else round(w, 4)}


def payload_stamp_ns(value):
    """The JSON payload's "stamp" (seconds) as int ns, or None."""
    stamp = value.get("stamp") if isinstance(value, dict) else None
    if isinstance(stamp, bool) or not isinstance(stamp, (int, float)) or not math.isfinite(stamp):
        return None
    return int(round(stamp * 1e9))


def stamped_index(times, series, source=None):
    """Sorted [(payload stamp ns, log ns, value)] of the messages that carry a stamp
    (and, when given, the payload "source")."""
    out = []
    for log_ns, value in zip(times, series):
        if source is not None and not (isinstance(value, dict) and value.get("source") == source):
            continue
        ps = payload_stamp_ns(value)
        if ps is not None:
            out.append((ps, log_ns, value))
    out.sort(key=lambda e: (e[0], e[1]))
    return out


def evidence_for(index, keys, frame):
    """The first-logged message whose payload stamp is the frame's header stamp (+-tol),
    logged after the frame's capture and at most EVIDENCE_WINDOW_S after the frame's log
    time; (log ns, value) or None."""
    lo = bisect.bisect_left(keys, frame["stamp_ns"] - STAMP_TOL_NS)
    hi = bisect.bisect_right(keys, frame["stamp_ns"] + STAMP_TOL_NS)
    window = int(EVIDENCE_WINDOW_S * 1e9)
    best = None
    for ps, log_ns, value in index[lo:hi]:
        in_window = frame["stamp_ns"] <= log_ns <= frame["log_ns"] + window
        if in_window and (best is None or log_ns < best[0]):
            best = (log_ns, {**value, "stamp_ns": ps})
    return best


def sidecar_rows(frames, side, max_gap_s: float, scans=None):
    gap = int(max_gap_s * 1e9)
    stamped = {}
    for name in STAMPED_TOPICS:
        if name in side:
            index = stamped_index(*side[name], source=STAMPED_SOURCES.get(name))
            stamped[name] = (index, [e[0] for e in index])
    for i, f in enumerate(frames):
        values, dts = {}, {}
        for name, (times, series) in side.items():
            if name in stamped:
                hit = evidence_for(*stamped[name], f)
                values[name] = None if hit is None else hit[1]
                dts[name] = None if hit is None else round((hit[0] - f["log_ns"]) / 1e9, 4)
                continue
            j = latest(times, f["log_ns"], gap)
            values[name] = None if j is None else series[j]
            dts[name] = None if j is None else round((times[j] - f["log_ns"]) / 1e9, 4)
        if scans is not None:
            # the ranges live in the .scan.npz at row i; the row only says which scan
            j = latest(scans["log_ns"], f["log_ns"], gap)
            values[SCAN_TOPIC] = None if j is None else {"stamp_ns": scans["stamp_ns"][j]}
            dts[SCAN_TOPIC] = None if j is None else round((scans["log_ns"][j] - f["log_ns"]) / 1e9, 4)
        yield {"index": i, "t": f["stamp_ns"] / 1e9, "stamp_ns": f["stamp_ns"],
               "log_ns": f["log_ns"], "side": values, "dt": dts,
               "motion": motion(f["log_ns"], side.get(ODOM_TOPIC), values.get("cmd_vel"))}


def scan_arrays(frames, scans, max_gap_s: float) -> dict:
    """npz payload: ranges[i] is the latest scan at or before frame i (NaN row when none)."""
    gap = int(max_gap_s * 1e9)
    beams = max(len(r) for r in scans["ranges"])
    ranges = np.full((len(frames), beams), np.nan, np.float16)
    stamp = np.zeros(len(frames), np.int64)
    dt = np.full(len(frames), np.nan, np.float32)
    for i, f in enumerate(frames):
        j = latest(scans["log_ns"], f["log_ns"], gap)
        if j is None:
            continue
        r = scans["ranges"][j]
        ranges[i, :len(r)] = r
        stamp[i] = scans["stamp_ns"][j]
        dt[i] = (scans["log_ns"][j] - f["log_ns"]) / 1e9
    return {"ranges": ranges, "scan_stamp_ns": stamp, "dt": dt,
            **{k: np.float32(v) for k, v in scans["meta"].items()}}


def mean_fps(frames) -> float:
    if len(frames) < 2:
        return 1.0
    span = (frames[-1]["stamp_ns"] - frames[0]["stamp_ns"]) / 1e9
    return round((len(frames) - 1) / span, 3) if span > 0 else 1.0


def ffmpeg_cmd(out: Path, size, fps: float, codec: str, crf: int, preset: str) -> list:
    spec = CODECS[codec]
    return ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
            "-s", f"{size[0]}x{size[1]}", "-r", str(fps), "-i", "-", "-vf", SWS,
            "-c:v", spec["encoder"], "-preset", preset, "-crf", str(crf), "-pix_fmt", PIX_FMT,
            *spec["extra"], "-fps_mode", "passthrough", "-movflags", "+faststart", str(out)]


def encode(files, cmd, expected: int) -> int:
    """Second pass: pipe the same frames first_pass() kept into ffmpeg."""
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    n = 0
    try:
        for _name, _log_ns, _schema, _msg, bgr in _camera_frames(files, camera_only=True):
            if bgr is None:
                continue
            proc.stdin.write(bgr.tobytes())
            n += 1
    finally:
        proc.stdin.close()
        code = proc.wait()
    if code != 0:
        raise SystemExit(f"ffmpeg failed ({code}): {' '.join(cmd)}")
    if n != expected:
        raise SystemExit(f"second pass saw {n} frames, first pass {expected}")
    return n


def count_frames(video: Path) -> int:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets",
                          "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", str(video)],
                         capture_output=True, text=True, check=True).stdout
    return int(out.strip().split(",")[0])


def output_stem(session: Path, meta: dict) -> str:
    device = re.sub(r"[^A-Za-z0-9_.-]", "-", str(meta.get("device") or "unknown"))
    m = re.match(r"(\d{8}T\d{6}Z)", session.name)
    stamp = m.group(1) if m else re.sub(r"[^0-9TZ]", "", str(meta.get("started_at", "")))[:15] + "Z"
    return f"teleop_{device}_{stamp}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("session")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--codec", choices=sorted(CODECS), default="hevc")
    ap.add_argument("--crf", type=int)
    ap.add_argument("--preset")
    ap.add_argument("--max-gap", type=float, default=0.5,
                    help="side values further than this (s) from a frame are null")
    ap.add_argument("--force", action="store_true", help="overwrite existing outputs")
    args = ap.parse_args(argv)
    session, out = Path(args.session), Path(args.out)
    files = extract._mcap_files(session)
    if not files:
        print(f"no .mcap files under {session / 'bag'}", file=sys.stderr)
        return 1
    if shutil.which("ffmpeg") is None:
        raise SystemExit("ffmpeg not on PATH")
    meta = json.loads((session / "session.json").read_text(encoding="utf-8")) \
        if (session / "session.json").is_file() else {}
    stem = output_stem(session, meta)
    video, rows_path, meta_path, scan_path = (
        out / f"{stem}{ext}" for ext in (".mp4", ".jsonl", ".json", ".scan.npz"))
    if not args.force and any(p.exists() for p in (video, rows_path, meta_path, scan_path)):
        print(f"{stem}.* already in {out} (use --force)", file=sys.stderr)
        return 1
    spec = CODECS[args.codec]
    crf = spec["crf"] if args.crf is None else args.crf
    preset = args.preset or spec["preset"]

    frames, side, skipped, size, scans = first_pass(files)
    if not frames:
        print("no camera frames in the session", file=sys.stderr)
        return 1
    fps = mean_fps(frames)
    out.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    encode(files, ffmpeg_cmd(video, size, fps, args.codec, crf, preset), len(frames))
    encode_s = time.perf_counter() - started
    decoded = count_frames(video)
    if decoded != len(frames):
        raise SystemExit(f"{video} holds {decoded} frames, sidecar would hold {len(frames)}")
    moving = 0
    with open(rows_path, "w", encoding="utf-8") as fh:
        for row in sidecar_rows(frames, side, args.max_gap, scans):
            moving += row["motion"]["moving"]
            fh.write(extract._dumps(row) + "\n")
    if scans is not None:
        np.savez_compressed(scan_path, **scan_arrays(frames, scans, args.max_gap))
    elif scan_path.exists():
        scan_path.unlink()  # --force over an older conversion that had one
    raw_bytes = sum(f.stat().st_size for f in files)
    duration = (frames[-1]["stamp_ns"] - frames[0]["stamp_ns"]) / 1e9
    topics = {k: len(v[0]) for k, v in side.items()} | {CAMERA_TOPIC: len(frames)}
    if scans is not None:
        topics[SCAN_TOPIC] = len(scans["log_ns"])
    doc = {
        "schema": SCHEMA,
        "session": meta,
        "source": {"session": session.name, "bag_bytes": raw_bytes, "topics": topics,
                   "skipped_frames": skipped},
        "video": {"file": video.name, "codec": args.codec, "encoder": spec["encoder"],
                  "crf": crf, "preset": preset, "pix_fmt": PIX_FMT, "width": size[0],
                  "height": size[1], "frames": len(frames), "fps": fps,
                  "duration_s": round(duration, 3), "bytes": video.stat().st_size,
                  "encode_s": round(encode_s, 2)},
        "sidecar": {"file": rows_path.name,
                    "match": "stamped evidence: payload stamp = frame header stamp (+-1 us), "
                             "logged after the capture and <= 0.5 s after the frame's "
                             "log time; other topics: latest at or "
                             "before the frame's bag log time",
                    "t": "camera header stamp (s)",
                    "max_gap_s": args.max_gap, "dt": "side log time minus frame log time (s)",
                    "moving_frames": moving,
                    "motion": {"window_s": MOTION_WINDOW_S, "odom_v": MOVING_V,
                               "odom_w": MOVING_W, "cmd_v": CMD_V, "cmd_w": CMD_W}},
        "scan": None if scans is None else {
            "file": scan_path.name, "rows": "frame index", "dtype": "float16",
            "beams": int(max(len(r) for r in scans["ranges"])), **scans["meta"]},
    }
    meta_path.write_text(json.dumps(extract._clean(doc), indent=1, allow_nan=False) + "\n",
                         encoding="utf-8")
    mb = video.stat().st_size / 1e6
    print(f"{len(frames)} frames ({skipped} skipped, {moving} moving) {fps} fps -> {video} "
          f"{mb:.1f} MB ({raw_bytes / 1e6 / max(mb, 1e-9):.0f}x smaller than the bag)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
