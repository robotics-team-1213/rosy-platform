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


STRING_DEF = "string data\n"


def _write_side_session(tmp_path, shadow_text, camera="/camera/front", shadow_topic=None):
    """One MCAP: a shadow String, a line/observation String, then one camera frame."""
    from mcap_ros2.writer import Writer

    from control.recording import SHADOW_TOPIC

    bag = tmp_path / "sess" / "bag"
    bag.mkdir(parents=True)
    with open(bag / "bag_0.mcap", "wb") as fh:
        w = Writer(fh)
        img_s = w.register_msgdef("sensor_msgs/msg/Image", IMAGE_DEF)
        str_s = w.register_msgdef("std_msgs/msg/String", STRING_DEF)
        # logged after the frame's capture (header stamp 0.0000008 s), before its log
        w.write_message(shadow_topic or "/" + SHADOW_TOPIC, str_s, {"data": shadow_text},
                        900, 900)
        w.write_message(camera.replace("camera/front", "line/observation"), str_s,
                        {"data": "not json"}, 950, 950)
        px = np.zeros((4, 6, 3), np.uint8)
        px[:, 2:4] = 255
        w.write_message(camera, img_s, {
            "header": {"stamp": {"sec": 0, "nanosec": 800}, "frame_id": "c"},
            "height": 4, "width": 6, "encoding": "bgr8", "is_bigendian": 0,
            "step": 18, "data": list(px.tobytes())}, 1000, 1000)
        w.finish()
    return tmp_path / "sess"


def test_side_topics_share_the_recording_constants():
    from control.recording import RECORD_TOPICS, SHADOW_TOPIC, SIDE_TOPICS
    assert set(SIDE_TOPICS) <= set(RECORD_TOPICS)
    assert {"cmd_vel", "line/observation", SHADOW_TOPIC, "scan", "odom"} == set(SIDE_TOPICS)


def test_string_side_data_round_trips_into_prelabel_score(tmp_path):
    """extract-shaped frames.jsonl row -> prelabel.score_frame adds |error_delta|."""
    pytest.importorskip("mcap_ros2")
    import prelabel
    from control.recording import SHADOW_TOPIC
    from test_dataset_build import MODEL_CLASSES, _logits

    # stamp = the frame's header stamp: the shadow result of that frame
    payload = {"stamp": 8e-7, "model_revision": "r1", "error_delta": -0.4, "confidence": 0.9}
    sess = _write_side_session(tmp_path, json.dumps(payload))
    out = tmp_path / "out"
    assert extract.main([str(sess), "--out", str(out)]) == 0
    row = json.loads((out / "frames.jsonl").read_text().splitlines()[0])
    assert row["side"][SHADOW_TOPIC] == payload
    # line/observation is a stamped topic; raw text carries no image stamp: no frame
    assert row["side"]["line/observation"] is None
    assert prelabel.SHADOW_KEY == SHADOW_TOPIC
    lg = _logits(lane_cols=slice(4, 6))
    base = prelabel.score_frame(lg, MODEL_CLASSES, {}, "r1")
    got = prelabel.score_frame(lg, MODEL_CLASSES, row["side"], "r1")
    assert got["recorded"] and got["error_delta"] == -0.4
    assert got["score"] == pytest.approx(base["score"] + 0.4)


def test_topic_match_strips_any_namespace():
    assert extract._topic_is("/camera/front", "camera/front")
    assert extract._topic_is("/pinky1/camera/front", "camera/front")
    assert extract._topic_is("/a/b/cmd_vel", "cmd_vel")
    assert not extract._topic_is("/xcamera/front", "camera/front")
    assert not extract._topic_is("/pinky1/camera/front/compressed", "camera/front")


