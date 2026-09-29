import json

import cv2
import numpy as np
import pytest

import extract
from frames import FrameSelector


def _img(x):
    im = np.zeros((48, 64, 3), np.uint8)
    im[:, x:x + 8] = 255
    return im


def test_selector_rules():
    s = FrameSelector(min_interval_s=0.5, max_hamming=4)
    assert s.accept(0.0, _img(5))
    assert not s.accept(0.1, _img(40))
    assert not s.accept(1.0, _img(5))
    assert s.accept(1.0, _img(40))


def test_extract_video(tmp_path):
    vid = tmp_path / "v.avi"
    w = cv2.VideoWriter(str(vid), cv2.VideoWriter_fourcc(*"MJPG"), 8.0, (64, 48))
    assert w.isOpened()
    for i in range(24):
        w.write(_img(i * 2))
    w.release()
    out = tmp_path / "out"
    assert extract.main([str(vid), "--out", str(out)]) == 0
    rows = [json.loads(l) for l in (out / "frames.jsonl").read_text().splitlines()]
    assert 1 <= len(rows) <= 7
    for r in rows:
        assert (out / "frames" / f"{r['index']:06d}.jpg").is_file()
        assert {"index", "t", "source", "session", "side"} <= set(r)


def test_image_to_bgr_encodings():
    rgb = np.array([[[10, 20, 30]]], np.uint8)
    got = extract.image_to_bgr("rgb8", 1, 1, 3, rgb.tobytes())
    assert got[0, 0].tolist() == [30, 20, 10]
    got = extract.image_to_bgr("bgr8", 1, 1, 3, rgb.tobytes())
    assert got[0, 0].tolist() == [10, 20, 30]
    got = extract.image_to_bgr("mono8", 2, 2, 2, bytes([1, 2, 3, 4]))
    assert got.shape == (2, 2, 3) and got[1, 1].tolist() == [4, 4, 4]
    with pytest.raises(ValueError):
        extract.image_to_bgr("16UC1", 1, 1, 2, b"\x00\x00")


def test_mcap_file_order_is_numeric(tmp_path):
    for n in ("bag_0.mcap", "bag_10.mcap", "bag_2.mcap"):
        (tmp_path / "bag").mkdir(exist_ok=True)
        (tmp_path / "bag" / n).write_bytes(b"")
    names = [p.name for p in extract._mcap_files(tmp_path)]
    assert names == ["bag_0.mcap", "bag_2.mcap", "bag_10.mcap"]


def test_jsonl_nan_becomes_null():
    assert json.loads(extract._dumps({"a": float("nan"), "b": [float("inf")]})) == {"a": None, "b": [None]}


def test_empty_session_errors(tmp_path):
    (tmp_path / "bag").mkdir()
    assert extract.main([str(tmp_path), "--out", str(tmp_path / "o")]) == 1


IMAGE_DEF = """std_msgs/Header header
uint32 height
uint32 width
string encoding
uint8 is_bigendian
uint32 step
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
TWIST_DEF = """Vector3 linear
Vector3 angular
================================================================================
MSG: geometry_msgs/Vector3
float64 x
float64 y
float64 z
"""


def test_mcap_session(tmp_path):
    pytest.importorskip("mcap_ros2")
    from mcap_ros2.writer import Writer

    bag = tmp_path / "sess" / "bag"
    bag.mkdir(parents=True)
    # (file, time_s, x) : frames spread over files, numeric suffix order
    plan = {"bag_0.mcap": [1.0, 2.0], "bag_2.mcap": [3.0], "bag_10.mcap": [4.0]}
    for name, times in plan.items():
        with open(bag / name, "wb") as fh:
            w = Writer(fh)
            img_s = w.register_msgdef("sensor_msgs/msg/Image", IMAGE_DEF)
            tw_s = w.register_msgdef("geometry_msgs/msg/Twist", TWIST_DEF)
            for t in times:
                ns = int(t * 1e9)
                w.write_message("/cmd_vel", tw_s, {"linear": {"x": t, "y": 0.0, "z": 0.0},
                                "angular": {"x": 0.0, "y": 0.0, "z": 0.0}}, ns - 1, ns - 1)
                px = np.full((4, 6, 3), int(t) * 50, np.uint8)
                px[:, int(t):int(t) + 2] = 255
                w.write_message("/camera/front", img_s, {
                    "header": {"stamp": {"sec": int(t), "nanosec": 0}, "frame_id": "c"},
                    "height": 4, "width": 6, "encoding": "bgr8", "is_bigendian": 0,
                    "step": 18, "data": list(px.tobytes())}, ns, ns)
            w.finish()
    out = tmp_path / "out"
    assert extract.main([str(tmp_path / "sess"), "--out", str(out),
                         "--min-interval", "0.5", "--max-hamming", "0"]) == 0
    rows = [json.loads(l) for l in (out / "frames.jsonl").read_text().splitlines()]
    assert [r["t"] for r in rows] == [1.0, 2.0, 3.0, 4.0]
    assert [r["side"]["cmd_vel"]["linear"]["x"] for r in rows] == [1.0, 2.0, 3.0, 4.0]
    assert (out / "frames" / "000003.jpg").is_file()


def test_mcap_malformed_frame_is_skipped_not_fatal(tmp_path, capsys):
    pytest.importorskip("mcap_ros2")
    from mcap_ros2.writer import Writer

    bag = tmp_path / "sess" / "bag"
    bag.mkdir(parents=True)
    with open(bag / "bag_0.mcap", "wb") as fh:
        w = Writer(fh)
        img_s = w.register_msgdef("sensor_msgs/msg/Image", IMAGE_DEF)
        for t, size in ((1.0, 4 * 6 * 3), (2.0, 5), (3.0, 4 * 6 * 3)):  # 2.0: truncated payload
            ns = int(t * 1e9)
            img = np.full((4, 6, 3), int(t) * 50, np.uint8)
            img[:, int(t):int(t) + 2] = 255
            px = img.tobytes()[:size]
            w.write_message("/camera/front", img_s, {
                "header": {"stamp": {"sec": int(t), "nanosec": 0}, "frame_id": "c"},
                "height": 4, "width": 6, "encoding": "bgr8", "is_bigendian": 0,
                "step": 18, "data": list(px)}, ns, ns)
        w.finish()
    out = tmp_path / "out"
    assert extract.main([str(tmp_path / "sess"), "--out", str(out),
                         "--min-interval", "0.5", "--max-hamming", "0"]) == 0
    rows = (out / "frames.jsonl").read_text().splitlines()
    assert len(rows) == 2
    assert "skipped 1" in capsys.readouterr().out
