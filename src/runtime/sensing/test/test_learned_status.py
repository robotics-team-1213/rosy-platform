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
    assert p["skip_ratio"] == pytest.approx(0.25)
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
    assert "frame_skipped()" in src and "frame_in()" in src and "frame_inferred(" in src
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
