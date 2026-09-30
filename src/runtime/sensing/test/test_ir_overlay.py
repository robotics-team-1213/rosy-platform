"""D-344 §12: the per-robot IR calibration overlay is validated before launch hands it over."""

from pathlib import Path

import pytest

from control.ir_overlay import IR_CALIBRATION_OVERLAY, overlay_problem, usable_overlay
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
