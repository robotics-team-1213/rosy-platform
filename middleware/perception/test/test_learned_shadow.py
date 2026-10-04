"""D-356 shadow wire shape: evidence only, never a command."""

import json

from control.sensing.perception.learned.lane_mask import LaneMaskEvidence
from control.sensing.perception.learned.runner import InferResult
from control.sensing.perception.learned.shadow import SHADOW_SCHEMA, shadow_payload


def test_payload_fields_and_json_roundtrip():
    r = InferResult(LaneMaskEvidence(True, 0.25, 0.8, {"floor": 0.9, "line": 0.1}),
                    87.5, "lane-seg-20260930-00000001")
    p = shadow_payload(r, stamp=12.5, rule_error=0.1)
    assert p == {
        "schema": SHADOW_SCHEMA, "stamp": 12.5, "model_revision": "lane-seg-20260930-00000001",
        "visible": True, "error": 0.25, "confidence": 0.8, "latency_ms": 87.5,
        "class_fractions": {"floor": 0.9, "line": 0.1}, "wall_fraction": 0.0,
        "rule_error": 0.1, "rule_visible": True, "error_delta": 0.15,
    }
    json.dumps(p)


def test_payload_without_rule_or_lane():
    r = InferResult(LaneMaskEvidence(False, None, 0.0, {}), 90.0, "rev")
    p = shadow_payload(r, stamp=1.0, rule_error=None)
    assert p["error"] is None and p["error_delta"] is None and p["rule_error"] is None
    assert p["rule_visible"] is None  # unknown, not "rule saw no lane"


def test_payload_rule_saw_no_lane_is_false_not_unknown():
    r = InferResult(LaneMaskEvidence(True, 0.2, 0.9, {}), 1.0, "rev")
    p = shadow_payload(r, stamp=1.0, rule_error=None, rule_visible=False)
    assert p["rule_visible"] is False and p["error_delta"] is None


def test_payload_has_no_command_fields():
    r = InferResult(LaneMaskEvidence(True, 0.0, 1.0, {}), 1.0, "rev")
    keys = set(shadow_payload(r, stamp=0.0, rule_error=None))
    assert not keys & {"linear", "angular", "cmd_vel", "twist"}


def test_learned_lane_node_main_shuts_down_like_line_observer():
    """Ctrl-C is not an error, and a context already shut down is not shut down twice."""
    import ast
    from pathlib import Path

    control = Path(__file__).resolve().parents[1] / "control"

    def main_src(name):
        tree = ast.parse((control / name).read_text(encoding="utf-8"))
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
        return ast.unparse(fn).replace("LineObserverNode", "Node").replace("LearnedLaneNode", "Node")

    got = main_src("learned_lane_node.py")
    assert got == main_src("line_observer_node.py")
    assert "except KeyboardInterrupt" in got and "if rclpy.ok():" in got
    assert "executor_choice.spin(node, rclpy)" in got


# ---- rule evidence matched to the inferred frame by stamp (D-373) ----
from control.sensing.perception.learned.shadow import RuleRing  # noqa: E402


def test_ring_exact_stamp_wins_over_newer():
    ring = RuleRing()
    ring.add(10.000, True, 0.1)
    ring.add(10.125, True, 0.5)
    ring.add(10.250, False, None)
    assert ring.match(10.1255) == (True, 0.5)  # within 1 ms
    assert ring.match(10.250) == (False, None)


def test_ring_nearest_within_0_2_s():
    ring = RuleRing()
    ring.add(10.0, True, 0.1)
    ring.add(10.3, True, 0.3)
    assert ring.match(10.12) == (True, 0.1)
    assert ring.match(10.2) == (True, 0.3)  # 0.1 from 10.3 beats 0.2 from 10.0


def test_ring_nothing_near_is_unknown():
    ring = RuleRing()
    ring.add(10.0, True, 0.1)
    assert ring.match(10.25) == (None, None)
    assert RuleRing().match(1.0) == (None, None)


def test_ring_forgets_after_window():
    ring = RuleRing(window_s=2.0)
    ring.add(10.0, True, 0.1)
    ring.add(12.5, True, 0.2)  # evicts 10.0 (older than 12.5 - 2.0)
    assert ring.match(10.0) == (None, None)
    assert ring.match(12.5) == (True, 0.2)


def test_ring_visible_without_numeric_error_counts_as_not_visible():
    ring = RuleRing()
    ring.add(1.0, True, None)
    ring.add(2.0, True, float("nan"))
    assert ring.match(1.0) == (False, None)
    assert ring.match(2.0) == (False, None)


def test_payload_carries_the_near_field_wall_fraction():
    r = InferResult(LaneMaskEvidence(True, 0.0, 1.0, {}, wall_fraction=0.3125), 1.0, "rev")
    assert shadow_payload(r, stamp=0.0, rule_error=None)["wall_fraction"] == 0.3125


def test_the_node_latches_visible_per_stream_before_publishing():
    """2026-10-02 audit: the visible hysteresis lives with the per-stream state, in the node;
    the published evidence is the latched one, and a model swap starts a fresh latch."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "control" / "learned_lane_node.py").read_text(encoding="utf-8")
    assert "VisibleHysteresis()" in src
    camera = src[src.index("def _on_camera"):src.index("def main")]
    assert camera.index("self._visible.update(") < camera.index("shadow_payload(")
    swap = camera[camera.index("if model.model_revision != self._logged_revision"):camera.index("self._busy = True")]
    assert "self._visible = VisibleHysteresis()" in swap
