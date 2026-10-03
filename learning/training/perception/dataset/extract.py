"""Extract training frames from an MP4 or a robot recording session (MCAP).

Usage: extract.py <source> --out data/perception/frames/<name>
<source> is a video file (cv2-readable) or a session folder with bag/*.mcap. A video made
by bag_to_video.py is read with its <stem>.jsonl sidecar (stamps, side data) and
<stem>.json metadata (session name, session.json).

Each row: t = the camera header stamp (s), stamp_ns / log_ns = header stamp and bag
log time (ns), side = side data, dt = side log time - frame log time (s) per topic.
One two-class clock rule for both inputs (D-356 addendum, D-373 decision 9):

(a) Side topics that carry the stamp of the image they judged (STAMPED_SIDE_TOPICS:
    the shadow result, line/observation with source CAMERA_LINE only; payload
    `stamp` in s from MCAP, the entry's `stamp_ns` in a sidecar) attach to the
    frame whose header stamp equals it (within STAMP_TOL_S, 1 us) if logged
    after that frame's capture (its
    header stamp) and at most SIDE_LOOKAHEAD_S after the frame's log time;
    otherwise to no frame. The lower bound is the capture, not the frame's log
    time: a camera observation can reach the recorder tens of microseconds
    before its own image does. A sidecar whose stamped entries carry no
    `stamp_ns` (written before that field) attaches no stamped evidence: null.
(b) Every other side topic (cmd_vel, odom, scan, ...) is the latest message
    logged at or before the frame's log time; a later one is never used.
    From MCAP odom is {stamp_ns, log_ns, x, y, yaw, linear, angular} (pose and
    twist of nav_msgs/Odometry).
    From MCAP the LiDAR scan (sensor_msgs/LaserScan) is attached as {stamp,
    angle_min, angle_increment, range_min, range_max, ranges} (non-finite
    ranges -> null); a sidecar carries {stamp_ns}, the ranges are in
    <stem>.scan.npz.

camera/front/compressed is preferred: when a session has it, raw camera/front
frames are not extracted.

Known limits of the matching: line/observation from IR_LINE is stamped with
odometry time, which can land within a millisecond of an image stamp (9dfk,
2026-10-01: 5 of 2387 within 0.05-0.78 ms), so only CAMERA_LINE counts as
evidence of an image; real CAMERA_LINE stamps equal the image stamp within
256 ns. The shadow node compares its frame with the nearest rule
answer within 0.2 s when the exact one is missing, so its rule_error can
belong to a neighbouring frame (control.sensing.perception.learned.shadow).

A truncated or corrupt MCAP file (a snapshot recovered after a crash) keeps
the messages read before the damage and is counted in the summary line.
"""
import argparse
import json
from collections import deque
import os
import math
import re
import shutil
import sys
from types import SimpleNamespace
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src" / "runtime" / "sensing"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "contracts" / "foundation"))  # core_common (D-424)

from frames import FrameSelector  # noqa: E402
from control.recording import (  # noqa: E402
    CAMERA_TOPIC, COMPRESSED_CAMERA_TOPIC, ODOM_TOPIC, SCAN_TOPIC, SHADOW_TOPIC, SIDE_TOPICS)
from control.sensing.perception.image_frame import image_msg_to_frame  # noqa: E402

STRING_SCHEMA = "std_msgs/msg/String"
JPEG_Q = 95
# Class (a) of the clock rule: payloads carrying the stamp of the image they judged.
STAMPED_SIDE_TOPICS = (SHADOW_TOPIC, "line/observation")
SIDE_LOOKAHEAD_S = 0.5  # a stamped side message may be logged this long after its frame
STAMP_TOL_S = 1e-6  # equal stamps: within 1 us (JSON float seconds keep ~0.2 us at epoch scale)
CAMERA_LINE = "CAMERA_LINE"  # the only line/observation source that judged an image


