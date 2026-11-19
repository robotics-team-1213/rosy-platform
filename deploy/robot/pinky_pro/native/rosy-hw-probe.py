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
import errno as errno_codes
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Callable, Optional

sys.dont_write_bytecode = True
# The shared switch parser (rosy_display_env.py) and helpers sit beside this program.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import rosy_display_env  # noqa: E402
from rosy_hw_probe_helpers import (  # noqa: E402, F401
    ADC_ADDRESS,
    ADC_BUS,
    ADC_CHANNELS,
    ADC_DELAY_S,
    ADC_FULL_SCALE,
    BATTERY_RANGE_V,
    BOOT_ID,
    BUS_MISSING,
    BUZZER_DEFAULT_PIN,
    CAMERA_SENSORS,
    COMMAND_TIMEOUT_S,
    CORE_GROUP,
    CSI_GLOB,
    DEVICES,
    DEVICE_IDS,
    DISPLAY_ENV,
    DISPLAY_UNIT,
    DRIVER_MISSING,
    FREE_STATES,
    I2C_CLIENT,
    IMU_ADDRESS,
    IMU_BUS,
    IMU_CHIP_ID,
    IO_UNITS,
    KMSG,
    LAMP_CHANNEL,
    LAMP_NODE,
    LAMP_PWM_CHANNEL,
    LCD_SPI,
    LIDAR_BAUD,
    LIDAR_DEV,
    LIDAR_NODES,
    LOCK_WAIT_S,
    MIN_INTERVAL_S,
    MOTOR_BAUD,
    MOTOR_DEV,
    MOTOR_IDS,
    MOTOR_NODES,
    NEEDS_HUMAN,
    NOT_MEASURED,
    NO_RESPONSE,
    OK,
    OUTPUT,
    PROBE_FAILED,
    SCHEMA,
    STATES,
    STATUS_DIR,
    BusTimeout,
    LockHeld,
    Row,
    SystemIo,
    _adc_value,
    _boot_id,
    _errno_text,
    document,
    group_id,
    write_atomic,
)


