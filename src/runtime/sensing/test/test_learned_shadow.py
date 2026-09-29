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
        "class_fractions": {"floor": 0.9, "line": 0.1},
        "rule_error": 0.1, "error_delta": 0.15,
    }
    json.dumps(p)


def test_payload_without_rule_or_lane():
    r = InferResult(LaneMaskEvidence(False, None, 0.0, {}), 90.0, "rev")
    p = shadow_payload(r, stamp=1.0, rule_error=None)
    assert p["error"] is None and p["error_delta"] is None and p["rule_error"] is None


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
