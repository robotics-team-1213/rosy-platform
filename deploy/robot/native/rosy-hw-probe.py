#!/usr/bin/env python3
"""Observe every board device as root, read-only, outside CORE (D-247).

CORE never opens a device (D-161). This program does, once after boot and
again when an administrator asks (rosy-hw-probe.path), and writes what it saw
to /run/rosy-boot/hardware.json, root:rosy-core 0640, the way rosy-login-code
hands CORE its verifier (D-193). CORE only reads that file.

Rules (D-247 5):

* Known addresses only; never a bus scan.
* Per-device time limits. The first time-out on an I2C bus ends that bus: the
  remaining devices there are `not_measured` (a wedged bus costs ~1 s per
  transaction, which a scan would turn into minutes).
* 0x08 on /dev/i2c-1 is read under the D-192 flock.
* BNO055: chip id and status registers only; the operating mode is never written.
* Motors: a torque-free ping, only while rosy-io is not running. No register write.
* Camera: the kernel's probe result (/dev/kmsg) and the CSI node status only.
* While rosy-io (or rosy-navigation) holds the motor UART, the LiDAR UART and
  0x08, those rows are `not_measured`; CORE judges them from topic freshness.

`--root` points every path at a fake tree for host tests; the I2C, UART,
DYNAMIXEL and command seams are methods of `SystemIo` that tests replace.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import errno as errno_codes
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from typing import Callable, Optional

sys.dont_write_bytecode = True

SCHEMA = 1
STATUS_DIR = "run/rosy-boot"
OUTPUT = f"{STATUS_DIR}/hardware.json"
BOOT_ID = "proc/sys/kernel/random/boot_id"
DISPLAY_ENV = "etc/rosy/boot-display.env"
KMSG = "dev/kmsg"
CSI_GLOB = "proc/device-tree/axi/pcie@120000/rp1/csi@*/status"
CORE_GROUP = "rosy-core"

OK = "ok"
NO_RESPONSE = "no_response"
BUS_MISSING = "bus_missing"
DRIVER_MISSING = "driver_missing"
NEEDS_HUMAN = "needs_human"
NOT_MEASURED = "not_measured"
STATES = (OK, NO_RESPONSE, BUS_MISSING, DRIVER_MISSING, NEEDS_HUMAN, NOT_MEASURED)

#: Units that open the motor UART, the LiDAR UART and /dev/i2c-1 (rosy-io.service DeviceAllow).
IO_UNITS = ("rosy-io.service", "rosy-navigation.service")
DISPLAY_UNIT = "rosy-boot-display.service"

MOTOR_DEV = "dev/rosy-motor"
MOTOR_BAUD = 1_000_000
MOTOR_IDS = (1, 2)
LIDAR_DEV = "dev/ttyAMA0"
LIDAR_BAUD = 460_800
IMU_BUS = "dev/i2c-0"
IMU_ADDRESS = 0x28
IMU_CHIP_ID = 0xA0
ADC_BUS = "dev/i2c-1"
ADC_ADDRESS = 0x08
#: rosylib Battery / D-192: write the register, wait ~6 ms, read two bytes.
ADC_DELAY_S = 0.006
ADC_CHANNELS = (("adc.battery", 0xF8), ("adc.ir0", 0x88), ("adc.ir1", 0xC8), ("adc.ir2", 0x98),
                ("adc.ultrasonic", 0xD8))
ADC_FULL_SCALE = 4095
#: V = raw / 4096 * 4.096 / (13 / 28) (board divider).
BATTERY_RANGE_V = (6.0, 8.8)
LCD_SPI = "dev/spidev0.0"
LAMP_NODE = "dev/ws281x_pwm"
BUZZER_DEFAULT_PIN = 22
LOCK_WAIT_S = 2.0
COMMAND_TIMEOUT_S = 3.0
CAMERA_SENSORS = re.compile(r"\b(ov5647|imx219|imx708)\b")
PROBE_FAILED = re.compile(r"probe of (\S+) failed with error (-\d+)|(\S+): probe with driver \S+ failed with error (-\d+)")

#: (id, label, bus, product). product follows D-169/D-190: bench-only devices are false.
DEVICES = (
    ("motor.1", "구동 모터 1 (XL330)", "UART4 /dev/rosy-motor", True),
    ("motor.2", "구동 모터 2 (XL330)", "UART4 /dev/rosy-motor", True),
    ("lidar", "LiDAR (RPLIDAR C1)", "UART0 /dev/ttyAMA0", True),
    ("imu", "IMU (BNO055)", "I2C0 /dev/i2c-0 0x28", False),
    ("adc.battery", "배터리 전압 (ADC)", "I2C1 /dev/i2c-1 0x08", True),
    ("adc.ir0", "IR 센서 0 (ADC)", "I2C1 /dev/i2c-1 0x08", True),
    ("adc.ir1", "IR 센서 1 (ADC)", "I2C1 /dev/i2c-1 0x08", True),
    ("adc.ir2", "IR 센서 2 (ADC)", "I2C1 /dev/i2c-1 0x08", True),
    ("adc.ultrasonic", "초음파 거리 (ADC)", "I2C1 /dev/i2c-1 0x08", True),
    ("camera", "카메라 (OV5647)", "CSI", True),
    ("lcd", "LCD (ST7789)", "SPI0 /dev/spidev0.0", True),
    ("buzzer", "부저", "GPIO BCM 22", True),
    ("lamp", "LED 램프 (WS2812)", "GPIO BCM 19 PWM", False),
    ("pi.power", "Pi 전원·온도", "vcgencmd", True),
)
DEVICE_IDS = tuple(device[0] for device in DEVICES)


class BusTimeout(Exception):
    """The bus did not answer in time; the rest of that bus is not measured."""


def _errno_text(error: OSError) -> str:
    code = error.errno or 0
    name = errno_codes.errorcode.get(code, "errno")
    return f"{name} (-{code})"


class SystemIo:
    """Every device and command access. Tests subclass it; paths are under `root`."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def path(self, relative: str) -> Path:
        return self.root / relative

    def exists(self, relative: str) -> bool:
        return os.path.exists(self.path(relative))

    def run(self, command: list[str]) -> tuple[int, str] | None:
        """(returncode, stdout), or None when the command is missing or hangs."""
        try:
            done = subprocess.run(command, capture_output=True, text=True, timeout=COMMAND_TIMEOUT_S,
                                  check=False)
        except (OSError, subprocess.SubprocessError):
            return None
        return done.returncode, done.stdout

    def unit_active(self, unit: str) -> bool:
        result = self.run(["systemctl", "is-active", "--quiet", unit])
        return result is not None and result[0] == 0

    def i2c_read(self, bus: str, address: int, register: int, length: int, delay_s: float = 0.0) -> bytes:
        """One register read under the bus flock (D-192). OSError(ETIMEDOUT) on a wedged bus."""
        import fcntl

        descriptor = os.open(self.path(bus), os.O_RDWR | getattr(os, "O_CLOEXEC", 0))
        try:
            deadline = time.monotonic() + LOCK_WAIT_S
            while True:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise OSError(errno_codes.EWOULDBLOCK, "bus lock held") from None
                    time.sleep(0.02)
            fcntl.ioctl(descriptor, 0x0703, address)  # I2C_SLAVE; never I2C_SLAVE_FORCE
            os.write(descriptor, bytes([register]))
            if delay_s:
                time.sleep(delay_s)
            return os.read(descriptor, length)
        finally:
            os.close(descriptor)  # also drops the flock

    def lidar_health(self, device: str) -> bytes:
        """RPLIDAR GET_HEALTH (A5 52): no motor start, no scan. The raw reply."""
        import select
        import termios

        descriptor = os.open(self.path(device), os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK
                             | getattr(os, "O_CLOEXEC", 0))
        try:
            attrs = termios.tcgetattr(descriptor)
            speed = getattr(termios, f"B{LIDAR_BAUD}")
            attrs[0] = 0
            attrs[1] = 0
            attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
            attrs[3] = 0
            attrs[4] = attrs[5] = speed
            termios.tcsetattr(descriptor, termios.TCSANOW, attrs)
            termios.tcflush(descriptor, termios.TCIOFLUSH)
            os.write(descriptor, b"\xa5\x52")
            reply = b""
            deadline = time.monotonic() + 1.0
            while len(reply) < 10 and time.monotonic() < deadline:
                ready, _, _ = select.select([descriptor], [], [], max(0.0, deadline - time.monotonic()))
                if ready:
                    reply += os.read(descriptor, 10 - len(reply))
            return reply
        finally:
            os.close(descriptor)

    def dxl_ping(self, device: str, ids: tuple[int, ...]) -> dict[int, tuple[bool, str]]:
        """Protocol 2.0 ping per id: (answered, evidence). ImportError when the SDK is absent."""
        from dynamixel_sdk import COMM_SUCCESS, PacketHandler, PortHandler

        port = PortHandler(str(self.path(device)))
        packet = PacketHandler(2.0)
        if not port.openPort():
            raise OSError(errno_codes.EIO, "open failed")
        try:
            if not port.setBaudRate(MOTOR_BAUD):
                raise OSError(errno_codes.EIO, "baud rate refused")
            result = {}
            for motor_id in ids:
                model, comm, error = packet.ping(port, motor_id)
                if comm == COMM_SUCCESS and error == 0:
                    result[motor_id] = (True, f"ping 응답 · 모델 {model} · ID {motor_id} · 1 Mbps")
                else:
                    result[motor_id] = (False, f"ping 무응답 · ID {motor_id} · {packet.getTxRxResult(comm)}")
            return result
        finally:
            port.closePort()

    def kernel_log(self) -> list[str] | None:
        """This boot's kernel messages from /dev/kmsg, read non-blocking; None when unreadable."""
        flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
        try:
            descriptor = os.open(self.path(KMSG), flags)
        except OSError:
            return None
        lines: list[str] = []
        try:
            while len(lines) < 20000:
                try:
                    chunk = os.read(descriptor, 8192)
                except BlockingIOError:
                    break  # end of the ring buffer
                except OSError as error:
                    if error.errno == errno_codes.EPIPE:  # a record was overwritten; keep reading
                        continue
                    break
                if not chunk:
                    break  # a regular file (host tests)
                for record in chunk.decode("utf-8", "replace").splitlines():
                    lines.append(record.split(";", 1)[1] if ";" in record else record)
        finally:
            os.close(descriptor)
        return lines