def _is_image_evidence(name, value) -> bool:
    return name != "line/observation" or (isinstance(value, dict)
                                          and value.get("source") == CAMERA_LINE)


def image_to_bgr(encoding: str, width: int, height: int, step: int, data: bytes) -> np.ndarray:
    # Shared with the camera observers so extraction sees what perception saw.
    # It requires tightly packed rows (step == width * channels).
    msg = SimpleNamespace(encoding=encoding, width=width, height=height, data=data)
    frame = image_msg_to_frame(msg)
    return cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR) if frame.ndim == 2 else np.ascontiguousarray(frame)


def _jpeg(bgr) -> bytes:
    ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, JPEG_Q])
    if not ok:
        raise RuntimeError("JPEG encode failed")
    return buf.tobytes()


def _sidecar(path: Path):
    """bag_to_video.py rows (<stem>.jsonl) and metadata (<stem>.json), or (None, None)."""
    rows_path = path.with_suffix(".jsonl")
    if not rows_path.is_file():
        return None, None
    rows = [json.loads(line) for line in rows_path.read_text(encoding="utf-8").splitlines() if line]
    meta_path = path.with_suffix(".json")
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else None
    return rows, meta


def _check_sidecar(path: Path, rows, meta) -> None:
    """Refuse a sidecar whose row count differs from the metadata or container frame count."""
    counts = {}
    if meta and (meta.get("video") or {}).get("frames") is not None:
        counts["metadata"] = int(meta["video"]["frames"])
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise SystemExit(f"cannot open video: {path}")
    counts["container"] = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    bad = {k: v for k, v in counts.items() if v != len(rows)}
    if bad:
        raise SystemExit(f"{path}: sidecar has {len(rows)} rows but "
                         + ", ".join(f"{k} says {v} frames" for k, v in bad.items()))


def _evidence_stamp_ns(value):
    """Image stamp (ns) of a stamped sidecar entry, or None (old sidecar, no stamp_ns)."""
    ns = value.get("stamp_ns") if isinstance(value, dict) else None
    return ns if isinstance(ns, int) and not isinstance(ns, bool) else None


def _in_window(e_log_ns, stamp_ns, log_ns) -> bool:
    """Clock rule (a): logged after the frame's capture, at most SIDE_LOOKAHEAD_S
    after its log time."""
    return stamp_ns <= e_log_ns <= log_ns + round(SIDE_LOOKAHEAD_S * 1e9)


def sidecar_side(rows):
    """(side, dt) per sidecar row under the clock rule. Class (b) values are the
    sidecar's own (latest at or before the frame's log time). Class (a) entries
    are gathered from every row and attached again by stamp and window, so a
    sidecar that holds a frame's evidence in a later row gives the same result."""
    tol_ns = round(STAMP_TOL_S * 1e9)
    evidence = {name: [] for name in STAMPED_SIDE_TOPICS}  # (stamp ns, log ns, value)
    seen = set()
    for r in rows:
        side, dts = r.get("side") or {}, r.get("dt") or {}
        for name in STAMPED_SIDE_TOPICS:
            value = side.get(name)
            stamp_ns = _evidence_stamp_ns(value)
            if (stamp_ns is None or r.get("log_ns") is None or dts.get(name) is None
                    or not _is_image_evidence(name, value)):
                continue
            e_log = r["log_ns"] + round(dts[name] * 1e9)
            if (name, stamp_ns, e_log) not in seen:
                seen.add((name, stamp_ns, e_log))
                evidence[name].append((stamp_ns, e_log, value))
    out = []
    for r in rows:
        side = {k: v for k, v in (r.get("side") or {}).items() if k not in STAMPED_SIDE_TOPICS}
        dts = {k: v for k, v in (r.get("dt") or {}).items() if k not in STAMPED_SIDE_TOPICS}
        stamp_ns, log_ns = r.get("stamp_ns"), r.get("log_ns")
        for name in STAMPED_SIDE_TOPICS:
            side[name], dts[name] = None, None
            if stamp_ns is None or log_ns is None:
                continue
            for e_stamp, e_log, value in evidence[name]:
                if abs(e_stamp - stamp_ns) <= tol_ns and _in_window(e_log, stamp_ns, log_ns):
                    side[name] = value
                    dts[name] = round((e_log - log_ns) / 1e9, 4)
                    break
        out.append((side, dts))
    return out


