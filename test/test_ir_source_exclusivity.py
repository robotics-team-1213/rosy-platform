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

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

#: Both launch files must carry this sentence so the rule is greppable where
#: an operator would wire the graph.
EXCLUSIVITY_MARKER = "ir_sensor/range single-publisher rule"

LINE_FOLLOW = SRC / "apps" / "control" / "launch" / "line_follow.launch.py"
HARDWARE = SRC / "navigation" / "navigation" / "launch" / "hardware.launch.py"
CALIB_NODE = SRC / "apps" / "control" / "control" / "calib_node.py"


def _launch_files():
    return sorted(SRC.glob("*/*/launch/*.py"))


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
