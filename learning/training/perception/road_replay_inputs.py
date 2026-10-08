"""Read camera frames and same-stamp evidence for offline road replay."""

import bisect
import math
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

import bag_to_video
import extract
import lane_replay
from control.recording import CAMERA_TOPIC, KEEP_DEBUG_TOPIC, SHADOW_TOPIC
from control.sensing.perception.camera_ground import ground_plane


@dataclass
class Frame:
    t: float
    bgr: np.ndarray
    odom: tuple | None = None          # (x, y, yaw)
    shadow: dict | None = None
    ir: dict | None = None             # latest IR_LINE line/observation payload
    odom_stamp: float | None = None    # source header stamp; absent means unverified for BEV
    keep_debug: dict | None = None     # same image stamp, when recorded


def _pose_tuple(pose):
    return None if not pose else (float(pose["x"]), float(pose["y"]), float(pose["yaw"]))


def _interp(series, t):
    """Odometry pose at t, linear between the samples around it (yaw wrapped)."""
    times, poses = series
    if not times:
        return None
    j = bisect.bisect_right(times, t)
    if j == 0:
        return poses[0]
    if j == len(times):
        return poses[-1]
    (t0, a), (t1, b) = (times[j - 1], poses[j - 1]), (times[j], poses[j])
    k = 0.0 if t1 <= t0 else (t - t0) / (t1 - t0)
    turn = math.atan2(math.sin(b[2] - a[2]), math.cos(b[2] - a[2]))
    return (a[0] + k * (b[0] - a[0]), a[1] + k * (b[1] - a[1]), a[2] + k * turn)


def _nearest_odom_stamp(series, t):
    times = series[0]
    if not times:
        return None
    j = bisect.bisect_left(times, t)
    return min((times[k] for k in (j - 1, j) if 0 <= k < len(times)),
               key=lambda stamp: abs(stamp - t))


def _mcap_odom(files):
    from mcap.reader import make_reader
    from mcap_ros2.decoder import DecoderFactory
    samples = []
    for f in files:
        with open(f, "rb") as fh:
            reader = make_reader(fh, decoder_factories=[DecoderFactory()])
            summary = reader.get_summary()
            topics = None if summary is None else [
                c.topic for c in summary.channels.values() if extract._topic_is(c.topic, "odom")]
            for _, ch, _, msg in reader.iter_decoded_messages(topics=topics):
                if extract._topic_is(ch.topic, "odom"):
                    samples.append((bag_to_video._stamp_ns(msg) / 1e9, _pose_tuple(bag_to_video._pose(msg))))
    samples.sort(key=lambda s: s[0])
    return [s[0] for s in samples], [s[1] for s in samples]


def mcap_frames(session: Path, *, recorded_ground: bool = False):
    files = extract._mcap_files(session)
    if not files:
        raise SystemExit(f"no .mcap files under {session / 'bag'}")
    odom = _mcap_odom(files)
    if recorded_ground:
        # Reuse extraction's stamp/window join: keep_debug is logged after its image.
        for t, item, side, _, _ in extract._mcap_frames(files):
            bgr = (item if isinstance(item, np.ndarray) else
                   cv2.imdecode(np.frombuffer(item, np.uint8), cv2.IMREAD_COLOR))
            if bgr is not None:
                line = side.get("line/observation")
                yield Frame(t, bgr, _interp(odom, t), side.get(SHADOW_TOPIC),
                            line if isinstance(line, dict) and line.get("source") == "IR_LINE" else None,
                            _nearest_odom_stamp(odom, t), side.get(KEEP_DEBUG_TOPIC))
        return
    shadow = ir = None
    for name, _, schema, msg in bag_to_video._messages(files, camera_only=False):
        if name == CAMERA_TOPIC:
            bgr = bag_to_video._frame(schema, msg)
            if bgr is not None:
                t = bag_to_video._stamp_ns(msg) / 1e9
                yield Frame(t, bgr, _interp(odom, t), shadow, ir,
                            _nearest_odom_stamp(odom, t))
        elif name == SHADOW_TOPIC:
            shadow = extract._side_value(schema, msg)
        elif name == "line/observation":
            value = extract._side_value(schema, msg)
            if isinstance(value, dict) and value.get("source") == "IR_LINE":
                ir = value


def video_frames(path: Path):
    rows, meta = extract._sidecar(path)
    if rows is None:
        raise SystemExit(f"{path}: no {path.with_suffix('.jsonl').name} sidecar; the estimator needs "
                         "odometry, so frame-only video is not replayed")
    extract._check_sidecar(path, rows, meta)
    for t, bgr, side, _, _ in extract._video_frames(path, rows):
        line = side.get("line/observation")
        odom = side.get("odom")
        stamp_ns = odom.get("stamp_ns") if isinstance(odom, dict) else None
        yield Frame(float(t), bgr, _pose_tuple(side.get("odom")), side.get(SHADOW_TOPIC),
                    line if isinstance(line, dict) and line.get("source") == "IR_LINE" else None,
                    stamp_ns / 1e9 if isinstance(stamp_ns, int) and not isinstance(stamp_ns, bool) else None,
                    side.get(KEEP_DEBUG_TOPIC))


def session_frames(source: Path, *, recorded_ground: bool = False):
    """extract.py's rule: a folder is an MCAP session, a file a bag_to_video video."""
    return mcap_frames(source, recorded_ground=recorded_ground) if source.is_dir() else video_frames(source)


def recorded_projection(frame: Frame):
    debug = frame.keep_debug
    if not isinstance(debug, dict):
        raise SystemExit(f"frame {frame.t}: missing line/keep_debug")
    stamp = debug.get("stamp")
    if (isinstance(stamp, bool) or not isinstance(stamp, (int, float))
            or not math.isfinite(stamp) or abs(stamp - frame.t) > extract.STAMP_TOL_S):
        raise SystemExit(f"frame {frame.t}: line/keep_debug image stamp mismatch")
    if debug.get("image_size") != [lane_replay.FRAME_W, lane_replay.FRAME_H] or \
            frame.bgr.shape[:2] != (lane_replay.FRAME_H, lane_replay.FRAME_W):
        raise SystemExit(f"frame {frame.t}: recorded ground image size mismatch")
    data = debug.get("ground_projection")
    keys = ("height_m", "pitch_rad", "focal_px", "principal_x", "principal_y", "max_range_m")
    if (not isinstance(data, dict) or any(isinstance(data.get(k), bool)
            or not isinstance(data.get(k), (int, float)) for k in (*keys, "camera_x_offset_m"))):
        raise SystemExit(f"frame {frame.t}: missing or invalid ground projection")
    plane = ground_plane(*(data[k] for k in keys))
    offset = data["camera_x_offset_m"]
    if plane is None or not math.isfinite(offset):
        raise SystemExit(f"frame {frame.t}: missing or invalid ground projection")
    return plane, float(offset), {**{k: getattr(plane, k) for k in keys}, "camera_x_offset_m": float(offset)}
