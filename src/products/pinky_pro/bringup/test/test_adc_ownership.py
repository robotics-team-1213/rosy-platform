"""Who reads the I2C-1 ADC MCU (0x08), and how they share it (D-192).

The MCU keeps one register pointer. A reading is pointer write, ~6 ms settle,
two-byte read; two processes interleaving those steps read each other's
channel. Decision: every reader holds an exclusive flock on its /dev/i2c-1
descriptor for the whole transaction — rosylib.Battery
(test_rosylib_battery.py), control's ir_adc_node (control/test/test_ir_adc_lock.py)
and the bench C++ sensor_adc (sensor_adc/test/test_adc_package_contract.py).
The C++ node still never runs beside ir_adc_node: both publish ir_sensor/range.
D-344 §12 adds the rosy-io lane-departure guard exception: bringup may start
ir_adc_node behind the default-false enable_ir flag (the navigation graph
owns the line_follow path; single publisher per bus is preserved).
"""

from __future__ import annotations

from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
REPO = PACKAGE.parents[3]
LAUNCH = PACKAGE / "launch" / "bringup_robot.launch.py"
HARDWARE_LAUNCH = REPO / "src/runtime/navigation/launch/hardware.launch.py"
IO_UNIT = REPO / "deploy/robot/pinky_pro/native/rosy-io.service"


def _code(path: Path) -> str:
    return "\n".join(line for line in path.read_text(encoding="utf-8").splitlines()
                     if not line.lstrip().startswith("#"))


def test_the_hardware_launches_never_start_the_cpp_reader():
    for path in (LAUNCH, HARDWARE_LAUNCH):
        code = _code(path)
        assert "sensor_adc" not in code, path
        assert "executable='main_node'" not in code and 'executable="main_node"' not in code, path


def test_the_bringup_launch_reads_the_adc_only_through_battery_publisher():
    code = _code(LAUNCH)
    assert "executable='battery_publisher'" in code
    assert "condition=IfCondition(enable_battery)" in code
    # D-344 §12 (lane-departure guard): ir_adc_node may appear in bringup
    # ONLY as the documented opt-in for the rosy-io graph - default false,
    # IfCondition-gated, carrying the line_follow dual-start warning. The
    # navigation hardware graph keeps it off (line_follow starts it); the
    # bus safety is D-192's flock, not this launch's composition.
    assert "DeclareLaunchArgument('enable_ir', default_value='false'" in code
    assert "Keep false when line_follow.launch" in code
    ir_pos = code.index("executable='ir_adc_node'")
    assert "condition=IfCondition(enable_ir)" in code
    assert code.index("condition=IfCondition(enable_ir)") > ir_pos


def test_the_io_unit_runs_the_battery_reader():
    unit = IO_UNIT.read_text(encoding="utf-8")
    assert "enable_battery:=true" in unit
    assert "DeviceAllow=/dev/i2c-1 rw" in unit
