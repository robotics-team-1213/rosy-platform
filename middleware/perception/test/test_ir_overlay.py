"""D-344 §12: the per-robot IR calibration overlay is validated before launch hands it over."""

from pathlib import Path

import pytest

from control.ir_overlay import (
    IR_CALIBRATION_OVERLAY, OPERATOR_KEYS, OPERATOR_OVERLAY, overlay_problem,
    usable_operator_overlay, usable_overlay)
from control.sensing.perception.ir_calibration import compute_ir_calibration, render_config

ROOT = Path(__file__).resolve().parents[1]
GOOD = """/**/line_observer_node:
  ros__parameters:
    ir_calibration_enabled: true
    ir_black: [1200.0, 1150.0, 1250.0]
    ir_white: [3100.0, 3000.0, 3200.0]
    ir_min_span: 100.0
"""


def test_absent_overlay_is_skipped(tmp_path):
    path, note = usable_overlay(str(tmp_path / "ir_calibration.yaml"))
    assert path is None and "absent" in note


def test_valid_overlay_is_loaded(tmp_path):
    target = tmp_path / "ir_calibration.yaml"
    target.write_text(GOOD, encoding="utf-8")
    assert usable_overlay(str(target)) == (str(target), f"{target} loaded")


@pytest.mark.parametrize("text, why", [
    ("{: [", "unreadable"),                                              # YAML syntax
    (GOOD.replace("1200.0", "1200"), "decimal"),                         # int → wrong ROS type
    (GOOD + "/**/ir_adc_node:\n  ros__parameters:\n    rate_hz: 20.0\n", "top level"),
    (GOOD.replace("ir_min_span: 100.0", "camera_bright_threshold: 180"), "only IR"),
    (GOOD.replace("3100.0", "1210.0"), "rejected"),                      # not separated
    (GOOD.replace("ir_calibration_enabled: true", "ir_calibration_enabled: yes please"), "true or false"),
    ("", "top level"),
])
def test_malformed_overlay_is_skipped_with_a_reason(tmp_path, text, why):
    target = tmp_path / "ir_calibration.yaml"
    target.write_text(text, encoding="utf-8")
    path, note = usable_overlay(str(target))
    assert path is None and why in note


def test_tool_output_observer_block_is_a_valid_overlay():
    yaml = pytest.importorskip("yaml")
    rows = lambda levels: [list(levels)] * 30                            # noqa: E731
    session = {"carpet": rows((1200, 1150, 1250)), "left": rows((3100, 1150, 1250)),
               "centre": rows((1200, 3000, 1250)), "right": rows((1200, 1150, 3200))}
    block = render_config(compute_ir_calibration(session)).split("\n\n")[0]
    assert overlay_problem(yaml.safe_load(block)) is None


def test_camera_launch_uses_the_validated_distinct_overlay_path():
    launch = (ROOT / "launch/camera_preview.launch.py").read_text(encoding="utf-8")
    assert "usable_overlay()" in launch and "/etc/rosy/line_follow.yaml" not in launch
    assert IR_CALIBRATION_OVERLAY == "/etc/rosy/ir_calibration.yaml"


def test_an_unimportable_checker_skips_the_overlay_instead_of_aborting(tmp_path, monkeypatch):
    import sys
    target = tmp_path / "ir_calibration.yaml"
    target.write_text(GOOD, encoding="utf-8")
    monkeypatch.setitem(sys.modules, "control.sensing.perception.lane", None)   # import → ImportError
    path, note = usable_overlay(str(target))
    assert path is None and "skipped" in note and "cannot check" in note


# D-344 §12 addendum 2026-10-03: the operator's camera lane overrides outside the release.
OPERATOR = """/**/line_observer_node:
  ros__parameters:
    camera_lane_mode: keep
    camera_ground_source: NOMINAL
    allow_nominal_ground: true
    nominal_camera_profile_path: /opt/rosy/current/install/share/pinky_pro/config/camera_nominal.yaml
    debug_overlay: true
    camera_pitch_rad_override: 0.19547687622336488
    camera_height_m_override: 0.059
"""


def test_absent_operator_overlay_keeps_todays_behaviour(tmp_path):
    path, note = usable_operator_overlay(str(tmp_path / "line_observer_overrides.yaml"))
    assert path is None and "absent" in note and "skipped" not in note


def test_valid_operator_overlay_is_loaded(tmp_path):
    target = tmp_path / "line_observer_overrides.yaml"
    target.write_text(OPERATOR, encoding="utf-8")
    assert usable_operator_overlay(str(target)) == (str(target), f"{target} loaded")


