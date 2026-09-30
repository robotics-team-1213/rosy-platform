"""D-373 decision 4: when a shadow/rule disagreement becomes a snapshot."""

import pytest

from control.capture_trigger import (
    DEFAULT_COOLDOWN_S,
    DEFAULT_DELTA_THRESHOLD,
    DEFAULT_FRAMES,
    CaptureTrigger,
    TriggerDecision,
)
from control.sensing.perception.learned.shadow import SHADOW_SCHEMA


_DERIVE = object()


def shadow(delta=None, *, error=0.1, rule_error=0.1, visible=True, stamp=1.0,
           rule_visible=_DERIVE):
    if delta is not None and error is not None and rule_error is None:
        rule_error = error - delta
    if rule_visible is _DERIVE:  # the rule answered: it saw a lane iff it gave an error
        rule_visible = rule_error is not None
    return {"schema": SHADOW_SCHEMA, "stamp": stamp, "model_revision": "rev",
            "visible": visible, "error": error, "rule_error": rule_error,
            "rule_visible": rule_visible, "error_delta": delta, "confidence": 0.9}


def feed(trig, payloads, t0=100.0, dt=0.125):
    out = []
    for i, p in enumerate(payloads):
        out.append(trig.on_shadow(p, t0 + i * dt))
    return out


def test_defaults():
    assert DEFAULT_DELTA_THRESHOLD == 0.35
    assert DEFAULT_FRAMES == 3
    assert DEFAULT_COOLDOWN_S == 30.0


def test_delta_streak_triggers_on_the_nth_frame():
    trig = CaptureTrigger()
    got = feed(trig, [shadow(0.4), shadow(-0.5), shadow(0.36)])
    assert got[:2] == [None, None]
    d = got[2]
    assert isinstance(d, TriggerDecision)
    assert d.reason == "error_delta"
    assert d.values["error_delta"] == [0.4, -0.5, 0.36]
    assert d.values["threshold"] == 0.35 and d.values["frames"] == 3
    assert d.values["model_revision"] == "rev"
    assert "stamp" in d.values and "error" in d.values and "rule_error" in d.values


def test_threshold_is_inclusive():
    trig = CaptureTrigger()
    assert feed(trig, [shadow(0.35)] * 3)[-1] is not None
    trig = CaptureTrigger()
    assert feed(trig, [shadow(-0.35)] * 3)[-1] is not None
    trig = CaptureTrigger()
    assert feed(trig, [shadow(0.3499)] * 5) == [None] * 5


def test_good_frame_resets_the_delta_streak():
    trig = CaptureTrigger()
    got = feed(trig, [shadow(0.5), shadow(0.5), shadow(0.1), shadow(0.5), shadow(0.5)])
    assert got == [None] * 5
    assert trig.on_shadow(shadow(0.5), 200.0) is not None


def test_none_delta_is_ignored_not_a_reset():
    trig = CaptureTrigger()
    # both see the lane but the rule evidence was stale -> delta None, rule_error None
    stale = shadow(None, error=None, rule_error=None, visible=False)
    got = feed(trig, [shadow(0.5), stale, shadow(0.5), stale, shadow(0.5)])
    assert got[-1] is not None and got[-1].reason == "error_delta"
    assert got[-1].values["error_delta"] == [0.5, 0.5, 0.5]


@pytest.mark.parametrize("bad", [True, "0.9", float("nan"), float("inf")])
def test_non_numeric_delta_is_ignored(bad):
    trig = CaptureTrigger()
    p = shadow(0.5)
    p["error_delta"] = bad
    assert feed(trig, [p] * 5) == [None] * 5


def test_learned_sees_lane_rule_does_not():
    trig = CaptureTrigger()
    p = shadow(None, error=0.2, rule_error=None)
    got = feed(trig, [p, p, p])
    assert got[:2] == [None, None]
    assert got[2].reason == "visibility_mismatch"
    assert got[2].values["learned_visible"] is True
    assert got[2].values["rule_visible"] is False
    assert got[2].values["frames"] == 3


def test_rule_sees_lane_learned_does_not():
    trig = CaptureTrigger()
    p = shadow(None, error=None, rule_error=0.1, visible=False)
    d = feed(trig, [p, p, p])[-1]
    assert d.reason == "visibility_mismatch"
    assert d.values["learned_visible"] is False and d.values["rule_visible"] is True


def test_visible_flag_false_counts_as_not_visible_even_with_an_error_value():
    trig = CaptureTrigger()
    p = shadow(None, error=0.2, rule_error=0.2, visible=False)
    assert feed(trig, [p, p, p])[-1].reason == "visibility_mismatch"


def test_agreement_resets_the_visibility_streak():
    trig = CaptureTrigger()
    mis = shadow(None, error=0.2, rule_error=None)
    both_blind = shadow(None, error=None, rule_error=None, visible=False)
    assert feed(trig, [mis, mis, both_blind, mis, mis]) == [None] * 5


def test_cooldown_blocks_then_releases():
    trig = CaptureTrigger(cooldown_s=30.0)
    assert feed(trig, [shadow(0.5)] * 3, t0=0.0)[-1] is not None  # t = 0.25
    # streaks restart after a trigger; a fresh streak inside the cooldown does not fire
    assert feed(trig, [shadow(0.5)] * 3, t0=10.0) == [None] * 3
    assert trig.on_shadow(shadow(0.5), 30.24) is None  # 29.99 s after the trigger
    d = trig.on_shadow(shadow(0.5), 30.25)  # exactly the cooldown: allowed
    assert d is not None and d.reason == "error_delta"


