"""D-247 slice 1: the root, read-only board device probe (rosy-hw-probe).

The probe runs over a temporary root: /dev nodes, the CSI device-tree status,
/dev/kmsg and /etc/rosy are files under tmp_path. The I2C, UART, DYNAMIXEL and
command seams are replaced by a fake that records every bus access, so the
tests can assert what the probe did not touch as well as what it reported.
"""

from __future__ import annotations

import errno
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "deploy/robot/native"
BOOT_ID = "0b1f5d2e-8c3a-4f6e-9d7b-1a2b3c4d5e6f"
EREMOTEIO = getattr(errno, "EREMOTEIO", 121)  # Linux; Windows has no name for it
CSI = "proc/device-tree/axi/pcie@120000/rp1"


def _load():
    spec = importlib.util.spec_from_file_location("rosy_hw_probe", NATIVE / "rosy-hw-probe.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


probe_module = _load()


def _raw(value: int) -> bytes:
    """The two ADC bytes for a 12-bit raw value: raw = (d0 << 4) + (d1 >> 4)."""
    return bytes([value >> 4, (value & 0xF) << 4])


class FakeIo(probe_module.SystemIo):
    def __init__(self, root: Path, *, active=(), i2c=None, lidar=None, motors=None, commands=None,
                 i2c_delay_s: float = 0.0, states=None, holders=()) -> None:
        super().__init__(root)
        self.active = set(active)
        #: unit -> ActiveState, or a callable(unit, call_number) for a state that changes mid-run.
        self.states = states or {}
        self.holders = {} if holders == () else holders
        self.state_calls = 0
        self.i2c = i2c or {}
        self.lidar = lidar
        self.motors = motors
        self.commands = commands or {}
        self.i2c_delay_s = i2c_delay_s
        self.touched: list[tuple] = []

    def unit_state(self, unit):
        self.state_calls += 1
        if callable(self.states):
            return self.states(unit, self.state_calls)
        if unit in self.states:
            return self.states[unit]
        return "active" if unit in self.active else "inactive"

    def device_holders(self, devices):
        if self.holders is None:
            return None
        return {pid for pid, node in self.holders.items() if node in devices}

    def run(self, command):
        return self.commands.get(tuple(command))

    def i2c_read(self, bus, address, register, length, delay_s=0.0):
        self.touched.append(("i2c", bus, address, register))
        time.sleep(self.i2c_delay_s)
        reply = self.i2c.get((bus, address, register), OSError(EREMOTEIO, "remote I/O"))
        if isinstance(reply, Exception):
            raise reply
        return reply

    def lidar_health(self, device):
        self.touched.append(("uart", device))
        if isinstance(self.lidar, Exception):
            raise self.lidar
        return self.lidar or b""

    def dxl_ping(self, device, ids):
        self.touched.append(("dxl", device))
        if isinstance(self.motors, BaseException):
            raise self.motors
        return self.motors or {}


def _tree(tmp_path: Path, *, nodes=("rosy-motor", "ttyAMA0", "i2c-1", "spidev0.0"), csi=("disabled", "disabled"),
          kmsg: str | None = "") -> Path:
    root = tmp_path / "root"
    (root / "proc/sys/kernel/random").mkdir(parents=True)
    (root / "proc/sys/kernel/random/boot_id").write_text(BOOT_ID + "\n", encoding="ascii")
    (root / "dev").mkdir()
    for node in nodes:
        (root / "dev" / node).write_bytes(b"")
    for index, status in enumerate(csi):
        directory = root / CSI / f"csi@{110000 + index * 18000}"
        directory.mkdir(parents=True)
        (directory / "status").write_bytes(status.encode("ascii") + b"\0")
    if kmsg is not None:
        (root / "dev/kmsg").write_text(kmsg, encoding="utf-8")
    (root / "run/rosy-boot").mkdir(parents=True)
    return root


HEALTHY_ADC = {("dev/i2c-1", 0x08, register): _raw(value)
               for register, value in ((0xF8, 3963), (0x88, 1200), (0xC8, 1300), (0x98, 1400), (0xD8, 800))}
IMU_OK = {("dev/i2c-0", 0x28, 0x00): b"\xa0", ("dev/i2c-0", 0x28, 0x39): b"\x05",
          ("dev/i2c-0", 0x28, 0x3A): b"\x00"}
PI_OK = {("vcgencmd", "get_throttled"): (0, "throttled=0x0\n"),
         ("vcgencmd", "measure_temp"): (0, "temp=48.3'C\n"),
         ("vcgencmd", "pmic_read_adc", "EXT5V_V"): (0, "EXT5V_V volt(24)=5.12345678V\n")}
LIDAR_OK = b"\xa5\x5a\x03\x00\x00\x00\x06\x00\x00\x00"
MOTORS_OK = {1: (True, "ping 응답 · 모델 1200 · ID 1 · 1 Mbps"), 2: (True, "ping 응답 · 모델 1200 · ID 2 · 1 Mbps")}


def _states(rows) -> dict[str, str]:
    return {row.id: row.state for row in rows}


def _evidence(rows) -> dict[str, str]:
    return {row.id: row.evidence for row in rows}


# --- the device list and the schema ---------------------------------------------


def test_every_board_device_has_one_row_and_d169_decides_product():
    ids = [device[0] for device in probe_module.DEVICES]
    assert ids == ["motor.1", "motor.2", "lidar", "imu", "adc.battery", "adc.ir0", "adc.ir1", "adc.ir2",
                   "adc.ultrasonic", "camera", "lcd", "buzzer", "lamp", "pi.power"]
    product = {device[0] for device in probe_module.DEVICES if device[3]}
    # D-169 (Accepted): the product surface is the motors, the LiDAR, the camera and the ADC.
    assert product == {"motor.1", "motor.2", "lidar", "camera", "adc.battery", "adc.ir0", "adc.ir1",
                       "adc.ir2", "adc.ultrasonic"}


def test_a_healthy_board_reads_ok_where_a_machine_can_tell(tmp_path):
    root = _tree(tmp_path, nodes=("rosy-motor", "ttyAMA0", "i2c-0", "i2c-1", "spidev0.0", "ws281x_pwm"),
                 csi=("okay", "disabled"), kmsg="6,900,1000,-;ov5647 10-0036: Consider updating driver\n")
    io = FakeIo(root, active={"rosy-boot-display.service"}, i2c={**HEALTHY_ADC, **IMU_OK}, lidar=LIDAR_OK,
                motors=MOTORS_OK, commands=PI_OK)
    rows = probe_module.Probe(io).run()
    states = _states(rows)

    assert {key: value for key, value in states.items() if value != "ok"} == {
        "buzzer": "needs_human", "lamp": "needs_human"}
    evidence = _evidence(rows)
    assert evidence["adc.battery"].startswith("8.54 V")
    assert evidence["imu"] == "칩 ID 0xA0 · 상태 5 · 오류 0"
    assert evidence["pi.power"] == "throttled=0x0 · 48.3 °C · EXT5V 5.12 V"
    assert "모델 1200" in evidence["motor.1"]


def test_the_2026_09_25_rosy_18_board_shows_all_six_states(tmp_path):
    """rosy_18 as checked by hand: no i2c-0, wedged ADC, -121 camera, no lamp driver, rosy-io running."""
    kmsg = ("6,800,900,-;rp1-cfe 1f00110000.csi: Using DMA\n"
            "3,801,901,-;ov5647 10-0036: probe with driver ov5647 failed with error -121\n")
    root = _tree(tmp_path, csi=("okay", "okay"), kmsg=kmsg)
    io = FakeIo(root, active={"rosy-io.service", "rosy-boot-display.service"}, commands=PI_OK)
    rows = probe_module.Probe(io).run()
    states = _states(rows)

    assert states == {
        "motor.1": "not_measured", "motor.2": "not_measured", "lidar": "not_measured",
        "imu": "bus_missing",
        "adc.battery": "not_measured", "adc.ir0": "not_measured", "adc.ir1": "not_measured",
        "adc.ir2": "not_measured", "adc.ultrasonic": "not_measured",
        "camera": "no_response", "lcd": "ok", "buzzer": "needs_human", "lamp": "driver_missing",
        "pi.power": "ok",
    }
    assert set(states.values()) == set(probe_module.STATES)
    evidence = _evidence(rows)
    assert evidence["camera"] == "ov5647 10-0036 probe -121 · CSI 활성"
    assert "dtoverlay=i2c0-pi5,pins_0_1" in evidence["imu"]
    assert "rp1_ws281x_pwm" in evidence["lamp"]
    assert evidence["buzzer"].startswith("BCM 22 미확인 · 꺼짐")
    held = {row.id: row.held_by for row in rows if row.held_by}
    assert held == dict.fromkeys(["motor.1", "motor.2", "lidar", "adc.battery", "adc.ir0", "adc.ir1",
                                  "adc.ir2", "adc.ultrasonic"], "rosy-io.service")
    assert all("rosy-io 사용 중 — 토픽으로 판정" == evidence[key] for key in held)


def test_while_rosy_io_runs_its_buses_are_never_opened(tmp_path):
    root = _tree(tmp_path, nodes=("rosy-motor", "ttyAMA0", "i2c-0", "i2c-1"))
    io = FakeIo(root, active={"rosy-io.service"}, i2c={**HEALTHY_ADC, **IMU_OK}, lidar=LIDAR_OK, motors=MOTORS_OK)
    probe_module.Probe(io).run()

    # Only the bench IMU bus (not rosy-io's) was read.
    assert io.touched == [("i2c", "dev/i2c-0", 0x28, 0x00), ("i2c", "dev/i2c-0", 0x28, 0x39),
                          ("i2c", "dev/i2c-0", 0x28, 0x3A)]


def test_navigation_holds_the_same_buses(tmp_path):
    root = _tree(tmp_path)
    io = FakeIo(root, active={"rosy-navigation.service"}, i2c=HEALTHY_ADC, lidar=LIDAR_OK, motors=MOTORS_OK)
    rows = probe_module.Probe(io).run()
    assert not [item for item in io.touched if item[0] in {"uart", "dxl"} or item[1] == "dev/i2c-1"]
    assert _evidence(rows)["lidar"] == "rosy-navigation 사용 중 — 토픽으로 판정"


@pytest.mark.parametrize("state", [None, "activating", "deactivating", "reloading", "unknown"])
def test_an_unknown_or_moving_runtime_state_keeps_every_io_bus_closed(tmp_path, state):
    root = _tree(tmp_path)
    io = FakeIo(root, states={"rosy-io.service": state}, i2c=HEALTHY_ADC, lidar=LIDAR_OK, motors=MOTORS_OK)
    rows = probe_module.Probe(io).run()
    assert not [item for item in io.touched if item[0] in {"uart", "dxl"} or item[1] == "dev/i2c-1"]
    states = _states(rows)
    assert all(states[key] == "not_measured" for key in ("motor.1", "lidar", "adc.battery", "adc.ir2"))
    if state is None:
        assert _evidence(rows)["lidar"] == "rosy-io 상태 확인 불가 — 측정 안 함"


def test_a_failed_runtime_frees_its_buses(tmp_path):
    root = _tree(tmp_path)
    io = FakeIo(root, states={"rosy-io.service": "failed"}, i2c=HEALTHY_ADC, lidar=LIDAR_OK, motors=MOTORS_OK)
    assert _states(probe_module.Probe(io).run())["motor.1"] == "ok"


def test_a_runtime_that_starts_mid_run_is_seen_before_the_next_bus(tmp_path):
    root = _tree(tmp_path)

    def starting(unit, call):
        # Free for the motor check (calls 1-2), then rosy-io comes up.
        return "active" if unit == "rosy-io.service" and call > 2 else "inactive"

    io = FakeIo(root, states=starting, i2c=HEALTHY_ADC, lidar=LIDAR_OK, motors=MOTORS_OK)
    states = _states(probe_module.Probe(io).run())
    assert states["motor.1"] == "ok"
    assert states["lidar"] == states["adc.battery"] == "not_measured"
    assert ("uart", "dev/ttyAMA0") not in io.touched


def test_a_foreign_process_holding_a_uart_keeps_it_closed(tmp_path):
    root = _tree(tmp_path)
    io = FakeIo(root, holders={4242: "/dev/ttyAMA4"}, i2c=HEALTHY_ADC, lidar=LIDAR_OK, motors=MOTORS_OK)
    rows = probe_module.Probe(io).run()
    assert _states(rows)["motor.1"] == "not_measured"
    assert _evidence(rows)["motor.2"] == "다른 프로세스(pid 4242)가 사용 중 — 측정 안 함"
    assert ("dxl", "dev/rosy-motor") not in io.touched
    assert _states(rows)["lidar"] == "ok"

    blind = FakeIo(root, holders=None, lidar=LIDAR_OK, motors=MOTORS_OK)
    rows = probe_module.Probe(blind).run()
    assert _states(rows)["lidar"] == "not_measured" and not [i for i in blind.touched if i[0] in {"uart", "dxl"}]


def test_fd_holders_are_read_from_proc(tmp_path):
    root = _tree(tmp_path)
    fd = root / "proc/77/fd"
    fd.mkdir(parents=True)
    (root / "proc/78/fd").mkdir(parents=True)
    try:
        (fd / "3").symlink_to("/dev/ttyAMA0")
    except OSError:
        pytest.skip("no symlink rights on this host")
    assert probe_module.SystemIo(root).device_holders(("/dev/ttyAMA0",)) == {77}
    assert probe_module.SystemIo(root).device_holders(("/dev/ttyAMA4",)) == set()


def test_the_unit_state_is_read_like_rosy_boot_status(tmp_path):
    class Commands(probe_module.SystemIo):
        def run(self, command):
            self.command = command
            return (0, "activating\n")

    io = Commands(tmp_path)
    assert io.unit_state("rosy-io.service") == "activating"
    assert io.command == ["systemctl", "show", "--property=ActiveState", "--value", "rosy-io.service"]


# --- the wedged bus -------------------------------------------------------------


def test_a_wedged_adc_bus_ends_after_the_first_time_out(tmp_path):
    """2026-09-25: every transaction on the wedged bus took ~1 s and returned ETIMEDOUT."""
    root = _tree(tmp_path)
    wedged = {("dev/i2c-1", 0x08, register): OSError(errno.ETIMEDOUT, "timed out")
              for _channel, register in probe_module.ADC_CHANNELS}
    io = FakeIo(root, i2c=wedged, lidar=LIDAR_OK, motors=MOTORS_OK, i2c_delay_s=0.3)
    started = time.monotonic()
    rows = probe_module.Probe(io).run()
    elapsed = time.monotonic() - started

    adc = [item for item in io.touched if item[0] == "i2c" and item[1] == "dev/i2c-1"]
    assert adc == [("i2c", "dev/i2c-1", 0x08, 0xF8)], "one transaction, then the bus is left alone"
    assert elapsed < 1.0
    states = _states(rows)
    assert states["adc.battery"] == "no_response"
    assert "ETIMEDOUT" in _evidence(rows)["adc.battery"]
    assert "로봇 전원을 완전히 껐다 켜세요" in _evidence(rows)["adc.battery"]
    assert "Pi 재부팅으로는 풀리지 않습니다" in _evidence(rows)["adc.battery"]
    assert [states[f"adc.{name}"] for name in ("ir0", "ir1", "ir2", "ultrasonic")] == ["not_measured"] * 4


def test_a_missing_address_is_no_response_and_the_bus_goes_on(tmp_path):
    root = _tree(tmp_path)
    replies = dict(HEALTHY_ADC)
    replies[("dev/i2c-1", 0x08, 0x88)] = OSError(EREMOTEIO, "remote I/O")
    io = FakeIo(root, i2c=replies, lidar=LIDAR_OK, motors=MOTORS_OK)
    rows = probe_module.Probe(io).run()
    states = _states(rows)
    assert states["adc.ir0"] == "no_response" and "-121" in _evidence(rows)["adc.ir0"]
    assert states["adc.ir1"] == states["adc.ultrasonic"] == "ok"


def test_a_held_d192_lock_is_not_a_fault_and_ends_the_bus(tmp_path):
    root = _tree(tmp_path)
    replies = dict(HEALTHY_ADC)
    replies[("dev/i2c-1", 0x08, 0x88)] = probe_module.LockHeld("dev/i2c-1")
    io = FakeIo(root, i2c=replies, lidar=LIDAR_OK, motors=MOTORS_OK)
    rows = probe_module.Probe(io).run()
    states = _states(rows)
    assert states["adc.battery"] == "ok"
    assert [states[f"adc.{name}"] for name in ("ir0", "ir1", "ir2", "ultrasonic")] == ["not_measured"] * 4
    assert [item[3] for item in io.touched if item[1] == "dev/i2c-1"] == [0xF8, 0x88]
    # EAGAIN from the device itself is a transport error, not the lock.
    replies[("dev/i2c-1", 0x08, 0x88)] = OSError(errno.EAGAIN, "try again")
    assert _states(probe_module.Probe(FakeIo(root, i2c=replies, lidar=LIDAR_OK, motors=MOTORS_OK)).run())[
        "adc.ir0"] == "no_response"


def test_an_out_of_range_battery_needs_a_person(tmp_path):
    root = _tree(tmp_path)
    replies = dict(HEALTHY_ADC)
    replies[("dev/i2c-1", 0x08, 0xF8)] = _raw(0)
    rows = probe_module.Probe(FakeIo(root, i2c=replies, lidar=LIDAR_OK, motors=MOTORS_OK)).run()
    assert _states(rows)["adc.battery"] == "needs_human"
    assert "0.00 V" in _evidence(rows)["adc.battery"]


def test_full_scale_ir_and_ultrasonic_mean_nothing_detected_not_a_fault(tmp_path):
    """2026-09-25 hand test: 4095 is the idle/far reading of IR 0-2 and the ultrasonic."""
    root = _tree(tmp_path)
    replies = dict(HEALTHY_ADC)
    for register in (0x88, 0xC8, 0x98, 0xD8):
        replies[("dev/i2c-1", 0x08, register)] = _raw(4095)
    rows = probe_module.Probe(FakeIo(root, i2c=replies, lidar=LIDAR_OK, motors=MOTORS_OK)).run()
    for channel in ("adc.ir0", "adc.ir1", "adc.ir2", "adc.ultrasonic"):
        assert _states(rows)[channel] == "ok"
        assert _evidence(rows)[channel] == "4095 (감지 없음)"


def test_imu_in_config_mode_is_judged_by_chip_id_and_sys_err(tmp_path):
    """After power-on the BNO055 is in CONFIG mode (status 0, zero accel): that is fine."""
    root = _tree(tmp_path, nodes=("i2c-0",))
    config_mode = {("dev/i2c-0", 0x28, 0x00): bytes([0xA0]), ("dev/i2c-0", 0x28, 0x39): bytes([0]),
                   ("dev/i2c-0", 0x28, 0x3A): bytes([0])}
    io = FakeIo(root, i2c=config_mode)
    assert probe_module.Probe(io).imu().state == "ok"
    assert {item[3] for item in io.touched} == {0x00, 0x39, 0x3A}, "no accel or mode register"

    config_mode[("dev/i2c-0", 0x28, 0x3A)] = bytes([3])
    row = probe_module.Probe(FakeIo(root, i2c=config_mode)).imu()
    assert row.state == "needs_human" and "시스템 오류 3" in row.evidence


def test_a_wrong_imu_chip_id_is_no_response(tmp_path):
    root = _tree(tmp_path, nodes=("i2c-0",))
    io = FakeIo(root, i2c={("dev/i2c-0", 0x28, 0x00): b"\xff"})
    rows = probe_module.Probe(io).run()
    assert _states(rows)["imu"] == "no_response"
    assert _evidence(rows)["imu"] == "칩 ID 0xFF (기대 0xA0)"
    # BNO055: chip id only when it is wrong; nothing written, no mode register touched.
    assert [item for item in io.touched if item[1] == "dev/i2c-0"] == [("i2c", "dev/i2c-0", 0x28, 0x00)]


# --- UARTs, camera, LCD, lamp, Pi ------------------------------------------------


def test_missing_uarts_are_bus_missing_and_silent_ones_no_response(tmp_path):
    root = _tree(tmp_path, nodes=())
    rows = probe_module.Probe(FakeIo(root)).run()
    states = _states(rows)
    assert states["motor.1"] == states["lidar"] == states["adc.battery"] == states["lcd"] == "bus_missing"

    root = _tree(tmp_path / "second")
    silent = FakeIo(root, motors={1: (False, "ping 무응답 · ID 1"), 2: (True, "ping 응답 · ID 2")}, lidar=b"")
    states = _states(probe_module.Probe(silent).run())
    assert states["motor.1"] == "no_response" and states["motor.2"] == "ok"
    assert states["lidar"] == "no_response"


def test_without_dynamixel_sdk_the_motors_are_not_measured(tmp_path):
    root = _tree(tmp_path)
    rows = probe_module.Probe(FakeIo(root, motors=ImportError("dynamixel_sdk"), lidar=LIDAR_OK)).run()
    assert _states(rows)["motor.1"] == "not_measured"
    assert "dynamixel_sdk" in _evidence(rows)["motor.2"]


def test_a_camera_without_a_sensor_or_a_csi_is_no_response(tmp_path):
    root = _tree(tmp_path, csi=("disabled", "disabled"), kmsg="6,1,1,-;Booting Linux\n")
    row = probe_module.Probe(FakeIo(root)).camera()
    assert (row.state, row.evidence) == ("no_response", "CSI 비활성 · 센서 미검출")


def test_an_empty_second_port_does_not_fail_a_registered_camera(tmp_path):
    kmsg = ("3,1,1,-;ov5647 11-0036: probe with driver ov5647 failed with error -121\n"
            "6,2,2,-;ov5647 10-0036: Consider updating driver ov5647 to match on endpoints\n")
    root = _tree(tmp_path, csi=("okay", "okay"), kmsg=kmsg)
    row = probe_module.Probe(FakeIo(root)).camera()
    assert row.state == "ok"
    assert row.evidence == "ov5647 10-0036 커널 probe 성공 · CSI 활성 · 빈 포트 ov5647 11-0036 probe -121"


def test_the_csi_status_is_found_under_any_pcie_node(tmp_path):
    root = _tree(tmp_path, csi=(), kmsg="6,2,2,-;ov5647 10-0036: registered\n")
    node = root / "proc/device-tree/axi/pcie@1000120000/rp1/csi@110000"
    node.mkdir(parents=True)
    (node / "status").write_bytes(b"okay\0")
    assert probe_module.Probe(FakeIo(root)).camera().state == "ok"


def test_an_unreadable_kernel_log_is_not_measured(tmp_path):
    root = _tree(tmp_path, kmsg=None)
    assert probe_module.Probe(FakeIo(root)).camera().state == "not_measured"


def test_a_stopped_boot_display_leaves_the_lcd_to_a_person(tmp_path):
    root = _tree(tmp_path)
    assert probe_module.Probe(FakeIo(root)).lcd().state == "needs_human"


def test_the_buzzer_reads_its_pin_from_the_display_environment(tmp_path):
    root = _tree(tmp_path)
    (root / "etc/rosy").mkdir(parents=True)
    (root / "etc/rosy/boot-display.env").write_text("ROSY_BUZZER_ENABLED=true\nROSY_BUZZER_PIN=17\n",
                                                   encoding="utf-8")
    row = probe_module.Probe(FakeIo(root)).buzzer()
    assert row.state == "needs_human" and row.evidence.startswith("BCM 17 미확인 · 켜짐")


def test_pi_power_throttling_and_a_missing_vcgencmd(tmp_path):
    root = _tree(tmp_path)
    assert probe_module.Probe(FakeIo(root)).pi_power().state == "driver_missing"
    throttled = dict(PI_OK)
    throttled[("vcgencmd", "get_throttled")] = (0, "throttled=0x50005\n")
    row = probe_module.Probe(FakeIo(root, commands=throttled)).pi_power()
    assert row.state == "needs_human" and "지금 저전압" in row.evidence


def test_the_kernel_log_reader_strips_the_kmsg_prefix(tmp_path):
    root = _tree(tmp_path, kmsg="3,801,901,-;ov5647 10-0036: probe failed\n6,802,902,-;plain\n")
    assert probe_module.SystemIo(root).kernel_log() == ["ov5647 10-0036: probe failed", "plain"]


# --- the file CORE reads ----------------------------------------------------------


def test_main_writes_the_schema_atomically_for_core(tmp_path, capsys):
    root = _tree(tmp_path, csi=("okay", "okay"),
                 kmsg="3,1,1,-;ov5647: probe of 10-0036 failed with error -121\n")
    io = FakeIo(root, active={"rosy-io.service"}, commands=PI_OK)
    gid = os.getgid() if hasattr(os, "getgid") else 0

    assert probe_module.main(["--root", str(root)], io=io, group=lambda name: gid) == 0

    path = root / "run/rosy-boot/hardware.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert set(data) == {"schema", "measured_at", "boot_id", "devices"}
    assert data["schema"] == 1 and data["boot_id"] == BOOT_ID
    assert data["measured_at"].endswith("+00:00")
    assert [device["id"] for device in data["devices"]] == list(probe_module.DEVICE_IDS)
    for device in data["devices"]:
        assert set(device) - {"held_by"} == {"id", "label", "bus", "state", "evidence", "product"}
        assert device["state"] in probe_module.STATES
    camera = next(device for device in data["devices"] if device["id"] == "camera")
    assert camera["evidence"] == "ov5647 10-0036 probe -121 · CSI 활성"
    assert not list((root / "run/rosy-boot").glob(".hardware.json.*")), "no temporary file is left"
    summary = json.loads(capsys.readouterr().out)
    assert summary["hw_probe"]["not_measured"] == 8


@pytest.mark.skipif(os.name != "posix", reason="POSIX modes and groups")
def test_the_result_is_root_rosy_core_0640(tmp_path):
    root = _tree(tmp_path)
    probe_module.main(["--root", str(root)], io=FakeIo(root), group=lambda name: os.getgid())
    info = (root / "run/rosy-boot/hardware.json").stat()
    assert stat.S_IMODE(info.st_mode) == 0o640 and info.st_gid == os.getgid()


def test_a_result_younger_than_ten_seconds_is_kept(tmp_path, capsys):
    root = _tree(tmp_path)
    output = root / "run/rosy-boot/hardware.json"
    output.write_text("{}", encoding="utf-8")
    io = FakeIo(root, i2c=HEALTHY_ADC, lidar=LIDAR_OK, motors=MOTORS_OK)
    assert probe_module.main(["--root", str(root)], io=io, group=lambda name: None) == 0
    assert output.read_text(encoding="utf-8") == "{}" and io.touched == []
    assert json.loads(capsys.readouterr().out)["hw_probe"] == "skipped"

    old = time.time() - 60
    os.utime(output, (old, old))
    assert probe_module.main(["--root", str(root)], io=io, group=lambda name: None) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["schema"] == 1


def test_stdout_mode_writes_nothing(tmp_path, capsys):
    root = _tree(tmp_path)
    assert probe_module.main(["--root", str(root), "--stdout"], io=FakeIo(root)) == 0
    assert json.loads(capsys.readouterr().out)["schema"] == 1
    assert not (root / "run/rosy-boot/hardware.json").exists()


def test_the_probe_never_writes_a_device_register_or_torque():
    source = (NATIVE / "rosy-hw-probe.py").read_text(encoding="utf-8")
    for forbidden in ("write1ByteTxRx", "write2ByteTxRx", "write4ByteTxRx", "I2C_SLAVE_FORCE =", "0x0706",
                      "OPR_MODE", "0x3D"):
        assert forbidden not in source, forbidden
    # Scan and motor-start commands of the RPLIDAR protocol are never sent.
    for command in (b"\\xa5\\x20", b"\\xa5\\x82", b"\\xa5\\xa8"):
        assert command.decode() not in source


def test_the_wrapper_runs_the_probe_isolated():
    wrapper = (NATIVE / "rosy-hw-probe").read_text(encoding="utf-8")
    assert 'exec /usr/bin/python3 -I -B "$SCRIPT_DIR/rosy-hw-probe.py" "$@"' in wrapper
