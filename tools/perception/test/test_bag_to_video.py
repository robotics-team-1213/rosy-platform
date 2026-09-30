import json
import math
import shutil
import subprocess

import cv2
import numpy as np
import pytest

import bag_to_video as b2v
import extract
from test_dataset_extract import IMAGE_DEF, STRING_DEF, TWIST_DEF

ODOM_DEF = """std_msgs/Header header
geometry_msgs/PoseWithCovariance pose
================================================================================
MSG: std_msgs/Header
builtin_interfaces/Time stamp
string frame_id
================================================================================
MSG: builtin_interfaces/Time
int32 sec
uint32 nanosec
================================================================================
MSG: geometry_msgs/PoseWithCovariance
Pose pose
================================================================================
MSG: geometry_msgs/Pose
Point position
Quaternion orientation
================================================================================
MSG: geometry_msgs/Point
float64 x
float64 y
float64 z
================================================================================
MSG: geometry_msgs/Quaternion
float64 x
float64 y
float64 z
float64 w
"""
SCAN_DEF = """std_msgs/Header header
float32 angle_min
float32 angle_max
float32 angle_increment
float32 range_min
float32 range_max
float32[] ranges
================================================================================
MSG: std_msgs/Header
builtin_interfaces/Time stamp
string frame_id
================================================================================
MSG: builtin_interfaces/Time
int32 sec
uint32 nanosec
"""
COMPRESSED_DEF = """std_msgs/Header header
string format
uint8[] data
================================================================================
MSG: std_msgs/Header
builtin_interfaces/Time stamp
string frame_id
================================================================================
MSG: builtin_interfaces/Time
int32 sec
uint32 nanosec
"""
SCAN_S = [1.02, 1.12, 1.22]   # 10 Hz LiDAR, only near the first frames
BEAMS = 8
W, H = 32, 24
FRAME_S = [1.0, 1.125, 1.25, 1.375, 1.5, 1.625]   # 8 fps
BAD_S = 1.3                                         # truncated payload, must be dropped
NS = "/rosy_60/"

needs_tools = pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
                                 reason="ffmpeg/ffprobe not on PATH")


def _ns(t):
    return int(round(t * 1e9))


def _px(i):
    return np.full((H, W, 3), 30 + 35 * i, np.uint8)


def _write_session(root, name="20260930T124745Z_rosy-pinky-test", lidar=False,
                   compressed=False):
    pytest.importorskip("mcap_ros2")
    from mcap_ros2.writer import Writer

    sess = root / name
    (sess / "bag").mkdir(parents=True)
    (sess / "session.json").write_text(json.dumps(
        {"schema": "rosy.recording.session/1", "device": "rosy-pinky-test",
         "reason": "unit"}), encoding="utf-8")
    # two files: frames 0-2 (+ the bad one) in bag_0, 3-5 in bag_1
    split = {"bag_0.mcap": (0.0, 1.32), "bag_1.mcap": (1.32, 9.0)}
    for fname, (lo, hi) in split.items():
        with open(sess / "bag" / fname, "wb") as fh:
            w = Writer(fh)
            img_s = w.register_msgdef("sensor_msgs/msg/Image", IMAGE_DEF)
            tw_s = w.register_msgdef("geometry_msgs/msg/Twist", TWIST_DEF)
            od_s = w.register_msgdef("nav_msgs/msg/Odometry", ODOM_DEF)
            st_s = w.register_msgdef("std_msgs/msg/String", STRING_DEF)
            sc_s = w.register_msgdef("sensor_msgs/msg/LaserScan", SCAN_DEF)
            ci_s = w.register_msgdef("sensor_msgs/msg/CompressedImage", COMPRESSED_DEF)
            events = []
            for k, t in enumerate(SCAN_S if lidar else []):
                events.append((t, NS + "scan", sc_s, {
                    "header": {"stamp": {"sec": 1, "nanosec": _ns(t) - 1_000_000_000},
                               "frame_id": "laser"},
                    "angle_min": -3.0, "angle_max": 3.0, "angle_increment": 0.75,
                    "range_min": 0.1, "range_max": 12.0,
                    "ranges": [float(k + 1)] * (BEAMS - 1) + [float("inf")]}))
            # cmd_vel every 0.02 s from 0.99 s, linear.x = its own time: nearest is checkable
            for k in range(40):
                t = 0.99 + 0.02 * k
                events.append((t, NS + "cmd_vel", tw_s, {
                    "linear": {"x": round(t, 2), "y": 0.0, "z": 0.0},
                    "angular": {"x": 0.0, "y": 0.0, "z": -round(t, 2)}}))
            # odom only near the first three frames: later frames are past --max-gap
            for k, t in enumerate((0.99, 1.13, 1.24)):
                yaw = 0.1 * (k + 1)
                events.append((t, NS + "odom", od_s, {
                    "header": {"stamp": {"sec": 0, "nanosec": 0}, "frame_id": "odom"},
                    "pose": {"pose": {"position": {"x": float(k), "y": -float(k), "z": 0.0},
                                      "orientation": {"x": 0.0, "y": 0.0,
                                                      "z": math.sin(yaw / 2),
                                                      "w": math.cos(yaw / 2)}}}}))
            for i, t in enumerate(FRAME_S):
                events.append((t + 0.004, NS + "line/observation", st_s,
                               {"data": json.dumps({"error": i / 10, "visible": True})}))
                if compressed:
                    jpg = cv2.imencode(".jpg", _px(i), [cv2.IMWRITE_JPEG_QUALITY, 85])[1]
                    events.append((t + 0.001, NS + "camera/front/compressed", ci_s,
                                   _compressed(t, jpg.tobytes())))
                else:
                    events.append((t + 0.001, NS + "camera/front", img_s,
                                   _image(t, _px(i).tobytes())))
            if compressed:
                events.append((BAD_S, NS + "camera/front/compressed", ci_s,
                               _compressed(BAD_S, b"\x00" * 5)))
            else:
                events.append((BAD_S, NS + "camera/front", img_s, _image(BAD_S, b"\x00" * 5)))
            for t, topic, schema, msg in sorted(events, key=lambda e: e[0]):
                if lo <= t < hi:
                    w.write_message(topic, schema, msg, _ns(t), _ns(t))
            w.finish()
    return sess


