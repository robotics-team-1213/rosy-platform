"""Extract training frames from an MP4 or a robot recording session (MCAP).

Usage: extract.py <source> --out data/perception/frames/<name>
<source> is a video file (cv2-readable) or a session folder with bag/*.mcap.
"""
import argparse
import json
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
from control.recording import RECORD_TOPICS  # noqa: E402
from control.sensing.perception.image_frame import image_msg_to_frame  # noqa: E402

CAMERA_TOPIC = RECORD_TOPICS[0]
SIDE_TOPICS = {"cmd_vel": "cmd_vel", "line/observation": "line_observation",
               "perception/learned/shadow": "shadow"}
JPEG_Q = 95


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


def _mcap_frames(files):
    try:
        from mcap.reader import make_reader
        from mcap_ros2.decoder import DecoderFactory
    except ImportError:
        raise SystemExit("MCAP extraction needs: pip install mcap mcap-ros2-support")
    side = {}
    for f in files:
        with open(f, "rb") as fh:
            reader = make_reader(fh, decoder_factories=[DecoderFactory()])
            for _, ch, message, msg in reader.iter_decoded_messages():
                # Channels carry absolute topics ("/camera/front").
                name = ch.topic.lstrip("/")
                if name in SIDE_TOPICS:
                    side[SIDE_TOPICS[name]] = _jsonable(msg)
                    continue
                t = message.log_time / 1e9
                if name == CAMERA_TOPIC + "/compressed":
                    ext = "png" if "png" in str(msg.format).lower() else "jpg"
                    yield t, bytes(msg.data), dict(side), ext
                elif name == CAMERA_TOPIC:
                    bgr = image_to_bgr(msg.encoding, msg.width, msg.height, msg.step, bytes(msg.data))
                    yield t, bgr, dict(side), "jpg"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("source")
    ap.add_argument("--out", required=True)
    ap.add_argument("--min-interval", type=float, default=0.5)
    ap.add_argument("--max-hamming", type=int, default=4)
    args = ap.parse_args(argv)
    src, out = Path(args.source), Path(args.out)
    is_session = src.is_dir()
    if is_session:
        files = _mcap_files(src)
        if not files:
            print(f"no .mcap files under {src / 'bag'}", file=sys.stderr)
            return 1
        it = _mcap_frames(files)
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
    print(f"extracted {n} frames -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