@dataclass
class Row:
    id: str
    state: str
    evidence: str
    held_by: Optional[str] = None


def _adc_value(channel: str, raw: int) -> tuple[str, str]:
    if channel == "adc.battery":
        volts = raw / 4096 * 4.096 / (13 / 28)
        low, high = BATTERY_RANGE_V
        if low <= volts <= high:
            return OK, f"{volts:.2f} V (raw {raw})"
        return NEEDS_HUMAN, f"{volts:.2f} V (raw {raw}) — 기대 범위 {low:.1f}–{high:.1f} V 밖"
    # IR and ultrasonic read full scale with nothing in front or below (2026-09-25
    # hand test: IR 1918-4095, ultrasonic 56-4095). Any reading is an answer.
    if raw == ADC_FULL_SCALE:
        return OK, f"{raw} (감지 없음)"
    return OK, f"raw {raw}"


class Probe:
    def __init__(self, io: SystemIo) -> None:
        self.io = io

    # --- buses the I/O runtime owns --------------------------------------

    def io_owner(self) -> Optional[str]:
        for unit in IO_UNITS:
            if self.io.unit_active(unit):
                return unit
        return None

    def motors(self, owner: Optional[str]) -> list[Row]:
        ids = [f"motor.{motor_id}" for motor_id in MOTOR_IDS]
        if owner:
            return [Row(i, NOT_MEASURED, f"{owner.removesuffix('.service')} 사용 중 — 토픽으로 판정", owner)
                    for i in ids]
        if not self.io.exists(MOTOR_DEV):
            return [Row(i, BUS_MISSING, "/dev/rosy-motor 없음 (uart4-pi5 오버레이·udev 규칙)") for i in ids]
        try:
            replies = self.io.dxl_ping(MOTOR_DEV, MOTOR_IDS)
        except ImportError:
            return [Row(i, NOT_MEASURED, "dynamixel_sdk 없음 — ping 못 함") for i in ids]
        except OSError as error:
            return [Row(i, NO_RESPONSE, f"UART 열기 실패 {_errno_text(error)}") for i in ids]
        rows = []
        for motor_id, row_id in zip(MOTOR_IDS, ids):
            answered, evidence = replies.get(motor_id, (False, "ping 결과 없음"))
            rows.append(Row(row_id, OK if answered else NO_RESPONSE, evidence))
        return rows

    def lidar(self, owner: Optional[str]) -> Row:
        if owner:
            return Row("lidar", NOT_MEASURED, f"{owner.removesuffix('.service')} 사용 중 — 토픽으로 판정", owner)
        if not self.io.exists(LIDAR_DEV):
            return Row("lidar", BUS_MISSING, "/dev/ttyAMA0 없음")
        try:
            reply = self.io.lidar_health(LIDAR_DEV)
        except OSError as error:
            return Row("lidar", NO_RESPONSE, f"UART 열기 실패 {_errno_text(error)}")
        if len(reply) >= 10 and reply[:2] == b"\xa5\x5a":
            status = reply[7]
            if status == 0:
                return Row("lidar", OK, "GET_HEALTH 정상 (460800 bps)")
            return Row("lidar", NO_RESPONSE, f"GET_HEALTH 상태 {status} (1 경고 · 2 오류), 코드 {reply[8] | reply[9] << 8}")
        return Row("lidar", NO_RESPONSE, f"GET_HEALTH 무응답 ({len(reply)} 바이트)")

    # --- I2C ------------------------------------------------------------------

    def _i2c(self, bus: str, address: int, register: int, length: int, delay_s: float = 0.0) -> bytes:
        try:
            data = self.io.i2c_read(bus, address, register, length, delay_s)
        except OSError as error:
            if error.errno == errno_codes.ETIMEDOUT:
                raise BusTimeout(_errno_text(error)) from error
            raise
        if len(data) != length:
            raise OSError(errno_codes.EIO, "short read")
        return data

    def imu(self) -> Row:
        if not self.io.exists(IMU_BUS):
            return Row("imu", BUS_MISSING, "/dev/i2c-0 없음 (config.txt dtoverlay=i2c0-pi5,pins_0_1)")
        try:
            chip = self._i2c(IMU_BUS, IMU_ADDRESS, 0x00, 1)[0]
            if chip != IMU_CHIP_ID:
                return Row("imu", NO_RESPONSE, f"칩 ID 0x{chip:02X} (기대 0x{IMU_CHIP_ID:02X})")
            status = self._i2c(IMU_BUS, IMU_ADDRESS, 0x39, 1)[0]
            error = self._i2c(IMU_BUS, IMU_ADDRESS, 0x3A, 1)[0]
        except BusTimeout as timeout:
            return Row("imu", NO_RESPONSE, f"{timeout} — 버스 멈춤")
        except OSError as failure:
            return Row("imu", NO_RESPONSE, _errno_text(failure))
        # Judged by chip id and SYS_ERR only: after power-on the chip sits in
        # CONFIG mode with zero acceleration, which is normal, and the probe
        # never changes the mode to look further (D-247 5).
        if error:
            return Row("imu", NEEDS_HUMAN, f"칩 ID 0xA0 · 상태 {status} · 시스템 오류 {error}")
        return Row("imu", OK, f"칩 ID 0xA0 · 상태 {status} · 오류 {error}")

    def adc(self, owner: Optional[str]) -> list[Row]:
        ids = [channel for channel, _register in ADC_CHANNELS]
        if owner:
            return [Row(i, NOT_MEASURED, f"{owner.removesuffix('.service')} 사용 중 — 토픽으로 판정", owner)
                    for i in ids]
        if not self.io.exists(ADC_BUS):
            return [Row(i, BUS_MISSING, "/dev/i2c-1 없음 (dtparam=i2c_arm=on)") for i in ids]
        rows: list[Row] = []
        for index, (channel, register) in enumerate(ADC_CHANNELS):
            try:
                d0, d1 = self._i2c(ADC_BUS, ADC_ADDRESS, register, 2, ADC_DELAY_S)
            except BusTimeout as timeout:
                rows.append(Row(channel, NO_RESPONSE,
                                f"{timeout} — ADC MCU 멈춤. Pi 재부팅으로는 풀리지 않습니다. 로봇 전원을 완전히 껐다 켜세요"))
                rows += [Row(rest, NOT_MEASURED, "같은 버스가 시간 초과 — 측정 안 함")
                         for rest, _register in ADC_CHANNELS[index + 1:]]
                break
            except OSError as failure:
                if failure.errno == errno_codes.EWOULDBLOCK:
                    rows.append(Row(channel, NOT_MEASURED, "D-192 버스 잠금 대기 시간 초과"))
                else:
                    rows.append(Row(channel, NO_RESPONSE, _errno_text(failure)))
                continue
            state, evidence = _adc_value(channel, (d0 << 4) + (d1 >> 4))
            rows.append(Row(channel, state, evidence))
        return rows

    # --- the rest -------------------------------------------------------------

    def camera(self) -> Row:
        statuses = []
        for node in sorted(self.io.root.glob(CSI_GLOB)):
            try:
                statuses.append(node.read_bytes().rstrip(b"\0").decode("ascii", "replace").strip())
            except OSError:
                continue
        csi_on = "okay" in statuses
        log = self.io.kernel_log()
        if log is None:
            return Row("camera", NOT_MEASURED, "커널 로그(/dev/kmsg)를 읽지 못함")
        failure = None
        seen = None
        for line in log:
            sensor = CAMERA_SENSORS.search(line)
            if not sensor:
                continue
            seen = sensor.group(1)
            failed = PROBE_FAILED.search(line)
            if failed:
                failure = (seen, failed.group(1) or failed.group(3), failed.group(2) or failed.group(4))
        csi = "CSI 활성" if csi_on else "CSI 비활성"
        if failure:
            sensor, address, code = failure
            return Row("camera", NO_RESPONSE, f"{sensor} {address} probe {code} · {csi}")
        if seen and csi_on:
            return Row("camera", OK, f"{seen} 커널 probe 성공 · {csi}")
        return Row("camera", NO_RESPONSE, f"{csi} · 센서 미검출")

    def lcd(self) -> Row:
        if not self.io.exists(LCD_SPI):
            return Row("lcd", BUS_MISSING, "/dev/spidev0.0 없음 (dtparam=spi=on)")
        if self.io.unit_active(DISPLAY_UNIT):
            return Row("lcd", OK, "rosy-boot-display 실행 중 · 화면 내용은 사람이 봐야 함")
        return Row("lcd", NEEDS_HUMAN, "rosy-boot-display 멈춤 · 화면을 사람이 확인")

    def buzzer(self) -> Row:
        enabled, pin = False, BUZZER_DEFAULT_PIN
        try:
            text = self.io.path(DISPLAY_ENV).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            text = ""
        for line in text.splitlines():
            key, _, value = line.strip().partition("=")
            if key == "ROSY_BUZZER_ENABLED":
                enabled = value.strip().lower() == "true"
            elif key == "ROSY_BUZZER_PIN" and value.strip().isdigit():
                pin = int(value.strip())
        switch = "켜짐" if enabled else "꺼짐 (ROSY_BUZZER_ENABLED=false)"
        return Row("buzzer", NEEDS_HUMAN, f"BCM {pin} 미확인 · {switch} · 소리는 사람이 확인")

    def lamp(self) -> Row:
        if not self.io.exists(LAMP_NODE):
            return Row("lamp", DRIVER_MISSING, "/dev/ws281x_pwm 없음 (rp1_ws281x_pwm 커널 모듈)")
        return Row("lamp", NEEDS_HUMAN, "드라이버 있음 · 빛은 사람이 확인")

    def pi_power(self) -> Row:
        throttled = self.io.run(["vcgencmd", "get_throttled"])
        if throttled is None:
            return Row("pi.power", DRIVER_MISSING, "vcgencmd 없음")
        if throttled[0] != 0:
            return Row("pi.power", NOT_MEASURED, f"vcgencmd 실패 (종료 {throttled[0]})")
        parts = []
        match = re.search(r"0x([0-9a-fA-F]+)", throttled[1])
        flags = int(match.group(1), 16) if match else None
        parts.append(f"throttled=0x{flags:x}" if flags is not None else "throttled=?")
        temp = self.io.run(["vcgencmd", "measure_temp"])
        if temp and temp[0] == 0 and (found := re.search(r"([\d.]+)'C", temp[1])):
            parts.append(f"{float(found.group(1)):.1f} °C")
        volts = self.io.run(["vcgencmd", "pmic_read_adc", "EXT5V_V"])
        if volts and volts[0] == 0 and (found := re.search(r"=([\d.]+)V", volts[1])):
            parts.append(f"EXT5V {float(found.group(1)):.2f} V")
        evidence = " · ".join(parts)
        if flags is None:
            return Row("pi.power", NOT_MEASURED, evidence)
        if flags & 0x1:
            return Row("pi.power", NEEDS_HUMAN, f"{evidence} — 지금 저전압")
        if flags:
            return Row("pi.power", NEEDS_HUMAN, f"{evidence} — 부팅 뒤 저전압·스로틀 이력")
        return Row("pi.power", OK, evidence)

    def run(self) -> list[Row]:
        owner = self.io_owner()
        rows = self.motors(owner) + [self.lidar(owner), self.imu()] + self.adc(owner)
        rows += [self.camera(), self.lcd(), self.buzzer(), self.lamp(), self.pi_power()]
        return rows