def _image(t, data):
    # header stamp = capture time t - 1 ms before the log time
    return {"header": {"stamp": {"sec": int(t), "nanosec": _ns(t) % 1_000_000_000},
                       "frame_id": "c"},
            "height": H, "width": W, "encoding": "bgr8", "is_bigendian": 0,
            "step": W * 3, "data": list(data)}


def _compressed(t, data):
    return {"header": {"stamp": {"sec": int(t), "nanosec": _ns(t) % 1_000_000_000},
                       "frame_id": "c"}, "format": "jpeg", "data": list(data)}


def _convert(tmp_path, *extra, **session_kw):
    sess = _write_session(tmp_path, **session_kw)
    out = tmp_path / "learning"
    rc = b2v.main([str(sess), "--out", str(out), "--codec", "h264", "--preset", "ultrafast",
                   "--max-gap", "0.05", *extra])
    assert rc == 0
    stem = out / "teleop_rosy-pinky-test_20260930T124745Z"
    return sess, stem


@needs_tools
def test_every_valid_frame_lands_in_video_and_sidecar(tmp_path):
    _, stem = _convert(tmp_path)
    video = stem.with_suffix(".mp4")
    rows = [json.loads(l) for l in stem.with_suffix(".jsonl").read_text().splitlines()]
    assert b2v.count_frames(video) == len(FRAME_S) == len(rows)
    assert [r["index"] for r in rows] == list(range(len(FRAME_S)))
    # exact stamps: header stamp and log time, ns
    assert [r["stamp_ns"] for r in rows] == [_ns(t) for t in FRAME_S]
    assert [r["log_ns"] for r in rows] == [_ns(t + 0.001) for t in FRAME_S]
    assert [r["t"] for r in rows] == pytest.approx(FRAME_S)
    # decoded frame i is recorded frame i: the flat levels are 35 apart and lossy coding
    # moves them by a few units, so +-10 still pins the order
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-f", "rawvideo",
                          "-pix_fmt", "bgr24", "-"], capture_output=True, check=True).stdout
    dec = np.frombuffer(raw, np.uint8).reshape(-1, H, W, 3)
    assert [round(float(f.mean())) for f in dec] == pytest.approx(
        [30 + 35 * i for i in range(len(FRAME_S))], abs=10)