class Probe:
    def __init__(self, io: SystemIo) -> None:
        self.io = io

    # --- buses the I/O runtime owns --------------------------------------

    def held(self, nodes: tuple[str, ...] = ()) -> Optional[tuple[str, Optional[str]]]:
        """(evidence, held_by) when the bus may be in use, None when it is provably free.

        Asked again right before each bus is opened, so a runtime that started
        since the last bus is still seen. Fail closed: an unknown unit state or
        an unreadable fd table counts as held.
        """
        for unit in IO_UNITS:
            state = self.io.unit_state(unit)
            name = unit.removesuffix(".service")
            if state is None:
                return f"{name} 상태 확인 불가 — 측정 안 함", None
            if state == "active":
                return f"{name} 사용 중 — 토픽으로 판정", unit
            if state not in FREE_STATES:
                return f"{name} {state} — 측정 안 함", unit
        if nodes:
            holders = self.io.device_holders(nodes)
            if holders is None:
                return "장치 사용 여부 확인 불가 — 측정 안 함", None
            if holders:
                pids = ", ".join(str(pid) for pid in sorted(holders))
                return f"다른 프로세스(pid {pids})가 사용 중 — 측정 안 함", None
        return None

    def motors(self) -> list[Row]:
        ids = [f"motor.{motor_id}" for motor_id in MOTOR_IDS]
        holder = self.held(MOTOR_NODES)
        if holder:
            return [Row(i, NOT_MEASURED, holder[0], holder[1]) for i in ids]
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

    def lidar(self) -> Row:
        holder = self.held(LIDAR_NODES)
        if holder:
            return Row("lidar", NOT_MEASURED, holder[0], holder[1])
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
        except LockHeld:
            return Row("imu", NOT_MEASURED, "버스 잠금 대기 시간 초과 — 측정 안 함")
        except OSError as failure:
            return Row("imu", NO_RESPONSE, _errno_text(failure))
        # Judged by chip id and SYS_ERR only: after power-on the chip sits in
        # CONFIG mode with zero acceleration, which is normal, and the probe
        # never changes the mode to look further (D-247 5).
        if error:
            return Row("imu", NEEDS_HUMAN, f"칩 ID 0xA0 · 상태 {status} · 시스템 오류 {error}")
        return Row("imu", OK, f"칩 ID 0xA0 · 상태 {status} · 오류 {error}")

    def adc(self) -> list[Row]:
        ids = [channel for channel, _register in ADC_CHANNELS]
        # /dev/i2c-1 is shared with the boot display by design; the D-192 flock orders them.
        holder = self.held()
        if holder:
            return [Row(i, NOT_MEASURED, holder[0], holder[1]) for i in ids]
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
            except LockHeld:
                rows += [Row(rest, NOT_MEASURED, "D-192 버스 잠금 대기 시간 초과 — 측정 안 함")
                         for rest, _register in ADC_CHANNELS[index:]]
                break
            except OSError as failure:
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
        # Per camera port (I2C client): the last word the kernel said about it.
        # The Pi 5 has two ports; an empty one answering -121 is not a fault
        # when the other registered a sensor.
        ports: dict[str, tuple[str, Optional[str]]] = {}
        for line in log:
            sensor = CAMERA_SENSORS.search(line)
            client = I2C_CLIENT.search(line)
            if not sensor or not client:
                continue
            failed = PROBE_FAILED.search(line)
            ports[client.group(1)] = (sensor.group(1), failed.group(1) if failed else None)
        csi = "CSI 활성" if csi_on else "CSI 비활성"
        good = sorted(f"{name} {port}" for port, (name, code) in ports.items() if code is None)
        bad = sorted(f"{name} {port} probe {code}" for port, (name, code) in ports.items() if code)
        if good and csi_on:
            note = f" · 빈 포트 {', '.join(bad)}" if bad else ""
            return Row("camera", OK, f"{', '.join(good)} 커널 probe 성공 · {csi}{note}")
        if bad:
            return Row("camera", NO_RESPONSE, f"{', '.join(bad)} · {csi}")
        return Row("camera", NO_RESPONSE, f"{csi} · 센서 미검출")

    def lcd(self) -> Row:
        if not self.io.exists(LCD_SPI):
            return Row("lcd", BUS_MISSING, "/dev/spidev0.0 없음 (dtparam=spi=on)")
        if self.io.unit_state(DISPLAY_UNIT) == "active":
            return Row("lcd", OK, "rosy-face 실행 중 · 화면 내용은 사람이 봐야 함")
        return Row("lcd", NEEDS_HUMAN, "rosy-face 멈춤 · 화면을 사람이 확인")

    def buzzer(self) -> Row:
        # D-260 2: the boot display's switch, read as the display reads it (rosy_display_env).
        try:
            text = self.io.path(DISPLAY_ENV).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            text = ""
        values = rosy_display_env.parse_env(text)
        enabled, _valid = rosy_display_env.flag(values, rosy_display_env.BUZZER_KEY)
        pin_text = values.get("ROSY_BUZZER_PIN", "")
        pin = int(pin_text) if pin_text.isdigit() else BUZZER_DEFAULT_PIN
        switch = "켜짐" if enabled else "꺼짐 (ROSY_BUZZER_ENABLED=false)"
        return Row("buzzer", NEEDS_HUMAN, f"BCM {pin} · {switch} · 소리는 사람이 확인")

    def lamp(self) -> Row:
        if not self.io.exists(LAMP_NODE):
            return Row("lamp", DRIVER_MISSING, "/dev/ws281x_pwm 없음 (rp1_ws281x_pwm 커널 모듈)")
        try:
            channel = self.io.path(LAMP_CHANNEL).read_text(encoding="ascii").strip()
        except (OSError, UnicodeDecodeError):
            channel = ""
        if channel != str(LAMP_PWM_CHANNEL):
            # Channel 2 drives GPIO18 (the LCD backlight): the lamp stays dark and a
            # lamp test would flicker the screen, so this is not a light for a person.
            shown = channel or "?"
            return Row("lamp", DRIVER_MISSING,
                       f"rp1_ws281x_pwm pwm_channel={shown} — GPIO19 램프는 3 (/etc/modprobe.d/rosy-ws281x.conf)")
        return Row("lamp", NEEDS_HUMAN, "드라이버 있음 · pwm_channel=3 (GPIO19) · 빛은 사람이 확인")

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
        rows = self.motors() + [self.lidar(), self.imu()] + self.adc()
        rows += [self.camera(), self.lcd(), self.buzzer(), self.lamp(), self.pi_power()]
        return rows


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
    if not args.stdout:
        try:
            age = time.time() - (args.root / OUTPUT).stat().st_mtime
        except OSError:
            age = None
        if age is not None and 0 <= age < MIN_INTERVAL_S:
            print(json.dumps({"hw_probe": "skipped", "result_age_s": round(age, 1)}), flush=True)
            return 0
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