@pytest.mark.parametrize("text, why", [
    ("{: [", "unreadable"),
    (OPERATOR.replace("debug_overlay: true", "lane_graph_path: /tmp/g.yaml"), "allowed"),
    (OPERATOR.replace("camera_lane_mode: keep", "camera_lane_mode: route_a"), "camera_lane_mode"),
    (OPERATOR.replace("NOMINAL", "GAZEBO"), "camera_ground_source"),
    (OPERATOR.replace("debug_overlay: true", "debug_overlay: 1"), "true or false"),
    (OPERATOR.replace("/opt/rosy/current", "opt/rosy/current"), "absolute"),
    (OPERATOR.replace("0.059", "59"), "camera_height_m_override"),         # int, and mm
    (OPERATOR.replace("0.059", "0.59"), "camera_height_m_override"),       # outside range
    (OPERATOR.replace("0.19547687622336488", ".nan"), "camera_pitch_rad_override"),
    (OPERATOR.replace("    allow_nominal_ground: true\n", ""), "NOMINAL ground needs"),
    (OPERATOR.replace("camera_ground_source: NOMINAL", "camera_ground_source: PINKY"),
     "needs camera_ground_source: NOMINAL"),
    (OPERATOR.replace("    camera_ground_source: NOMINAL\n", ""), "needs camera_ground_source: NOMINAL"),
    (OPERATOR + "/**/road_observer_node:\n  ros__parameters:\n    debug_overlay: true\n", "top level"),
    (OPERATOR.replace("ros__parameters:", "params:"), "ros__parameters"),
])
def test_malformed_operator_overlay_is_skipped_with_a_reason(tmp_path, text, why):
    target = tmp_path / "line_observer_overrides.yaml"
    target.write_text(text, encoding="utf-8")
    path, note = usable_operator_overlay(str(target))
    assert path is None and "skipped" in note and why in note


def test_operator_keys_are_declared_observer_parameters():
    node = (ROOT / "control/line_observer_node.py").read_text(encoding="utf-8")
    for key in OPERATOR_KEYS:
        assert f"declare_parameter('{key}'" in node, key


def test_camera_launch_layers_the_operator_overlay_last_outside_the_release():
    launch = (ROOT / "launch/camera_preview.launch.py").read_text(encoding="utf-8")
    assert launch.index("line_params.append(overlay)") < launch.index("line_params.append(operator)")
    assert "usable_operator_overlay()" in launch
    assert OPERATOR_OVERLAY.startswith("/etc/rosy/") and OPERATOR_OVERLAY != IR_CALIBRATION_OVERLAY


def test_learned_paint_overlay_loads_the_existing_keep_pipeline(tmp_path):
    target = tmp_path / "learned.yaml"
    target.write_text(OPERATOR + "    paint_source: learned\n"
                      "    learned_lane_pointer: /var/lib/rosy/models/shadow\n"
                      "    learned_paint_every_n: 2\n    learned_paint_threads: 1\n", encoding="utf-8")
    assert usable_operator_overlay(str(target))[0] == str(target)


def test_learned_paint_every_n_accepts_four(tmp_path):
    target = tmp_path / "four.yaml"
    target.write_text(OPERATOR + "    paint_source: learned\n"
                      "    learned_lane_pointer: /var/lib/rosy/models/shadow\n"
                      "    learned_paint_every_n: 4\n", encoding="utf-8")
    assert usable_operator_overlay(str(target))[0] == str(target)


def test_learned_paint_motion_compensation_loads(tmp_path):
    target = tmp_path / "d570.yaml"
    target.write_text(OPERATOR + "    paint_source: learned\n"
                      "    learned_lane_pointer: /var/lib/rosy/models/shadow\n"
                      "    learned_paint_motion_compensation: true\n",
                      encoding="utf-8")
    assert usable_operator_overlay(str(target))[0] == str(target)


@pytest.mark.parametrize("extra", [
    "paint_source: unknown", "paint_source: learned", "learned_paint_threads: 0",
    "learned_paint_threads: true", "learned_paint_every_n: 0", "learned_paint_every_n: 5", "learned_paint_threads: 3",
    "learned_lane_pointer: relative/path", "learned_paint_motion_compensation: 1", "learned_paint_cadence: idle",
])
def test_unsafe_paint_overlay_is_skipped(tmp_path, extra):
    target = tmp_path / "bad.yaml"
    target.write_text(OPERATOR + "    " + extra + "\n", encoding="utf-8")
    assert usable_operator_overlay(str(target))[0] is None


def test_learned_paint_cannot_be_selected_in_a_mode_that_ignores_it(tmp_path):
    target = tmp_path / "wrong-mode.yaml"
    target.write_text(OPERATOR.replace("camera_lane_mode: keep", "camera_lane_mode: line")
                      + "    paint_source: learned\n"
                      "    learned_lane_pointer: /var/lib/rosy/models/shadow\n", encoding="utf-8")
    assert usable_operator_overlay(str(target))[0] is None