def _video_frames(path: Path, rows=None):
    """rows (sidecar) give frame i its recorded stamp and side data instead of POS_MSEC."""
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise SystemExit(f"cannot open video: {path}")
    attached = sidecar_side(rows) if rows is not None else None
    n = 0
    try:
        while True:
            ok, bgr = cap.read()
            if not ok:
                break
            if rows is None:
                yield cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0, bgr, {}, "jpg", {}
            elif n < len(rows):
                r = rows[n]
                side, dts = attached[n]
                extra = {k: r[k] for k in ("stamp_ns", "log_ns") if k in r}
                yield r["t"], bgr, side, "jpg", {**extra, "dt": dts}
            n += 1
    finally:
        cap.release()
    if rows is not None and n != len(rows):
        raise SystemExit(f"{path} decodes {n} frames but its sidecar has {len(rows)} rows")


def _jsonable(value):
    slots = getattr(value, "__slots__", None)
    if slots is not None:
        return {s.lstrip("_"): _jsonable(getattr(value, s)) for s in slots}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (bytes, bytearray)):
        return None
    return value if isinstance(value, (int, float, str, bool, type(None))) else str(value)


def _topic_is(topic: str, name: str) -> bool:
    """topic, under any namespace ("/pinky1/camera/front"), is the relative name."""
    topic = topic.lstrip("/")
    return topic == name or topic.endswith("/" + name)


def _side_value(schema_name: str, msg):
    """std_msgs/String payloads are JSON on our topics: decode them (raw text if not)."""
    if schema_name == STRING_SCHEMA:
        try:
            return json.loads(msg.data)
        except ValueError:
            return msg.data
    return _jsonable(msg)


def _mcap_files(session: Path):
    def key(p):
        m = re.search(r"(\d+)(?=\.mcap$)", p.name)
        return (int(m.group(1)) if m else -1, p.name)
    return sorted((session / "bag").glob("*.mcap"), key=key)


