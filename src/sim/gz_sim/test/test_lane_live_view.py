"""ROS-free tests for lane_live_view.py: it is a ROS script (rclpy,
sensor_msgs/nav_msgs/std_msgs) that cannot run on this Windows host, but
its HTTP/HTML/MJPEG/state logic must stay importable and testable here,
same pattern as junction_harness.py / test_junction_harness_contract.py."""

import importlib.util
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GRAPH = ROOT.parents[1] / "apps" / "control" / "map" / "map_v2_fleet" / "lane_graph.yaml"


def _mod():
    spec = importlib.util.spec_from_file_location(
        "lane_live_view", ROOT / "scripts" / "lane_live_view.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_module_imports_without_ros():
    mod = _mod()
    assert mod.DEFAULT_PORT == 28183
    assert mod.DEFAULT_CORE_URL == "http://127.0.0.1:8080"
    assert mod.DEFAULT_TRAIL == 2000
    assert callable(mod.main)


def test_ros_imports_are_deferred_out_of_module_scope():
    source = (ROOT / "scripts" / "lane_live_view.py").read_text(encoding="utf-8")
    header = source.split("def build_node(", 1)[0]
    assert "import rclpy" not in header
    assert "from rclpy" not in header
    assert "from nav_msgs" not in header
    assert "from sensor_msgs" not in header
    assert "from std_msgs" not in header


def test_module_creates_no_publishers():
    """Observation only: the viewer must never gain motion authority."""
    source = (ROOT / "scripts" / "lane_live_view.py").read_text(encoding="utf-8")
    assert "create_publisher" not in source


def test_viewer_binds_all_interfaces_so_windows_can_reach_wsl():
    source = (ROOT / "scripts" / "lane_live_view.py").read_text(encoding="utf-8")
    assert '("0.0.0.0", args.port)' in source


# ---------------------------------------------------------------------
# HTML page
# ---------------------------------------------------------------------


def test_index_html_has_the_required_panels_and_endpoints():
    mod = _mod()
    html = mod.render_index_html()
    assert "/overlay.mjpg" in html
    assert "/camera.mjpg" in html
    assert "/status.json" in html
    assert "/graph.json" in html
    assert 'id="overlay"' in html
    assert 'id="camera"' in html
    assert 'id="map"' in html
    assert "<canvas" in html
    assert "NO DATA" in html


def test_index_html_is_self_contained_dark_and_legible():
    mod = _mod()
    html = mod.render_index_html()
    assert "<script src=" not in html
    assert "<link rel=\"stylesheet\"" not in html
    assert "background: #111318" in html or "color-scheme: dark" in html


# ---------------------------------------------------------------------
# MJPEG framing
# ---------------------------------------------------------------------


def test_mjpeg_part_framing_has_boundary_content_type_and_length():
    mod = _mod()
    fake_jpeg = b"\xff\xd8fake-jpeg-bytes-from-a-fake-frame-source\xff\xd9"
    part = mod.mjpeg_part(fake_jpeg)

    head, _, rest = part.partition(b"\r\n\r\n")
    lines = head.split(b"\r\n")
    assert lines[0] == f"--{mod.BOUNDARY}".encode("ascii")
    headers = dict(line.split(b": ", 1) for line in lines[1:])
    assert headers[b"Content-Type"] == b"image/jpeg"
    assert int(headers[b"Content-Length"]) == len(fake_jpeg)
    assert rest == fake_jpeg + b"\r\n"


def test_mjpeg_part_framing_is_stable_across_different_frame_sizes():
    mod = _mod()
    for size in (0, 1, 4096):
        frame = bytes(range(256)) * (size // 256 + 1)
        frame = frame[:size]
        part = mod.mjpeg_part(frame)
        head, _, rest = part.partition(b"\r\n\r\n")
        headers = dict(line.split(b": ", 1) for line in head.split(b"\r\n")[1:])
        assert int(headers[b"Content-Length"]) == size
        assert rest == frame + b"\r\n"


# ---------------------------------------------------------------------
# Frame stream: fps + staleness / NO DATA
# ---------------------------------------------------------------------


def test_frame_stream_reports_no_data_until_first_publish():
    mod = _mod()
    stream = mod.FrameStream()
    health = stream.health(now=100.0)
    assert health == {"ok": False, "age_s": None, "fps": 0.0}


def test_frame_stream_is_fresh_right_after_publish_and_goes_stale_later():
    mod = _mod()
    stream = mod.FrameStream()
    stream.publish(b"frame-bytes", now=10.0)

    fresh = stream.health(now=10.5)
    assert fresh["ok"] is True
    assert fresh["age_s"] == 0.5

    stale = stream.health(now=10.0 + mod.STREAM_STALE_S + 1.0)
    assert stale["ok"] is False


def test_frame_stream_latest_returns_the_most_recent_frame():
    mod = _mod()
    stream = mod.FrameStream()
    stream.publish(b"first", now=0.0)
    stream.publish(b"second", now=0.2)
    data, ts = stream.latest()
    assert data == b"second"
    assert ts == 0.2


def test_frame_stream_fps_counts_publishes_within_the_window():
    mod = _mod()
    stream = mod.FrameStream()
    for t in (0.0, 0.2, 0.4, 0.6, 0.8):
        stream.publish(b"f", now=t)
    health = stream.health(now=0.8)
    assert health["fps"] > 0.0

    old = mod.FrameStream()
    old.publish(b"f", now=0.0)
    health_after_window = old.health(now=0.0 + mod.FPS_WINDOW_S + 5.0)
    assert health_after_window["fps"] == 0.0


# ---------------------------------------------------------------------
# Trail reset
# ---------------------------------------------------------------------


def test_trail_accumulates_points_normally():
    mod = _mod()
    trail = mod.Trail(maxlen=10)
    assert trail.add(0.0, 0.0, now=0.0) is False
    assert trail.add(0.01, 0.0, now=0.1) is False
    assert trail.as_list() == [(0.0, 0.0), (0.01, 0.0)]


def test_trail_resets_on_a_pose_jump_beyond_threshold():
    mod = _mod()
    trail = mod.Trail(maxlen=10)
    trail.add(0.0, 0.0, now=0.0)
    trail.add(0.01, 0.0, now=0.1)
    reset = trail.add(1.0, 1.0, now=0.2)
    assert reset is True
    assert trail.as_list() == [(1.0, 1.0)]


def test_trail_does_not_reset_on_a_small_jump():
    mod = _mod()
    trail = mod.Trail(maxlen=10)
    trail.add(0.0, 0.0, now=0.0)
    reset = trail.add(0.0 + mod.POSE_JUMP_RESET_M - 0.05, 0.0, now=0.1)
    assert reset is False
    assert len(trail.as_list()) == 2


def test_trail_resets_on_odom_silence_beyond_threshold():
    mod = _mod()
    trail = mod.Trail(maxlen=10)
    trail.add(0.0, 0.0, now=0.0)
    reset = trail.add(0.02, 0.0, now=mod.ODOM_SILENCE_RESET_S + 1.0)
    assert reset is True
    assert trail.as_list() == [(0.02, 0.0)]


def test_trail_respects_maxlen():
    mod = _mod()
    trail = mod.Trail(maxlen=3)
    for i in range(5):
        trail.add(i * 0.01, 0.0, now=i * 0.1)
    assert len(trail.as_list()) == 3


# ---------------------------------------------------------------------
# Status JSON shape
# ---------------------------------------------------------------------


def test_status_json_shape():
    mod = _mod()
    core = {"mode": "CAMERA_LINE", "state": "RUNNING", "reason": "", "error": 0.01, "confidence": 0.9}
    observation = {"source": "camera", "visible": True, "error": 0.01, "confidence": 0.9}
    odom = {"x": 1.0, "y": 2.0, "yaw": 0.1, "speed": 0.2}
    overlay_health = {"ok": True, "age_s": 0.1, "fps": 5.0}
    camera_health = {"ok": True, "age_s": 0.1, "fps": 5.0}

    status = mod.build_status(core, observation, odom, overlay_health, camera_health, now=10.0)

    assert status["core"] == core
    assert status["observation"] == observation
    assert status["odom"] == odom
    assert status["streams"] == {"overlay": overlay_health, "camera": camera_health}
    assert status["timestamp"] == 10.0
    json.dumps(status)  # must round-trip through the HTTP JSON encoder


def test_status_json_shape_defaults_to_empty_dicts_before_any_data():
    mod = _mod()
    status = mod.build_status(None, None, None, {"ok": False, "age_s": None, "fps": 0.0},
                               {"ok": False, "age_s": None, "fps": 0.0}, now=0.0)
    assert status["core"] == {}
    assert status["observation"] == {}
    assert status["odom"] == {}


def test_viewer_state_status_reflects_live_stream_health():
    mod = _mod()
    state = mod.ViewerState({"segments": {}, "nodes": {}})
    state.overlay.publish(b"x", now=1.0)
    status = state.status(now=1.1)
    assert status["streams"]["overlay"]["ok"] is True
    assert status["streams"]["camera"]["ok"] is False  # never published: NO DATA


def test_viewer_state_setters_are_reflected_in_status():
    mod = _mod()
    state = mod.ViewerState({"segments": {}, "nodes": {}})
    state.set_core({"mode": "CAMERA_LINE"})
    state.set_observation({"visible": True})
    state.set_odom({"x": 1.0, "y": 2.0})
    status = state.status(now=0.0)
    assert status["core"] == {"mode": "CAMERA_LINE"}
    assert status["observation"] == {"visible": True}
    assert status["odom"] == {"x": 1.0, "y": 2.0}


# ---------------------------------------------------------------------
# Graph loading
# ---------------------------------------------------------------------


def test_load_graph_reads_segments_and_nodes_from_the_real_lane_graph():
    mod = _mod()
    assert GRAPH.is_file(), f"expected lane_graph.yaml at {GRAPH}"
    graph = mod.load_graph(GRAPH)

    assert "segments" in graph and "nodes" in graph
    assert "east" in graph["segments"]
    assert len(graph["segments"]["east"]) > 1
    assert all(len(p) == 2 for p in graph["segments"]["east"][:5])
    assert "NE" in graph["nodes"]
    assert graph["nodes"]["NE"] == [-0.1818, 0.1999]


def test_load_graph_ignores_non_polyline_top_level_keys(tmp_path):
    mod = _mod()
    fixture = tmp_path / "graph.yaml"
    fixture.write_text(
        "nodes:\n  A: [0.0, 0.0]\n  B: [1.0, 0.0]\n"
        "segments:\n  a_to_b:\n    from: A\n    to: B\n    points:\n"
        "    - [0.0, 0.0]\n    - [0.5, 0.0]\n    - [1.0, 0.0]\n"
        "parking:\n  spot: [2.0, 0.0, 0.0]\n"
        "roundabout:\n  radius_m: 0.25\n",
        encoding="utf-8")

    graph = mod.load_graph(fixture)

    assert graph == {
        "segments": {"a_to_b": [[0.0, 0.0], [0.5, 0.0], [1.0, 0.0]]},
        "nodes": {"A": [0.0, 0.0], "B": [1.0, 0.0]},
    }


# ---------------------------------------------------------------------
# Odometry quaternion -> yaw
# ---------------------------------------------------------------------


def test_yaw_from_identity_quaternion_is_zero():
    mod = _mod()
    assert abs(mod.yaw_from_quaternion(0.0, 0.0, 0.0, 1.0)) < 1e-9


def test_yaw_from_quaternion_matches_a_known_90_degree_turn():
    mod = _mod()
    yaw = mod.yaw_from_quaternion(0.0, 0.0, math.sin(math.pi / 4), math.cos(math.pi / 4))
    assert abs(yaw - math.pi / 2) < 1e-9


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------


def test_cli_takes_port_graph_core_url_and_trail():
    mod = _mod()
    try:
        mod.main(["--help"])
    except SystemExit as exc:
        assert exc.code == 0
    else:
        raise AssertionError("--help should exit")


def test_cli_defaults_match_the_documented_port_and_core_url():
    source = (ROOT / "scripts" / "lane_live_view.py").read_text(encoding="utf-8")
    assert '"--port", type=int, default=DEFAULT_PORT' in source
    assert '"--core-url", default=DEFAULT_CORE_URL' in source
    assert '"--trail", type=int, default=DEFAULT_TRAIL' in source
    assert '"--graph", type=Path, required=True' in source


# ---------------------------------------------------------------------
# Source shape: sensible thread/shutdown wiring
# ---------------------------------------------------------------------


def test_http_server_and_ros_spin_run_on_separate_threads():
    source = (ROOT / "scripts" / "lane_live_view.py").read_text(encoding="utf-8")
    assert "target=spin, args=(rclpy_module, node, stop_event)" in source
    assert "httpd.serve_forever()" in source


def test_sigint_triggers_a_clean_shutdown():
    source = (ROOT / "scripts" / "lane_live_view.py").read_text(encoding="utf-8")
    assert "signal.signal(signal.SIGINT, handle_sigint)" in source
    main_source = source.split("def main(", 1)[1]
    assert "stop_event.set()" in main_source
    assert "node.destroy_node()" in main_source
    assert "rclpy_module.shutdown()" in main_source


def test_core_poll_runs_off_the_ros_callback_thread():
    """CORE's HTTP API poll uses blocking urllib calls; it must not run on
    the same thread as rclpy.spin_once, or a slow/hung CORE would stall
    every ROS callback (frame publishing included)."""
    source = (ROOT / "scripts" / "lane_live_view.py").read_text(encoding="utf-8")
    assert "target=core_poll_loop, args=(state, args.core_url, stop_event)" in source
    poll_source = source.split("def core_poll_loop(", 1)[1].split("\ndef ", 1)[0]
    assert "spin_once" not in poll_source