@needs_tools
def test_sidecar_takes_the_nearest_side_sample_and_nulls_stale_ones(tmp_path):
    _, stem = _convert(tmp_path)
    rows = [json.loads(l) for l in stem.with_suffix(".jsonl").read_text().splitlines()]
    for r, t in zip(rows, FRAME_S):
        log_t = t + 0.001
        want = min((0.99 + 0.02 * k for k in range(40)), key=lambda c: abs(c - log_t))
        assert r["side"]["cmd_vel"] == {"linear": pytest.approx(round(want, 2)),
                                        "angular": pytest.approx(-round(want, 2))}
        assert r["dt"]["cmd_vel"] == pytest.approx(round(want - log_t, 4), abs=1e-4)
        assert r["side"]["line/observation"]["error"] == pytest.approx(FRAME_S.index(t) / 10)
    # frame 1 (1.126 s): nearest odom is 1.13 s, i.e. the sample AFTER the frame
    assert rows[1]["side"]["odom"] == {"x": 1.0, "y": -1.0, "yaw": pytest.approx(0.2)}
    assert rows[1]["dt"]["odom"] > 0
    # frames 3.. are more than --max-gap from any odom sample
    assert all(r["side"]["odom"] is None and r["dt"]["odom"] is None for r in rows[3:])


@needs_tools
def test_metadata_copies_session_and_describes_the_video(tmp_path):
    sess, stem = _convert(tmp_path)
    doc = json.loads(stem.with_suffix(".json").read_text())
    assert doc["schema"] == b2v.SCHEMA
    assert doc["session"] == json.loads((sess / "session.json").read_text())
    assert doc["source"]["session"] == sess.name
    assert doc["source"]["skipped_frames"] == 1
    v = doc["video"]
    assert (v["frames"], v["width"], v["height"], v["codec"]) == (len(FRAME_S), W, H, "h264")
    assert v["fps"] == pytest.approx(8.0)
    assert v["bytes"] == stem.with_suffix(".mp4").stat().st_size


@needs_tools
def test_existing_outputs_are_not_overwritten_without_force(tmp_path, capsys):
    sess, stem = _convert(tmp_path)
    out = str(stem.parent)
    assert b2v.main([str(sess), "--out", out, "--codec", "h264", "--preset", "ultrafast"]) == 1
    assert "--force" in capsys.readouterr().err
    assert b2v.main([str(sess), "--out", out, "--codec", "h264", "--preset", "ultrafast",
                     "--force"]) == 0


@needs_tools
def test_extract_reads_the_video_with_its_sidecar(tmp_path):
    sess, stem = _convert(tmp_path)
    out = tmp_path / "frames"
    assert extract.main([str(stem.with_suffix(".mp4")), "--out", str(out),
                         "--min-interval", "0", "--max-hamming", "-1"]) == 0
    rows = [json.loads(l) for l in (out / "frames.jsonl").read_text().splitlines()]
    assert [r["t"] for r in rows] == pytest.approx(FRAME_S)
    assert {r["session"] for r in rows} == {sess.name}
    assert rows[0]["side"]["cmd_vel"]["linear"] == pytest.approx(1.01)
    assert json.loads((out / "session.json").read_text())["device"] == "rosy-pinky-test"


@needs_tools
def test_extract_refuses_a_sidecar_that_does_not_match_the_video(tmp_path):
    _, stem = _convert(tmp_path)
    sidecar = stem.with_suffix(".jsonl")
    sidecar.write_text("\n".join(sidecar.read_text().splitlines()[:-1]) + "\n")
    with pytest.raises(SystemExit, match="sidecar"):
        extract.main([str(stem.with_suffix(".mp4")), "--out", str(tmp_path / "f"),
                      "--min-interval", "0", "--max-hamming", "-1"])


def test_nearest():
    times = [10, 20, 30]
    assert b2v.nearest(times, 14, 100) == 0
    assert b2v.nearest(times, 16, 100) == 1
    assert b2v.nearest(times, 99, 100) == 2
    assert b2v.nearest(times, 0, 5) is None
    assert b2v.nearest([], 5, 100) is None


def test_output_stem_and_rate(tmp_path):
    assert b2v.output_stem(tmp_path / "20260930T124745Z_rosy-pinky-8kcn",
                           {"device": "rosy-pinky-8kcn"}) == \
        "teleop_rosy-pinky-8kcn_20260930T124745Z"
    assert b2v.output_stem(tmp_path / "manual",
                           {"device": "a/b", "started_at": "2026-09-30T12:47:45.3+00:00"}) == \
        "teleop_a-b_20260930T124745Z"
    frames = [{"stamp_ns": _ns(t)} for t in FRAME_S]
    assert b2v.mean_fps(frames) == pytest.approx(8.0)