def test_operator_request_does_not_touch_the_auto_cooldown():
    trig = CaptureTrigger(cooldown_s=30.0)
    d = trig.on_request("  lap 3 weird turn ", 5.0)
    assert d.reason == "operator" and d.values == {"note": "lap 3 weird turn"}
    assert feed(trig, [shadow(0.5)] * 3, t0=6.0)[-1].reason == "error_delta"


def test_operator_request_keeps_the_auto_streak():
    trig = CaptureTrigger()
    assert feed(trig, [shadow(0.5)] * 2, t0=0.0) == [None, None]
    assert trig.on_request("x", 0.3).reason == "operator"
    assert trig.on_shadow(shadow(0.5), 0.4).reason == "error_delta"


def test_operator_requests_are_rate_limited_on_their_own_clock():
    from control.capture_trigger import DEFAULT_OPERATOR_COOLDOWN_S
    assert DEFAULT_OPERATOR_COOLDOWN_S == 5.0
    trig = CaptureTrigger()
    assert trig.on_request("a", 10.0) is not None
    assert trig.on_request("b", 14.99) is None
    assert trig.on_request("c", 15.0) is not None
    with __import__("pytest").raises(ValueError):
        CaptureTrigger(operator_cooldown_s=-1.0)


def test_operator_request_bypasses_the_automatic_cooldown():
    trig = CaptureTrigger(cooldown_s=30.0)
    assert feed(trig, [shadow(0.5)] * 3, t0=0.0)[-1] is not None
    assert trig.on_request("again", 1.0).reason == "operator"


def test_empty_operator_request_still_triggers_with_empty_note():
    assert CaptureTrigger().on_request("", 0.0).values == {"note": ""}


@pytest.mark.parametrize("junk", [None, [], "text", {"schema": "other/1", "error_delta": 0.9},
                                  {"error_delta": 0.9}])
def test_foreign_payloads_are_ignored(junk):
    trig = CaptureTrigger()
    assert feed(trig, [junk] * 5) == [None] * 5


def test_parameters_are_validated():
    with pytest.raises(ValueError):
        CaptureTrigger(delta_threshold=0.0)
    with pytest.raises(ValueError):
        CaptureTrigger(frames=0)
    with pytest.raises(ValueError):
        CaptureTrigger(cooldown_s=-1.0)


def test_custom_frames_and_threshold():
    trig = CaptureTrigger(delta_threshold=0.1, frames=1)
    d = trig.on_shadow(shadow(0.1), 0.0)
    assert d is not None and d.values["error_delta"] == [0.1]


def test_decision_has_no_command_fields():
    d = feed(CaptureTrigger(), [shadow(0.5)] * 3)[-1]
    assert not set(d.values) & {"linear", "angular", "cmd_vel", "twist"}


def test_capture_trigger_node_main_shuts_down_like_line_observer():
    import ast
    from pathlib import Path

    control = Path(__file__).resolve().parents[1] / "control"

    def main_src(name):
        tree = ast.parse((control / name).read_text(encoding="utf-8"))
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
        return (ast.unparse(fn).replace("LineObserverNode", "Node")
                .replace("CaptureTriggerNode", "Node"))

    assert main_src("capture_trigger_node.py") == main_src("line_observer_node.py")


def test_capture_trigger_node_is_evidence_only():
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "control" / "capture_trigger_node.py").read_text(
        encoding="utf-8")
    assert "create_publisher" not in src
    assert "rosbag2_interfaces.srv import Snapshot" in src
    assert "write_snapshot_request" in src  # the reason reaches session.json
    from control.recording import SHADOW_TOPIC
    assert f"create_subscription(String, '{SHADOW_TOPIC}', self._on_shadow, 10)" in src


def test_unknown_rule_evidence_never_counts_as_mismatch():
    """Stale/missing rule evidence (rule_visible null) is not "rule saw no lane"."""
    trig = CaptureTrigger()
    unknown = shadow(None, error=0.2, rule_error=None, rule_visible=None)
    assert feed(trig, [unknown] * 6) == [None] * 6


def test_unknown_rule_evidence_neither_extends_nor_breaks_a_mismatch_streak():
    trig = CaptureTrigger()
    mis = shadow(None, error=0.2, rule_error=None)
    unknown = shadow(None, error=0.2, rule_error=None, rule_visible=None)
    got = feed(trig, [mis, unknown, mis, unknown, mis])
    assert got[:4] == [None] * 4 and got[4].reason == "visibility_mismatch"


def test_payload_without_rule_visible_field_is_unknown():
    trig = CaptureTrigger()
    p = shadow(None, error=0.2, rule_error=None)
    del p["rule_visible"]
    assert feed(trig, [p] * 5) == [None] * 5


def test_capture_trigger_node_times_out_a_hung_snapshot_call():
    """A call that never answers must not leave its request file to pair with the next dump."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "control" / "capture_trigger_node.py").read_text(
        encoding="utf-8")
    assert "SNAPSHOT_CALL_TIMEOUT_S = 10.0" in src
    assert "remove_pending_request(future)" in src
    assert "self._forget(request)" in src
    assert "operator request ignored" in src  # D-62: a rate-limited request is said, not dropped


def test_capture_trigger_node_derives_the_recorder_service_from_its_namespace():
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "control" / "capture_trigger_node.py").read_text(
        encoding="utf-8")
    assert "snapshot_node_name(self.get_namespace())" in src