def test_namespaced_session_extracts_frames_and_side_data(tmp_path):
    pytest.importorskip("mcap_ros2")
    from control.recording import SHADOW_TOPIC

    sess = _write_side_session(tmp_path, json.dumps({"stamp": 8e-7, "error_delta": 0.1}),
                               camera="/pinky1/camera/front",
                               shadow_topic="/pinky1/" + SHADOW_TOPIC)
    out = tmp_path / "out"
    assert extract.main([str(sess), "--out", str(out)]) == 0
    rows = [json.loads(l) for l in (out / "frames.jsonl").read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["side"] == {SHADOW_TOPIC: {"stamp": 8e-7, "error_delta": 0.1},
                                   "line/observation": None, "line/keep_debug": None}


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


def _frame_px(t):
    px = np.full((4, 6, 3), int(t * 10) % 200, np.uint8)
    px[:, int(t) % 5:int(t) % 5 + 2] = 255
    return px


def _write_stamped(tmp_path, events):
    """events: (log_s, kind, stamp_s[, extra]) with kind raw|jpeg|shadow|line|cmd."""
    from mcap_ros2.writer import Writer

    from control.recording import SHADOW_TOPIC

    bag = tmp_path / "sess" / "bag"
    bag.mkdir(parents=True)
    with open(bag / "bag_0.mcap", "wb") as fh:
        w = Writer(fh)
        img_s = w.register_msgdef("sensor_msgs/msg/Image", IMAGE_DEF)
        jpg_s = w.register_msgdef("sensor_msgs/msg/CompressedImage", COMPRESSED_DEF)
        str_s = w.register_msgdef("std_msgs/msg/String", STRING_DEF)
        tw_s = w.register_msgdef("geometry_msgs/msg/Twist", TWIST_DEF)
        scan_s = w.register_msgdef("sensor_msgs/msg/LaserScan", SCAN_DEF)
        for log_s, kind, stamp in events:
            ns = int(round(log_s * 1e9))
            sec = int(stamp)
            header = {"stamp": {"sec": sec, "nanosec": int(round((stamp - sec) * 1e9))},
                      "frame_id": "c"}
            px = _frame_px(stamp)
            if kind == "raw":
                w.write_message("/camera/front", img_s, {
                    "header": header, "height": 4, "width": 6, "encoding": "bgr8",
                    "is_bigendian": 0, "step": 18, "data": list(px.tobytes())}, ns, ns)
            elif kind == "jpeg":
                ok, buf = cv2.imencode(".jpg", px)
                w.write_message("/camera/front/compressed", jpg_s, {
                    "header": header, "format": "jpeg", "data": list(buf.tobytes())}, ns, ns)
            elif kind == "shadow":
                w.write_message("/" + SHADOW_TOPIC, str_s, {"data": json.dumps(
                    {"stamp": stamp, "error_delta": stamp})}, ns, ns)
            elif kind == 'keep':
                w.write_message('/line/keep_debug', str_s, {'data': json.dumps(
                    {'stamp': stamp, 'target_m': [0.22, -0.04],
                     'strategy': 'right_only', 'paint_source_used': 'threshold'})}, ns, ns)
            elif kind in ("line", "irline"):
                source = "CAMERA_LINE" if kind == "line" else "IR_LINE"
                w.write_message("/line/observation", str_s, {"data": json.dumps(
                    {"source": source, "stamp": stamp, "error": stamp})}, ns, ns)
            elif kind == "cmd":
                w.write_message("/cmd_vel", tw_s, {"linear": {"x": stamp, "y": 0.0, "z": 0.0},
                                "angular": {"x": 0.0, "y": 0.0, "z": 0.0}}, ns, ns)
            elif kind == "scan":
                w.write_message("/pinky1/scan", scan_s, {
                    "header": header, "angle_min": -3.14, "angle_max": 3.14,
                    "angle_increment": 1.57, "time_increment": 0.0, "scan_time": 0.1,
                    "range_min": 0.05, "range_max": 8.0,
                    "ranges": [stamp, float("nan"), float("inf"), 1.5],
                    "intensities": [1.0, 2.0, 3.0, 4.0]}, ns, ns)
        w.finish()
    return tmp_path / "sess"


def test_keep_debug_mcap_conversion_and_extraction_have_the_same_source_frame(tmp_path):
    import bag_to_video as b2v
    session = _write_stamped(tmp_path, [
        (1.0, 'raw', 1.0), (1.04, 'keep', 1.0), (1.1, 'raw', 1.1),
        (1.12, 'keep', 1.0), (1.2, 'raw', 1.2), (1.24, 'keep', 1.2)])
    frames, side, _, _, _ = b2v.first_pass(extract._mcap_files(session))
    converted = list(b2v.sidecar_rows(frames, side, 0.5))
    direct = [{'side': row[2]} for row in extract._mcap_frames(extract._mcap_files(session))]
    for rows in (converted, direct):
        assert rows[0]['side']['line/keep_debug']['target_m'] == [0.22, -0.04]
        assert rows[1]['side']['line/keep_debug'] is None
        assert rows[2]['side']['line/keep_debug']['strategy'] == 'right_only'


SCAN_DEF = """std_msgs/Header header
float32 angle_min
float32 angle_max
float32 angle_increment
float32 time_increment
float32 scan_time
float32 range_min
float32 range_max
float32[] ranges
float32[] intensities
================================================================================
MSG: std_msgs/Header
builtin_interfaces/Time stamp
string frame_id
================================================================================
MSG: builtin_interfaces/Time
int32 sec
uint32 nanosec
"""


def test_scan_is_the_latest_logged_at_or_before_the_frame(tmp_path):
    """Clock rule class (b): no future leakage, even when a later scan is nearer."""
    pytest.importorskip("mcap_ros2")
    from control.recording import RECORD_TOPICS, SCAN_TOPIC, SIDE_TOPICS

    assert SCAN_TOPIC == "scan" and SCAN_TOPIC in SIDE_TOPICS and SCAN_TOPIC in RECORD_TOPICS
    assert SCAN_TOPIC not in extract.STAMPED_SIDE_TOPICS
    sess = _write_stamped(tmp_path, [
        (0.5, "raw", 0.5),                          # no scan logged yet -> none
        (0.90, "scan", 0.90),
        (0.97, "scan", 0.97),                       # latest before frame 1
        (1.0, "raw", 1.0),
        (1.01, "scan", 1.01),                       # nearer, but logged after: not frame 1's
        (2.0, "raw", 2.0),                          # latest before: 1.01, however old
    ])
    rows = _rows(sess, tmp_path)
    scans = [r["side"].get(SCAN_TOPIC) for r in rows]
    assert scans[0] is None
    assert scans[1]["stamp"] == pytest.approx(0.97, abs=1e-6)
    assert scans[2]["stamp"] == pytest.approx(1.01, abs=1e-6)
    assert rows[1]["dt"][SCAN_TOPIC] == pytest.approx(-0.03, abs=1e-6)
    assert rows[2]["dt"][SCAN_TOPIC] == pytest.approx(-0.99, abs=1e-6)
    s = scans[1]
    assert set(s) == {"stamp", "angle_min", "angle_increment", "range_min", "range_max",
                      "ranges"}
    assert s["ranges"][0] == pytest.approx(0.97, abs=1e-6)
    assert s["ranges"][1] is None and s["ranges"][2] is None and s["ranges"][3] == 1.5
    assert s["range_max"] == 8.0 and s["angle_increment"] == pytest.approx(1.57, abs=1e-6)


def _rows(sess, tmp_path):
    out = tmp_path / "out"
    assert extract.main([str(sess), "--out", str(out), "--min-interval", "0",
                         "--max-hamming", "-1"]) == 0
    return [json.loads(l) for l in (out / "frames.jsonl").read_text().splitlines()]


def test_shadow_logged_after_its_frame_attaches_to_that_frame(tmp_path):
    """WSL lap-1 bug: shadow for frame N (published after inference) landed on N+1."""
    pytest.importorskip("mcap_ros2")
    from control.recording import SHADOW_TOPIC

    sess = _write_stamped(tmp_path, [
        (0.95, "cmd", 1.0), (1.0, "raw", 1.0), (1.02, "line", 1.0), (1.1, "shadow", 1.0),
        (1.95, "cmd", 2.0), (2.0, "raw", 2.0), (2.02, "line", 2.0), (2.3, "shadow", 2.0),
        (3.0, "raw", 3.0),  # its shadow never came (skipped frame)
        (3.2, "shadow", 99.0),  # stamp of no frame in the bag: attaches nowhere
    ])
    rows = _rows(sess, tmp_path)
    assert extract.STAMP_TOL_S == 1e-6
    assert [r["t"] for r in rows] == [1.0, 2.0, 3.0]
    assert [(r["side"][SHADOW_TOPIC] or {}).get("stamp") for r in rows] == [1.0, 2.0, None]
    assert rows[0]["dt"][SHADOW_TOPIC] == pytest.approx(0.1)  # logged after its frame
    assert [(r["side"]["line/observation"] or {}).get("stamp") for r in rows] == [1.0, 2.0, None]
    # cmd_vel has no stamp: latest logged before the frame
    assert [r["side"]["cmd_vel"]["linear"]["x"] for r in rows] == [1.0, 2.0, 2.0]


def test_side_message_beyond_the_lookahead_window_is_not_attached(tmp_path):
    pytest.importorskip("mcap_ros2")
    from control.recording import SHADOW_TOPIC

    assert extract.SIDE_LOOKAHEAD_S == 0.5
    sess = _write_stamped(tmp_path, [
        (1.0, "raw", 1.0), (1.45, "line", 1.0), (1.6, "shadow", 1.0), (2.0, "raw", 2.0)])
    rows = _rows(sess, tmp_path)
    assert rows[0]["side"][SHADOW_TOPIC] is None
    assert rows[0]["side"]["line/observation"]["stamp"] == 1.0
    assert rows[1]["side"][SHADOW_TOPIC] is None


def test_compressed_camera_is_preferred_over_raw(tmp_path):
    pytest.importorskip("mcap_ros2")
    from control.recording import SHADOW_TOPIC

    events = []
    for t in (1.0, 2.0, 3.0):
        events += [(t, "raw", t), (t + 0.001, "jpeg", t), (t + 0.1, "shadow", t)]
    rows = _rows(_write_stamped(tmp_path, events), tmp_path)
    assert len(rows) == 3  # not six: raw frames are dropped when compressed exists
    assert [r["t"] for r in rows] == [1.0, 2.0, 3.0]  # header stamp, not log time
    assert [r["log_ns"] for r in rows] == [1_001_000_000, 2_001_000_000, 3_001_000_000]
    assert [r["side"][SHADOW_TOPIC]["stamp"] for r in rows] == [1.0, 2.0, 3.0]


def test_truncated_file_keeps_what_was_read_and_is_counted(tmp_path, capsys):
    """A crash-recovered snapshot can end mid-chunk; the rest of the session still extracts."""
    pytest.importorskip("mcap_ros2")
    sess = _write_stamped(tmp_path, [(1.0, "raw", 1.0), (2.0, "raw", 2.0)])
    good = sess / "bag" / "bag_0.mcap"
    full = good.read_bytes()
    (sess / "bag" / "bag_1.mcap").write_bytes(full[: len(full) // 2])  # cut mid-file
    (sess / "bag" / "bag_2.mcap").write_bytes(b"\x89MCAP0\r\n")  # magic only
    out = tmp_path / "out"
    assert extract.main([str(sess), "--out", str(out), "--min-interval", "0",
                         "--max-hamming", "-1"]) == 0
    rows = (out / "frames.jsonl").read_text().splitlines()
    assert len(rows) >= 2
    assert "truncated 2" in capsys.readouterr().out


def test_observation_logged_between_capture_and_its_own_image_attaches(tmp_path):
    """8kcn: 45/2258 line observations reached the recorder 37-61 us before their own
    image. The window opens at the frame's capture (header stamp), not its log time;
    evidence logged before the capture cannot be about that image."""
    pytest.importorskip("mcap_ros2")
    from control.recording import SHADOW_TOPIC

    sess = _write_stamped(tmp_path, [
        (1.00004, "line", 1.0),    # after capture 1.0, 60 us before its image's log time
        (1.0001, "raw", 1.0),
        (1.9999, "shadow", 2.0),   # stamp of frame 2 but logged before its capture
        (2.0001, "raw", 2.0),
    ])
    rows = _rows(sess, tmp_path)
    assert rows[0]["side"]["line/observation"]["stamp"] == 1.0
    assert -0.0001 <= rows[0]["dt"]["line/observation"] < 0  # logged before the image (4 dp)
    assert rows[1]["side"][SHADOW_TOPIC] is None


def _sidecar_row(i, stamp_s, side, dt):
    return {"index": i, "t": stamp_s, "stamp_ns": round(stamp_s * 1e9),
            "log_ns": round((stamp_s + 0.01) * 1e9), "side": side, "dt": dt}


def test_sidecar_rows_follow_the_same_two_class_clock_rule():
    """mp4 + sidecar input: stamped entries (with stamp_ns) are attached by stamp and
    window from wherever they sit; class (b) stays as the sidecar recorded it."""
    from control.recording import SHADOW_TOPIC

    cmd = {"linear": 0.03, "angular": 0.0}
    rows = [
        _sidecar_row(0, 1.0, {SHADOW_TOPIC: None, "cmd_vel": cmd},
                     {SHADOW_TOPIC: None, "cmd_vel": -0.02}),
        # frame 0's shadow held in row 1 (an older writer): logged 1.11 s, 0.1 s after
        # frame 0's log time; line/observation of frame 1 logged 50 us before its image
        _sidecar_row(1, 1.125, {
            SHADOW_TOPIC: {"stamp": 1.0, "error_delta": 0.1, "stamp_ns": 1_000_000_000},
            "line/observation": {"source": "CAMERA_LINE", "stamp": 1.125, "error": 0.2,
                                 "stamp_ns": 1_125_000_000},
            "cmd_vel": cmd},
            {SHADOW_TOPIC: -0.025, "line/observation": -0.00005, "cmd_vel": -0.02}),
        # frame 2's shadow logged 0.6 s after frame 2's log time: beyond the window
        _sidecar_row(2, 1.25, {SHADOW_TOPIC: None}, {SHADOW_TOPIC: None}),
        _sidecar_row(3, 2.0, {SHADOW_TOPIC: {"stamp": 1.25, "stamp_ns": 1_250_000_000}},
                     {SHADOW_TOPIC: -0.15}),
    ]
    got = extract.sidecar_side(rows)
    assert got[0][0][SHADOW_TOPIC]["error_delta"] == 0.1
    assert got[0][1][SHADOW_TOPIC] == pytest.approx(0.1)
    assert got[0][0]["cmd_vel"] == cmd and got[0][1]["cmd_vel"] == -0.02  # class (b) as is
    assert got[1][0]["line/observation"]["error"] == 0.2
    assert got[1][0][SHADOW_TOPIC] is None
    assert got[0][0]["line/observation"] is None
    assert got[2][0][SHADOW_TOPIC] is None and got[3][0][SHADOW_TOPIC] is None


def test_old_sidecar_without_stamp_ns_attaches_no_stamped_evidence():
    """Sidecars written before stamp_ns: stamped evidence is null, never shifted."""
    from control.recording import SHADOW_TOPIC

    rows = [_sidecar_row(0, 1.0, {SHADOW_TOPIC: None, "line/observation": None}, {}),
            _sidecar_row(1, 1.125, {SHADOW_TOPIC: {"stamp": 1.0, "error_delta": 0.1},
                                    "line/observation": {"stamp": 1.0, "error": 0.2}},
                         {SHADOW_TOPIC: -0.02, "line/observation": -0.03})]
    for side, dt in extract.sidecar_side(rows):
        assert side[SHADOW_TOPIC] is None and side["line/observation"] is None
        assert dt[SHADOW_TOPIC] is None


def test_ir_line_near_an_image_stamp_is_not_camera_evidence(tmp_path):
    """Audit 2026-10-01 (9dfk): an IR_LINE observation 0.05-0.78 ms from an image
    stamp won over the real CAMERA_LINE. Only CAMERA_LINE counts, within 1 us."""
    pytest.importorskip("mcap_ros2")
    sess = _write_stamped(tmp_path, [
        (1.0001, "raw", 1.0),
        (1.001, "irline", 1.0004),   # IR_LINE 0.4 ms from the image stamp, logged first
        (1.02, "line", 1.0),         # the camera's own answer
        (2.0001, "raw", 2.0),
        (2.001, "irline", 2.0004),   # IR only: nothing attaches
        (2.02, "line", 2.0005),      # CAMERA_LINE 0.5 ms off: not this image
    ])
    rows = _rows(sess, tmp_path)
    assert rows[0]["side"]["line/observation"]["source"] == "CAMERA_LINE"
    assert rows[0]["side"]["line/observation"]["stamp"] == 1.0
    assert rows[1]["side"]["line/observation"] is None


def test_sidecar_ignores_ir_line_evidence():
    rows = [_sidecar_row(0, 1.0, {"line/observation": None}, {}),
            _sidecar_row(1, 1.125, {"line/observation": {
                "source": "IR_LINE", "error": 0.2, "stamp_ns": 1_000_000_000}},
                {"line/observation": -0.02})]
    assert all(side["line/observation"] is None for side, _ in extract.sidecar_side(rows))


ODOM_FULL_DEF = """std_msgs/Header header
string child_frame_id
geometry_msgs/PoseWithCovariance pose
geometry_msgs/TwistWithCovariance twist
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
float64[36] covariance
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
================================================================================
MSG: geometry_msgs/TwistWithCovariance
Twist twist
float64[36] covariance
================================================================================
MSG: geometry_msgs/Twist
Vector3 linear
Vector3 angular
================================================================================
MSG: geometry_msgs/Vector3
float64 x
float64 y
float64 z
"""


def test_odom_is_attached_as_latest_before_with_pose_twist_and_stamps(tmp_path):
    pytest.importorskip("mcap_ros2")
    import math as _m

    from mcap_ros2.writer import Writer

    from control.recording import SIDE_TOPICS

    assert "odom" in SIDE_TOPICS and "odom" not in extract.STAMPED_SIDE_TOPICS
    bag = tmp_path / "sess" / "bag"
    bag.mkdir(parents=True)
    with open(bag / "bag_0.mcap", "wb") as fh:
        w = Writer(fh)
        img_s = w.register_msgdef("sensor_msgs/msg/Image", IMAGE_DEF)
        od_s = w.register_msgdef("nav_msgs/msg/Odometry", ODOM_FULL_DEF)
        for k, t in enumerate((0.95, 1.05)):  # the second is logged after the frame
            yaw = 0.2 * (k + 1)
            w.write_message("/pinky1/odom", od_s, {
                "header": {"stamp": {"sec": 0, "nanosec": int(t * 1e9) - 1000}, "frame_id": "odom"},
                "child_frame_id": "base",
                "pose": {"pose": {"position": {"x": 1.0 + k, "y": -2.0, "z": 0.0},
                                  "orientation": {"x": 0.0, "y": 0.0, "z": _m.sin(yaw / 2),
                                                  "w": _m.cos(yaw / 2)}},
                         "covariance": [0.0] * 36},
                "twist": {"twist": {"linear": {"x": 0.03, "y": 0.0, "z": 0.0},
                                    "angular": {"x": 0.0, "y": 0.0, "z": 0.1}},
                          "covariance": [0.0] * 36}}, int(t * 1e9), int(t * 1e9))
            if k == 0:
                px = np.zeros((4, 6, 3), np.uint8)
                w.write_message("/pinky1/camera/front", img_s, {
                    "header": {"stamp": {"sec": 0, "nanosec": 990_000_000}, "frame_id": "c"},
                    "height": 4, "width": 6, "encoding": "bgr8", "is_bigendian": 0,
                    "step": 18, "data": list(px.tobytes())}, 1_000_000_000, 1_000_000_000)
        w.finish()
    rows = _rows(tmp_path / "sess", tmp_path)
    odom = rows[0]["side"]["odom"]
    assert odom == {"stamp_ns": 949_999_000, "log_ns": 950_000_000, "x": 1.0, "y": -2.0,
                    "yaw": pytest.approx(0.2), "linear": 0.03, "angular": 0.1}
    assert rows[0]["dt"]["odom"] == pytest.approx(-0.05)


def test_late_evidence_dt_is_exact_from_integer_nanoseconds(tmp_path):
    """At epoch magnitude, float seconds lose ~0.1 ms in round(t - log_t, 4)."""
    pytest.importorskip("mcap_ros2")
    from control.recording import SHADOW_TOPIC

    base = 1_759_300_000.0  # 2025-10-01 epoch seconds
    sess = _write_stamped(tmp_path, [(base + 0.00015, "raw", base),
                                     (base + 0.10035, "shadow", base)])
    rows = _rows(sess, tmp_path)
    log_frame = rows[0]["log_ns"]
    assert rows[0]["dt"][SHADOW_TOPIC] == round((int(round((base + 0.10035) * 1e9)) - log_frame) / 1e9, 4)


def test_mcap_writes_null_for_unmatched_stamped_evidence_like_the_sidecar(tmp_path):
    """D-356: a frame without its stamped evidence says so (null), in both inputs."""
    pytest.importorskip("mcap_ros2")
    from control.recording import SHADOW_TOPIC

    rows = _rows(_write_stamped(tmp_path, [(1.0, "raw", 1.0), (1.1, "cmd", 1.0)]), tmp_path)
    for topic in extract.STAMPED_SIDE_TOPICS:
        assert topic in rows[0]["side"] and rows[0]["side"][topic] is None
        assert rows[0]["dt"][topic] is None
    assert SHADOW_TOPIC in extract.STAMPED_SIDE_TOPICS