def test_empty_session_errors(tmp_path):
    (tmp_path / "bag").mkdir()
    assert b2v.main([str(tmp_path), "--out", str(tmp_path / "o")]) == 1


@needs_tools
def test_lidar_scan_nearest_per_frame_goes_to_the_npz(tmp_path):
    _, stem = _convert(tmp_path, lidar=True)
    rows = [json.loads(l) for l in stem.with_suffix(".jsonl").read_text().splitlines()]
    npz = np.load(str(stem) + ".scan.npz")
    assert npz["ranges"].dtype == np.float16
    assert npz["ranges"].shape == (len(FRAME_S), BEAMS)
    assert float(npz["angle_increment"]) == pytest.approx(0.75)
    # frame 0 (log 1.001) -> scan 1.02, frame 1 (1.126) -> 1.12, frame 2 (1.251) -> 1.22
    for i, k in enumerate((0, 1, 2)):
        assert npz["ranges"][i, 0] == k + 1 and np.isinf(npz["ranges"][i, -1])
        assert int(npz["scan_stamp_ns"][i]) == rows[i]["side"]["scan"]["stamp_ns"] == _ns(SCAN_S[k])
        assert float(npz["dt"][i]) == pytest.approx(rows[i]["dt"]["scan"], abs=1e-4)
    # later frames are past --max-gap: NaN row in the npz, null in the sidecar
    assert np.isnan(npz["ranges"][3:].astype(np.float32)).all()
    assert all(r["side"]["scan"] is None for r in rows[3:])
    doc = json.loads(stem.with_suffix(".json").read_text())
    assert doc["scan"]["beams"] == BEAMS and doc["source"]["topics"]["scan"] == len(SCAN_S)


@needs_tools
def test_compressed_camera_topic_converts_with_the_same_stamps(tmp_path):
    _, stem = _convert(tmp_path, compressed=True)
    rows = [json.loads(l) for l in stem.with_suffix(".jsonl").read_text().splitlines()]
    assert b2v.count_frames(stem.with_suffix(".mp4")) == len(rows) == len(FRAME_S)
    assert [r["stamp_ns"] for r in rows] == [_ns(t) for t in FRAME_S]
    assert json.loads(stem.with_suffix(".json").read_text())["source"]["skipped_frames"] == 1
    assert not (stem.parent / (stem.name + ".scan.npz")).exists()


def _odom(points):
    """[(t_s, x, yaw)] -> (times ns, poses) as first_pass() stores them."""
    return [_ns(t) for t, _, _ in points], [{"x": x, "y": 0.0, "yaw": yaw} for _, x, yaw in points]


def test_motion_flags_idle_driving_pivoting_and_commanded():
    still = _odom([(0.0, 0.0, 0.0), (0.1, 0.0, 0.0), (0.2, 0.0, 0.0), (0.3, 0.0, 0.0)])
    zero = {"linear": 0.0, "angular": 0.0}
    m = b2v.motion(_ns(0.15), still, zero)
    assert m == {"moving": False, "commanded": False, "v": 0.0, "w": 0.0}
    drive = _odom([(0.0, 0.0, 0.0), (0.1, 0.01, 0.0), (0.2, 0.02, 0.0), (0.3, 0.03, 0.0)])
    m = b2v.motion(_ns(0.15), drive, zero)
    assert m["moving"] and not m["commanded"] and m["v"] == pytest.approx(0.1)
    # in-place pivot across the +-pi seam: small wrapped yaw change, not 2*pi
    pivot = _odom([(0.0, 0.0, 3.1), (0.1, 0.0, -3.13), (0.2, 0.0, -3.08), (0.3, 0.0, -3.03)])
    m = b2v.motion(_ns(0.15), pivot, zero)
    wrapped = (-3.03 - 3.1) + 2 * math.pi               # 0.153 rad over the 0.3 s window
    assert m["moving"] and m["v"] == 0.0 and m["w"] == pytest.approx(wrapped / 0.3, abs=1e-3)
    m = b2v.motion(_ns(0.15), still, {"linear": 0.0, "angular": 0.3})
    assert m["moving"] and m["commanded"]
    m = b2v.motion(_ns(5.0), still, None)       # no odom near the frame, no command
    assert m == {"moving": False, "commanded": False, "v": None, "w": None}
