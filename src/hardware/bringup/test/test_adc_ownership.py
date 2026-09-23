"""Who reads the I2C-1 ADC MCU (0x08), and how they share it (D-192).

The MCU keeps one register pointer. A reading is pointer write, ~6 ms settle,
two-byte read; two processes interleaving those steps read each other's
channel. Decision: every Rosy reader (rosylib.Battery in battery_publisher,
control's ir_adc_node) holds an exclusive flock on its /dev/i2c-1 descriptor
for the whole transaction. The bench-only C++ sensor_adc takes no lock and
is never started by the hardware launches.
"""

from __future__ import annotations

from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
REPO = PACKAGE.parents[2]
LAUNCH = PACKAGE / "launch" / "bringup_robot.launch.py"
HARDWARE_LAUNCH = REPO / "src/navigation/navigation/launch/hardware.launch.py"
IR_NODE = REPO / "src/apps/control/control/ir_adc_node.py"
BATTERY = PACKAGE / "rosylib" / "battery.py"
IO_UNIT = REPO / "deploy/robot/native/rosy-io.service"


def _code(path: Path) -> str:
    return "\n".join(line for line in path.read_text(encoding="utf-8").splitlines()
                     if not line.lstrip().startswith("#"))


def test_the_hardware_launches_never_start_the_unlocked_cpp_reader():
    for path in (LAUNCH, HARDWARE_LAUNCH):
        code = _code(path)
        assert "sensor_adc" not in code, path
        assert "executable='main_node'" not in code and 'executable="main_node"' not in code, path


def test_the_bringup_launch_reads_the_adc_only_through_battery_publisher():
    code = _code(LAUNCH)
    assert "executable='battery_publisher'" in code
    assert "condition=IfCondition(enable_battery)" in code
    assert "ir_adc_node" not in code


def test_both_rosy_readers_lock_the_bus_for_the_whole_transaction():
    ir = IR_NODE.read_text(encoding="utf-8")
    body = ir[ir.index("def read_channels"):ir.index("def close")]
    assert body.index("fcntl.flock(self._fd, fcntl.LOCK_EX)") < body.index("os.write(")
    assert body.index("os.read(") < body.index("fcntl.flock(self._fd, fcntl.LOCK_UN)")
    assert "finally:" in body

    battery = BATTERY.read_text(encoding="utf-8")
    assert "fcntl.flock(fd, fcntl.LOCK_EX)" in battery
    assert "fcntl.flock(fd, fcntl.LOCK_UN)" in battery


def test_the_io_unit_runs_the_battery_reader():
    unit = IO_UNIT.read_text(encoding="utf-8")
    assert "enable_battery:=true" in unit
    assert "DeviceAllow=/dev/i2c-1 rw" in unit
