"""Device I/O seams, constants, and document serialization for rosy-hw-probe (D-247)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import errno as errno_codes
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from typing import Optional

sys.dont_write_bytecode = True

SCHEMA = 1
STATUS_DIR = "run/rosy-boot"
OUTPUT = f"{STATUS_DIR}/hardware.json"
BOOT_ID = "proc/sys/kernel/random/boot_id"
DISPLAY_ENV = "etc/rosy/boot-display.env"
KMSG = "dev/kmsg"
CSI_GLOB = "proc/device-tree/axi/pcie@*/rp1/csi@*/status"
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
#: ActiveState values that prove a unit holds nothing. Anything else (active,
#: activating, deactivating, reloading, unknown) leaves its buses alone.
FREE_STATES = ("inactive", "failed")
#: How /proc/<pid>/fd shows the two UARTs (the motor alias resolves to ttyAMA4).
MOTOR_NODES = ("/dev/rosy-motor", "/dev/ttyAMA4")
LIDAR_NODES = ("/dev/ttyAMA0",)
DISPLAY_UNIT = "rosy-face.service"  # D-433 (was rosy-boot-display.service)

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
#: The driver's PWM0 channel: 3 is GPIO19, the lamp; its default 2 is GPIO18, the
#: LCD backlight (rosy_18 2026-09-26). /etc/modprobe.d/rosy-ws281x.conf sets 3.
LAMP_CHANNEL = "sys/module/rp1_ws281x_pwm/parameters/pwm_channel"
LAMP_PWM_CHANNEL = 3
#: The Pinky Pro buzzer (board.yaml), heard on rosy_18 2026-09-26; ROSY_BUZZER_PIN wins.
BUZZER_DEFAULT_PIN = 4
LOCK_WAIT_S = 2.0
#: A result this fresh is kept: a burst of refresh requests runs the buses once.
MIN_INTERVAL_S = 10.0
COMMAND_TIMEOUT_S = 3.0
CAMERA_SENSORS = re.compile(r"\b(ov5647|imx219|imx708)\b")
PROBE_FAILED = re.compile(r"failed with error (-\d+)")
#: The sensor's I2C client, e.g. 10-0036 (bus 10, address 0x36): one per camera port.
I2C_CLIENT = re.compile(r"\b(\d+-00[0-9a-fA-F]{2})\b")

#: (id, label, bus, product). product follows D-169 (Accepted): only the motors, the
#: LiDAR, the camera and the ADC are product devices; everything else is bench/host.
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
    ("lcd", "LCD (ST7789)", "SPI0 /dev/spidev0.0", False),
    ("buzzer", "부저", "GPIO (ROSY_BUZZER_PIN, 기본 BCM 4)", False),
    ("lamp", "LED 램프 (WS2812)", "GPIO BCM 19 PWM", False),
    ("pi.power", "Pi 전원·온도", "vcgencmd", False),
)
DEVICE_IDS = tuple(device[0] for device in DEVICES)


class BusTimeout(Exception):
    """The bus did not answer in time; the rest of that bus is not measured."""


class LockHeld(Exception):
    """Another reader held the D-192 bus flock past LOCK_WAIT_S; the bus is left alone."""


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

    def unit_state(self, unit: str) -> Optional[str]:
        """systemd's ActiveState (as rosy-boot-status.py reads it), or None when unknown."""
        result = self.run(["systemctl", "show", "--property=ActiveState", "--value", unit])
        if result is None or result[0] != 0:
            return None
        return result[1].strip() or None

    def device_holders(self, devices: tuple[str, ...]) -> Optional[set[int]]:
        """Pids (other than this one) with one of `devices` open; None when /proc cannot be read.

        `devices` are absolute paths as /proc/<pid>/fd links show them. The
        unit's CAP_SYS_PTRACE lets root read other users' fd tables.
        """
        wanted = set(devices)
        holders: set[int] = set()
        proc = self.path("proc")
        try:
            entries = [entry for entry in os.listdir(proc) if entry.isdigit()]
        except OSError:
            return None
        for entry in entries:
            if int(entry) == os.getpid():
                continue
            fd_dir = proc / entry / "fd"
            try:
                names = os.listdir(fd_dir)
            except FileNotFoundError:
                continue  # the process exited
            except OSError:
                return None  # cannot see its fds: not provably free
            for name in names:
                try:
                    target = os.readlink(fd_dir / name)
                except OSError:
                    continue
                if target in wanted:
                    holders.add(int(entry))
                    break
        return holders

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
                        raise LockHeld(bus) from None
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