def _clean(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def _dumps(row) -> str:
    return json.dumps(_clean(row), allow_nan=False)


def _payload_stamp(value):
    stamp = value.get("stamp") if isinstance(value, dict) else None
    if isinstance(stamp, bool) or not isinstance(stamp, (int, float)):
        return None
    return float(stamp) if math.isfinite(stamp) else None


def _header_stamp_ns(msg):
    try:
        return int(msg.header.stamp.sec) * 1_000_000_000 + int(msg.header.stamp.nanosec)
    except AttributeError:
        return None


def _header_stamp(msg):
    ns = _header_stamp_ns(msg)
    return None if ns is None else ns / 1e9


def _scan_value(msg, stamp: float) -> dict:
    def num(v):
        v = float(v)
        return v if math.isfinite(v) else None
    return {"stamp": stamp, "angle_min": num(msg.angle_min),
            "angle_increment": num(msg.angle_increment), "range_min": num(msg.range_min),
            "range_max": num(msg.range_max), "ranges": [num(r) for r in msg.ranges]}


def _odom_value(msg, log_ns: int) -> dict:
    p, q = msg.pose.pose.position, msg.pose.pose.orientation
    yaw = math.atan2(2.0 * (q.w * q.z + q.x * q.y), 1.0 - 2.0 * (q.y * q.y + q.z * q.z))
    tw = getattr(getattr(msg, "twist", None), "twist", None)  # absent in a pose-only schema
    return {"stamp_ns": _header_stamp_ns(msg), "log_ns": int(log_ns), "x": float(p.x),
            "y": float(p.y), "yaw": yaw,
            "linear": None if tw is None else float(tw.linear.x),
            "angular": None if tw is None else float(tw.angular.z)}


def _has_compressed(files, make_reader) -> bool:
    for f in files:
        with open(f, "rb") as fh:
            try:
                summary = make_reader(fh).get_summary()
            except Exception:  # truncated file: no summary section
                summary = None
            if summary is not None:
                topics = [ch.topic for ch in summary.channels.values()]
            else:
                fh.seek(0)
                topics = []
                try:
                    for _, ch, _ in make_reader(fh).iter_messages():
                        topics.append(ch.topic)
                except Exception:  # damaged tail: the topics seen so far count
                    pass
            if any(_topic_is(t, COMPRESSED_CAMERA_TOPIC) for t in topics):
                return True
    return False


def _mcap_frames(files, skipped=None, truncated=None):
    """Frames as (t, item, side, ext, extra) under the clock rule (module docstring);
    t is the camera header stamp, the clock of bag_to_video sidecars and D-379."""
    try:
        from mcap.reader import make_reader
        from mcap_ros2.decoder import DecoderFactory
    except ImportError:
        raise SystemExit("MCAP extraction needs: pip install mcap mcap-ros2-support")
    prefer_compressed = _has_compressed(files, make_reader)
    latest = {}  # class (b): name -> (log ns, value), latest by log time
    early = deque()  # class (a) logged before its frame: (log ns, stamp, name, value)
    pending = deque()  # frames still inside their look-ahead window

    def ready(now):
        while pending and (now is None or pending[0]["log_t"] + SIDE_LOOKAHEAD_S < now):
            f = pending.popleft()
            for name in STAMPED_SIDE_TOPICS:  # no evidence of this image: null, as in a sidecar
                f["side"].setdefault(name, None)
                f["extra"]["dt"].setdefault(name, None)
            yield f["t"], f["item"], f["side"], f["ext"], f["extra"]

    def decoded(f):
        """Messages of one file; a damaged file ends early instead of failing."""
        with open(f, "rb") as fh:
            try:
                reader = make_reader(fh, decoder_factories=[DecoderFactory()])
                yield from reader.iter_decoded_messages()
            except Exception as exc:
                print(f"{f.name}: truncated or corrupt ({type(exc).__name__}); "
                      "kept what was read", file=sys.stderr)
                if truncated is not None:
                    truncated[0] += 1

    for f in files:
        for schema, ch, message, msg in decoded(f):
            t = message.log_time / 1e9
            yield from ready(t)
            while early and early[0][0] / 1e9 + SIDE_LOOKAHEAD_S < t:
                early.popleft()
            # Channels carry absolute, possibly namespaced topics.
            name = next((n for n in SIDE_TOPICS if _topic_is(ch.topic, n)), None)
            if name is not None:
                if name == SCAN_TOPIC:
                    value = _scan_value(msg, _header_stamp(msg))
                elif name == ODOM_TOPIC:
                    value = _odom_value(msg, message.log_time)
                else:
                    value = _side_value(schema.name, msg)
                if name not in STAMPED_SIDE_TOPICS:
                    latest[name] = (message.log_time, value)
                    continue
                stamp = _payload_stamp(value)
                if stamp is None or not _is_image_evidence(name, value):
                    continue  # no image stamp, or not about an image: no frame
                # Every pending frame was logged at most SIDE_LOOKAHEAD_S before now.
                frame = next((p for p in pending if p["stamp"] is not None
                              and abs(p["stamp"] - stamp) <= STAMP_TOL_S
                              and message.log_time >= p["extra"]["stamp_ns"]), None)
                if frame is not None:
                    if name not in frame["side"]:
                        frame["side"][name] = value
                        frame["extra"]["dt"][name] = round(
                            (message.log_time - frame["extra"]["log_ns"]) / 1e9, 4)
                else:
                    early.append((message.log_time, stamp, name, value))
                continue
            if _topic_is(ch.topic, COMPRESSED_CAMERA_TOPIC):
                ext = "png" if "png" in str(msg.format).lower() else "jpg"
                item = bytes(msg.data)
            elif _topic_is(ch.topic, CAMERA_TOPIC):
                if prefer_compressed:
                    continue
                try:
                    item = image_to_bgr(msg.encoding, msg.width, msg.height, msg.step,
                                        bytes(msg.data))
                except ValueError:  # malformed frame: count it, keep going
                    if skipped is not None:
                        skipped[0] += 1
                    continue
                ext = "jpg"
            else:
                continue
            stamp_ns = _header_stamp_ns(msg)
            stamp = None if stamp_ns is None else stamp_ns / 1e9
            side = {n: v for n, (_, v) in latest.items()}
            dts = {n: round((log_ns - message.log_time) / 1e9, 4)
                   for n, (log_ns, _) in latest.items()}
            if stamp is not None:
                for e_log, e_stamp, e_name, e_value in early:
                    # logged before this frame's log time, but not before its capture
                    if (abs(e_stamp - stamp) <= STAMP_TOL_S and e_name not in side
                            and e_log >= stamp_ns):
                        side[e_name] = e_value
                        dts[e_name] = round((e_log - message.log_time) / 1e9, 4)
            extra = {"stamp_ns": stamp_ns, "log_ns": message.log_time, "dt": dts}
            pending.append({"t": t if stamp is None else stamp, "log_t": t, "stamp": stamp,
                            "item": item, "side": side, "ext": ext, "extra": extra})
    yield from ready(None)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("source")
    ap.add_argument("--out", required=True)
    ap.add_argument("--min-interval", type=float, default=0.5)
    ap.add_argument("--max-hamming", type=int, default=4)
    args = ap.parse_args(argv)
    src, out = Path(args.source), Path(args.out)
    is_session = src.is_dir()
    skipped = [0]
    truncated = [0]
    video_meta = None
    if is_session:
        files = _mcap_files(src)
        if not files:
            print(f"no .mcap files under {src / 'bag'}", file=sys.stderr)
            return 1
        it = _mcap_frames(files, skipped, truncated)
        session = src.name
    else:
        rows, video_meta = _sidecar(src)
        if rows is not None:
            _check_sidecar(src, rows, video_meta)  # before any output is written
        it = _video_frames(src, rows)
        # A converted session keeps its session name, so build.py splits it with its bag.
        session = ((video_meta or {}).get("source") or {}).get("session")
    (out / "frames").mkdir(parents=True, exist_ok=True)
    sel = FrameSelector(args.min_interval, args.max_hamming)
    n = 0
    with open(out / "frames.jsonl", "w", encoding="utf-8") as rows:
        last_t = None
        for t, item, side, ext, extra in it:
            if last_t is not None and t < last_t:
                continue  # never let time run backwards
            last_t = t
            if isinstance(item, bytes):  # already-compressed JPEG: keep bytes
                bgr = cv2.imdecode(np.frombuffer(item, np.uint8), cv2.IMREAD_COLOR)
                if bgr is None or not sel.accept(t, bgr):
                    continue
                data = item
            else:
                if not sel.accept(t, item):
                    continue
                data = _jpeg(item)
            (out / "frames" / f"{n:06d}.{ext}").write_bytes(data)
            rows.write(_dumps({"index": n, "t": t, **extra, "source": str(src),
                               "session": session, "side": side}) + "\n")
            n += 1
    if is_session and (src / "session.json").is_file():
        shutil.copy2(src / "session.json", out / "session.json")
    elif video_meta and video_meta.get("session"):
        (out / "session.json").write_text(json.dumps(video_meta["session"], indent=2),
                                          encoding="utf-8")
    notes = ([f"skipped {skipped[0]} malformed"] if skipped[0] else []) + (
        [f"truncated {truncated[0]} files"] if truncated[0] else [])
    note = f" ({', '.join(notes)})" if notes else ""
    print(f"extracted {n} frames{note} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
