"""D-373 decision 2: perception/learned/status says what the shadow node is doing (D-62)."""

import json

import pytest

from control.sensing.perception.learned.status import (
    STATUS_SCHEMA,
    STATUS_TOPIC,
    LearnedStatus,
)


def test_empty_status_says_no_model():
    s = LearnedStatus()
    p = s.payload(model_revision=None, last_error=None)
    assert p == {
        "schema": STATUS_SCHEMA,
        "model_revision": None,
        "last_error": "no shadow model loaded",
        "frames_in": 0,
        "frames_expected": 0,
        "frames_inferred": 0,
        "frames_skipped": 0,
        "skip_ratio": 0.0,
        "latency_ms_p50": None,
    }
    json.dumps(p)
    assert STATUS_SCHEMA == "rosy.perception.learned_status/1"
    assert STATUS_TOPIC == "perception/learned/status"


def test_loaded_model_without_error_reports_null_error():
    p = LearnedStatus().payload(model_revision="rev-a", last_error=None)
    assert p["model_revision"] == "rev-a" and p["last_error"] is None


def test_error_is_reported_even_with_a_model():
    p = LearnedStatus().payload(model_revision="rev-a", last_error="sha256 mismatch")
    assert p["last_error"] == "sha256 mismatch"


def test_counters_and_skip_ratio():
    s = LearnedStatus()
    for _ in range(4):
        s.frame_in()
    s.frame_inferred(10.0)
    s.frame_inferred(30.0)
    s.frame_skipped()
    p = s.payload(model_revision="r", last_error=None)
    assert (p["frames_in"], p["frames_inferred"], p["frames_skipped"]) == (4, 2, 1)
    # skip_ratio = frames not inferred / frames expected (here: arrivals, no stamps)
    assert p["skip_ratio"] == pytest.approx(0.5)
    assert p["latency_ms_p50"] == pytest.approx(20.0)


def test_p50_uses_only_the_last_window():
    s = LearnedStatus(window=3)
    for ms in (1000.0, 1000.0, 1000.0, 5.0, 7.0, 9.0):
        s.frame_in()
        s.frame_inferred(ms)
    assert s.payload(model_revision="r", last_error=None)["latency_ms_p50"] == pytest.approx(7.0)


def test_window_must_be_positive():
    with pytest.raises(ValueError):
        LearnedStatus(window=0)


def test_status_has_no_command_fields():
    s = LearnedStatus()
    s.frame_in()
    s.frame_inferred(1.0)
    keys = set(s.payload(model_revision="r", last_error=None))
    assert not keys & {"linear", "angular", "cmd_vel", "twist", "command", "enabled"}


def test_node_publishes_status_and_counts_busy_frames_as_skipped():
    """Source contract: the node wires the builder, a 1 Hz timer and the busy-skip count."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "control" / "learned_lane_node.py").read_text(
        encoding="utf-8")
    assert "STATUS_TOPIC" in src and "create_timer(1.0" in src
    assert "frame_skipped()" in src and "frame_inferred(" in src
    # arrivals carry the camera stamp so queue drops show up as gaps
    assert "frame_in(msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9)" in src
    assert "self._rules.match(stamp)" in src and "rule_visible=rule_visible" in src
    assert "cmd_vel" not in src.replace("never publishes cmd_vel", "")


def test_node_camera_subscription_is_best_effort_depth_one():
    """A reliable subscriber never matches camera_detect_node's sensor-data publisher."""
    import ast
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "control" / "learned_lane_node.py").read_text(
        encoding="utf-8")
    calls = [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call)
             and getattr(n.func, "attr", "") == "create_subscription"
             and isinstance(n.args[1], ast.Constant) and n.args[1].value == "camera/front"]
    assert len(calls) == 1
    assert ast.unparse(calls[0].args[3]) == (
        "QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT)")


# ---- frames the depth-1 queue dropped, from camera stamp gaps (D-373) ----
from control.sensing.perception.learned.status import expected_frames  # noqa: E402


@pytest.mark.parametrize("gap, n", [(0.125, 1), (0.25, 2), (0.30, 2), (0.375, 3),
                                    (0.19, 2), (0.18, 1), (0.0, 1), (-0.5, 1)])
def test_expected_frames_from_gap(gap, n):
    assert expected_frames(gap, period_s=0.125) == n


def test_expected_frames_long_gap_is_a_stream_restart():
    assert expected_frames(1.5, period_s=0.125, max_gap_s=1.0) == 1
    assert expected_frames(0.9, period_s=0.125, max_gap_s=1.0) == 7


def test_expected_frames_rejects_bad_period():
    with pytest.raises(ValueError):
        expected_frames(0.1, period_s=0.0)


def test_status_counts_queue_drops_into_the_skip_ratio():
    s = LearnedStatus(period_s=0.125)
    for stamp in (10.0, 10.125, 10.5, 10.625):  # 10.25 and 10.375 never arrived
        s.frame_in(stamp)
        s.frame_inferred(50.0)
    p = s.payload(model_revision="r", last_error=None)
    assert (p["frames_in"], p["frames_expected"], p["frames_inferred"]) == (4, 6, 4)
    assert p["skip_ratio"] == pytest.approx(2 / 6, abs=1e-4)


def test_status_busy_skip_and_queue_drop_both_count():
    s = LearnedStatus(period_s=0.125)
    s.frame_in(1.0)
    s.frame_inferred(10.0)
    s.frame_in(1.25)  # one dropped by the queue
    s.frame_skipped()  # and this one arrived while busy
    p = s.payload(model_revision="r", last_error=None)
    assert (p["frames_expected"], p["frames_inferred"], p["frames_skipped"]) == (3, 1, 1)
    assert p["skip_ratio"] == pytest.approx(2 / 3, abs=1e-4)


def test_status_without_stamps_falls_back_to_arrivals():
    s = LearnedStatus()
    s.frame_in()
    s.frame_in()
    s.frame_inferred(1.0)
    p = s.payload(model_revision="r", last_error=None)
    assert p["frames_expected"] == 2 and p["skip_ratio"] == pytest.approx(0.5)


def test_status_is_latched_and_published_at_start():
    """A late subscriber (dashboard, `ros2 topic echo` under load) still gets the last status."""
    import ast
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "control" / "learned_lane_node.py").read_text(
        encoding="utf-8")
    tree = ast.parse(src)
    pub = next(n for n in ast.walk(tree) if isinstance(n, ast.Call)
               and getattr(n.func, "attr", "") == "create_publisher"
               and ast.unparse(n.args[1]) == "STATUS_TOPIC")
    assert ast.unparse(pub.args[2]) == ("QoSProfile(depth=1, durability=DurabilityPolicy."
                                        "TRANSIENT_LOCAL, reliability=ReliabilityPolicy.RELIABLE)")
    init = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "__init__")
    assert ast.unparse(init.body[-1]) == "self._publish_status()"
