"""Extract training frames from an MP4 or a robot recording session (MCAP).

Usage: extract.py <source> --out data/perception/frames/<name>
<source> is a video file (cv2-readable) or a session folder with bag/*.mcap.

Side data is matched to frames, not attached in bag order: payloads that carry
a `stamp` (the shadow result, line/observation) go to the frame whose header
stamp equals it, if logged within SIDE_LOOKAHEAD_S after that frame (inference
finishes after the frame is logged); stamp-less side data (cmd_vel, text) is
the latest one logged before the frame. camera/front/compressed is preferred:
when a session has it, raw camera/front frames are not extracted.
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
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src" / "runtime" / "sensing"))

from frames import FrameSelector  # noqa: E402
from control.recording import CAMERA_TOPIC, COMPRESSED_CAMERA_TOPIC, SIDE_TOPICS  # noqa: E402
from control.sensing.perception.image_frame import image_msg_to_frame  # noqa: E402

STRING_SCHEMA = "std_msgs/msg/String"
JPEG_Q = 95
SIDE_LOOKAHEAD_S = 0.5  # a stamped side message may be logged this long after its frame
STAMP_TOL_S = 1e-4  # stamps round-trip through JSON floats


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


def _video_frames(path: Path):
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise SystemExit(f"cannot open video: {path}")
    try:
        while True:
            ok, bgr = cap.read()
            if not ok:
                break
            yield cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0, bgr, {}, "jpg"
    finally:
        cap.release()


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


def _header_stamp(msg):
    try:
        return float(msg.header.stamp.sec) + float(msg.header.stamp.nanosec) * 1e-9
    except AttributeError:
        return None


def _has_compressed(files, make_reader) -> bool:
    for f in files:
        with open(f, "rb") as fh:
            reader = make_reader(fh)
            try:
                summary = reader.get_summary()
            except Exception:  # truncated file: no summary section
                summary = None
            if summary is not None:
                channels = summary.channels.values()
            else:
                fh.seek(0)
                channels = (ch for _, ch, _ in make_reader(fh).iter_messages())
            if any(_topic_is(ch.topic, COMPRESSED_CAMERA_TOPIC) for ch in channels):
                return True
    return False


def _mcap_frames(files, skipped=None):
    try:
        from mcap.reader import make_reader
        from mcap_ros2.decoder import DecoderFactory
    except ImportError:
        raise SystemExit("MCAP extraction needs: pip install mcap mcap-ros2-support")
    prefer_compressed = _has_compressed(files, make_reader)
    latest = {}  # stamp-less side data, latest by log time
    early = deque()  # stamped side data logged before its frame: (t, stamp, name, value)
    pending = deque()  # frames still inside their look-ahead window

    def ready(now):
        while pending and (now is None or pending[0]["t"] + SIDE_LOOKAHEAD_S < now):
            f = pending.popleft()
            yield f["t"], f["item"], f["side"], f["ext"]

    for f in files:
        with open(f, "rb") as fh:
            reader = make_reader(fh, decoder_factories=[DecoderFactory()])
            for schema, ch, message, msg in reader.iter_decoded_messages():
                t = message.log_time / 1e9
                yield from ready(t)
                while early and early[0][0] + SIDE_LOOKAHEAD_S < t:
                    early.popleft()
                # Channels carry absolute, possibly namespaced topics.
                name = next((n for n in SIDE_TOPICS if _topic_is(ch.topic, n)), None)
                if name is not None:
                    value = _side_value(schema.name, msg)
                    stamp = _payload_stamp(value)
                    if stamp is None:
                        latest[name] = value
                        continue
                    frame = next((p for p in pending if p["stamp"] is not None
                                  and abs(p["stamp"] - stamp) <= STAMP_TOL_S), None)
                    if frame is not None:
                        frame["side"][name] = value
                    else:
                        early.append((t, stamp, name, value))
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
                stamp = _header_stamp(msg)
                side = dict(latest)
                if stamp is not None:
                    for _, s_stamp, s_name, s_value in early:
                        if abs(s_stamp - stamp) <= STAMP_TOL_S:
                            side[s_name] = s_value
                pending.append({"t": t, "stamp": stamp, "item": item, "side": side, "ext": ext})
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
    if is_session:
        files = _mcap_files(src)
        if not files:
            print(f"no .mcap files under {src / 'bag'}", file=sys.stderr)
            return 1
        it = _mcap_frames(files, skipped)
    else:
        it = _video_frames(src)
    session = src.name if is_session else None
    (out / "frames").mkdir(parents=True, exist_ok=True)
    sel = FrameSelector(args.min_interval, args.max_hamming)
    n = 0
    with open(out / "frames.jsonl", "w", encoding="utf-8") as rows:
        last_t = None
        for t, item, side, ext in it:
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
            rows.write(_dumps({"index": n, "t": t, "source": str(src),
                                   "session": session, "side": side}) + "\n")
            n += 1
    if is_session and (src / "session.json").is_file():
        shutil.copy2(src / "session.json", out / "session.json")
    note = f" (skipped {skipped[0]} malformed)" if skipped[0] else ""
    print(f"extracted {n} frames{note} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