def _boot_id(root: Path) -> Optional[str]:
    try:
        return (root / BOOT_ID).read_text(encoding="ascii").strip() or None
    except OSError:
        return None


def document(rows: list[Row], root: Path, now: Optional[datetime] = None) -> dict:
    by_id = {row.id: row for row in rows}
    devices = []
    for device_id, label, bus, product in DEVICES:
        row = by_id[device_id]
        entry = {"id": device_id, "label": label, "bus": bus, "state": row.state,
                 "evidence": row.evidence, "product": product}
        if row.held_by:
            entry["held_by"] = row.held_by
        devices.append(entry)
    measured = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    return {"schema": SCHEMA, "measured_at": measured, "boot_id": _boot_id(root), "devices": devices}


def group_id(name: str) -> int | None:
    try:
        import grp
        return grp.getgrnam(name).gr_gid
    except (ImportError, KeyError):
        return None


def write_atomic(path: Path, content: str, mode: int, group: int | None) -> None:
    """rosy-login-code's _write (D-190 pattern): group and mode on the empty temp file, then rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            if group is not None and hasattr(os, "fchown"):
                os.fchown(handle.fileno(), -1, group)
            if hasattr(os, "fchmod"):
                os.fchmod(handle.fileno(), mode)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None, *, io: SystemIo | None = None,
         group: Callable[[str], int | None] = group_id) -> int:
    parser = argparse.ArgumentParser(
        prog="rosy-hw-probe",
        description="Read-only board device observation (D-247); writes /run/rosy-boot/hardware.json.")
    parser.add_argument("--root", type=Path, default=Path("/"), help=argparse.SUPPRESS)
    parser.add_argument("--stdout", action="store_true", help="print the result instead of writing it")
    args = parser.parse_args(argv)
    if args.root == Path("/") and not args.stdout and hasattr(os, "geteuid") and os.geteuid() != 0:
        print("rosy-hw-probe: run as root", file=sys.stderr)
        return 1
    probe = Probe(io or SystemIo(args.root))
    started = time.monotonic()
    result = document(probe.run(), args.root)
    text = json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n"
    if args.stdout:
        print(text, end="")
        return 0
    write_atomic(args.root / OUTPUT, text, 0o640, group(CORE_GROUP))
    counts: dict[str, int] = {}
    for device in result["devices"]:
        counts[device["state"]] = counts.get(device["state"], 0) + 1
    # States only, one line for the journal; the evidence lives in the file.
    print(json.dumps({"hw_probe": counts, "seconds": round(time.monotonic() - started, 2)}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
