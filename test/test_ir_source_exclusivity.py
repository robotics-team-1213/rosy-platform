"""ir_sensor/range must have exactly one publisher per I2C bus.

The Python ``ir_adc_node`` (control, started by ``line_follow.launch.py`` in
the OS hardware graph) and the C++ ``sensor_adc`` node (legacy bench, manual
``ros2 run``) speak the same register protocol on the same bus and both
publish ``ir_sensor/range``. Running both interleaves arrays from two readers
of one bus and corrupts every IR consumer (safety cliff gates, line
observer).

Communication-protocol report 2026-09-22 §3.2.1 / remediation plan T2.
"""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = yaml.safe_load((ROOT / "tools/harness/platform_parts.yaml").read_text(encoding="utf-8"))["colcon_roots"]

#: Both launch files must carry this sentence so the rule is greppable where
#: an operator would wire the graph.
EXCLUSIVITY_MARKER = "ir_sensor/range single-publisher rule"

LINE_FOLLOW = ROOT / "middleware" / "perception" / "launch" / "line_follow.launch.py"
HARDWARE = ROOT / "middleware" / "core" / "navigation" / "launch" / "hardware.launch.py"
CALIB_NODE = ROOT / "middleware" / "perception" / "control" / "calib_node.py"


def _launch_files():
    return sorted(path for source in SOURCE_ROOTS
                  for manifest in (ROOT / source).rglob("package.xml")
                  for path in (manifest.parent / "launch").glob("*.py"))


def test_ir_scan_includes_nested_product_bringup():
    assert ROOT / "middleware" / "apps" / "device" / "pinky" / "bringup" / "launch" / "bringup_robot.launch.py" in _launch_files()


def _code_text(text: str) -> str:
    """Drop full-line comments — the exclusivity rule itself is documented in
    comments that must be allowed to name both publishers."""
    return "\n".join(
        line for line in text.splitlines()
        if not line.lstrip().startswith("#"))


def test_no_launch_starts_both_ir_publishers():
    for path in _launch_files():
        code = _code_text(path.read_text(encoding="utf-8"))
        if "ir_adc_node" in code:
            assert "sensor_adc" not in code, (
                f"{path} wires both IR publishers of ir_sensor/range")
        if "sensor_adc" in code:
            assert "ir_adc_node" not in code, (
                f"{path} wires both IR publishers of ir_sensor/range")


def test_line_follow_declares_single_publisher_gate():
    text = LINE_FOLLOW.read_text(encoding="utf-8")
    assert "start_ir_adc" in text, "line_follow must gate ir_adc_node"
    assert EXCLUSIVITY_MARKER in text


def test_hardware_launch_names_its_ir_source():
    text = HARDWARE.read_text(encoding="utf-8")
    assert "line_ir_enabled" in text
    code = _code_text(text)
    assert "sensor_adc" not in code, (
        "the OS hardware graph must not start the C++ sensor_adc; "
        "IR comes from ir_adc_node via line_follow")
    assert EXCLUSIVITY_MARKER in text


def test_calib_operator_messages_name_the_real_package():
    text = CALIB_NODE.read_text(encoding="utf-8")
    assert "pinky_sensor_adc" not in text, (
        "calib operator messages still point at the pre-rename package")
    assert "sensor_adc" in text


def test_rosy_io_graph_starts_ir_but_hardware_graph_does_not_double_it():
    """D-344 §12: rosy-io (motor/core modes) gets IR from bringup's enable_ir;
    the navigation hardware graph includes bringup without enable_ir and takes
    IR from line_follow instead. The two units conflict, so one reader per bus."""
    bringup = (ROOT / "middleware" / "apps" / "device" / "pinky" / "bringup" / "launch"
               / "bringup_robot.launch.py").read_text(encoding="utf-8")
    assert "DeclareLaunchArgument('enable_ir', default_value='false'" in bringup
    assert "condition=IfCondition(enable_ir)" in bringup
    assert EXCLUSIVITY_MARKER in bringup
    assert '"enable_ir"' not in _code_text(HARDWARE.read_text(encoding="utf-8"))
    native = ROOT / "deploy" / "robot" / "pinky_pro" / "native"
    io_unit = (native / "rosy-io.service").read_text(encoding="utf-8")
    assert "enable_ir:=true" in io_unit
    assert "Conflicts=rosy-navigation.service" in io_unit
