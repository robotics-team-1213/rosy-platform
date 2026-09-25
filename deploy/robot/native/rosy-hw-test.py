#!/usr/bin/env python3
"""Beep the buzzer or flash the lamp once, as root, on an administrator's request (D-247 6).

The buzzer and the WS2812 lamp are devices a machine cannot judge: a person
has to hear or see them. CORE never opens a device (D-161); an administrator
presses the test on the dashboard, CORE writes /run/rosy/hw-test.request, and
rosy-hw-test.path starts this program, which does exactly one of:

* buzzer: three 150 ms beeps, 2 kHz, 10 % duty, on the BCM line
  /etc/rosy/boot-display.env names (ROSY_BUZZER_PIN, default 4, the lines
  rosy-boot-display.py allows). Never while rosy-boot-display owns that line
  (ROSY_BUZZER_ENABLED=true): the boot display beeps at CORE_READY instead.
* lamp: lamp_selftest (built with lamp_control against the pinned rpi_ws281x)
  shows dim red, green and blue for a second each, then turns the lamp off.
  Only when the rp1_ws281x_pwm driver runs on PWM0 channel 3 (GPIO19); its
  default channel 2 is GPIO18, the LCD backlight.

The outcome goes to /run/rosy-boot/hw-test.json, root:rosy-core 0640, which
CORE reads. The person's answer (heard / seen) is recorded by CORE, not here.
No motor, no cmd_vel, no ADC: this program opens only the GPIO chip (through
RPi.GPIO / rpi-lgpio) and, through lamp_selftest, /dev/ws281x_pwm.

The request is read strictly: a regular file, no symlink, at most 1 KiB, a
JSON object with exactly the keys CORE writes, a known action and a hex
request id, written in the last REQUEST_MAX_AGE_S. Anything else is ignored.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time
from typing import Callable, Optional

sys.dont_write_bytecode = True

SCHEMA = 1
REQUEST = "run/rosy/hw-test.request"
RESULT = "run/rosy-boot/hw-test.json"
DISPLAY_ENV = "etc/rosy/boot-display.env"
LAMP_NODE = "dev/ws281x_pwm"
LAMP_CHANNEL = "sys/module/rp1_ws281x_pwm/parameters/pwm_channel"
LAMP_PWM_CHANNEL = "3"
LAMP_HELPER = "opt/rosy/current/install/lib/lamp_control/lamp_selftest"
LAMP_TIMEOUT_S = 10.0
DISPLAY_UNIT = "rosy-boot-display.service"
CORE_GROUP = "rosy-core"
ACTIONS = ("buzzer", "lamp")
REQUEST_KEYS = {"action", "request_id", "requested_at", "by"}
MAX_REQUEST_BYTES = 1024
MAX_BY = 128
REQUEST_ID = re.compile(r"[0-9a-f]{16,64}")
#: A request older than this (a path unit started late, a leftover file) starts nothing.
REQUEST_MAX_AGE_S = 60.0
#: rosy-boot-display.py BUZZER_LINES / BUZZER_DEFAULT_LINE (board.yaml boot_display.buzzer).
BUZZER_LINES = frozenset({4, 5, 6, 16, 17, 20, 21, 22, 23, 24, 26})
BUZZER_DEFAULT_LINE = 4
BUZZER_FREQUENCY_HZ = 2000
BUZZER_DUTY = 10
BUZZER_BEEPS = 3
BUZZER_ON_S = 0.15
BUZZER_OFF_S = 0.15
COMMAND_TIMEOUT_S = 3.0

DONE = "done"            # the device was driven; a person now says whether it was heard / seen
BUSY = "busy"            # another owner has the device; nothing was driven
UNAVAILABLE = "unavailable"  # the driver or configuration is missing; nothing was driven
FAILED = "failed"        # driving it failed part-way


def read_request(path: Path, now: Optional[float] = None) -> Optional[dict]:
    """CORE's request, validated, or None. Never follows a link, never blocks on a FIFO."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) \
        | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_REQUEST_BYTES:
            return None
        raw = os.read(descriptor, MAX_REQUEST_BYTES + 1)
    finally:
        os.close(descriptor)
    if len(raw) > MAX_REQUEST_BYTES:
        return None
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(data, dict) or set(data) != REQUEST_KEYS:
        return None
    if data["action"] not in ACTIONS or not isinstance(data["request_id"], str) \
            or not REQUEST_ID.fullmatch(data["request_id"]):
        return None
    if not isinstance(data["by"], str) or len(data["by"]) > MAX_BY:
        return None
    try:
        requested = datetime.fromisoformat(str(data["requested_at"]))
    except ValueError:
        return None
    if requested.tzinfo is None:
        return None
    age = (now if now is not None else time.time()) - requested.timestamp()
    if not -5.0 <= age <= REQUEST_MAX_AGE_S:
        return None
    return data


def buzzer_settings(text: str) -> tuple[bool, Optional[int]]:
    """(ROSY_BUZZER_ENABLED, pin) from boot-display.env; pin None when it is not an allowed line."""
    enabled, pin_text = False, str(BUZZER_DEFAULT_LINE)
    for line in text.splitlines():
        key, _, value = line.strip().partition("=")
        if key == "ROSY_BUZZER_ENABLED":
            enabled = value.strip() == "true"
        elif key == "ROSY_BUZZER_PIN":
            pin_text = value.strip()
    if not pin_text.isdigit() or int(pin_text) not in BUZZER_LINES:
        return enabled, None
    return enabled, int(pin_text)


class System:
    """Everything that touches the machine. Tests replace it; paths are under `root`."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def path(self, relative: str) -> Path:
        return self.root / relative

    def unit_state(self, unit: str) -> Optional[str]:
        try:
            done = subprocess.run(["systemctl", "show", "--property=ActiveState", "--value", unit],
                                  capture_output=True, text=True, timeout=COMMAND_TIMEOUT_S, check=False)
        except (OSError, subprocess.SubprocessError):
            return None
        return (done.stdout.strip() or None) if done.returncode == 0 else None

    def beep(self, pin: int) -> None:
        """BUZZER_BEEPS short tones on `pin` through RPi.GPIO (rpi-lgpio, RPI_LGPIO_CHIP=4)."""
        import RPi.GPIO as gpio  # noqa: N813 - vendor name

        gpio.setwarnings(False)
        gpio.setmode(gpio.BCM)
        gpio.setup(pin, gpio.OUT, initial=gpio.LOW)
        try:
            pwm = gpio.PWM(pin, BUZZER_FREQUENCY_HZ)
            for index in range(BUZZER_BEEPS):
                pwm.start(BUZZER_DUTY)
                time.sleep(BUZZER_ON_S)
                pwm.stop()
                if index + 1 < BUZZER_BEEPS:
                    time.sleep(BUZZER_OFF_S)
        finally:
            gpio.cleanup(pin)

    def helper_trusted(self, helper: Path) -> bool:
        """Root runs lamp_selftest: only a regular file root owns and no group or other can write."""
        try:
            info = os.stat(helper)
        except OSError:
            return False
        return stat.S_ISREG(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022

    def lamp_selftest(self, helper: Path) -> tuple[int, str]:
        done = subprocess.run([str(helper)], capture_output=True, text=True, timeout=LAMP_TIMEOUT_S,
                              check=False, env={"PATH": "/usr/bin:/bin"})
        return done.returncode, (done.stderr or "").strip()


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def run_buzzer(system: System) -> tuple[str, str]:
    enabled, pin = buzzer_settings(_read_text(system.path(DISPLAY_ENV)))
    if pin is None:
        return UNAVAILABLE, f"ROSY_BUZZER_PIN이 허용 목록 {sorted(BUZZER_LINES)} 밖 — 울리지 않음"
    if enabled:
        state = system.unit_state(DISPLAY_UNIT)
        if state != "inactive" and state != "failed":
            # The boot display holds the line and beeps at CORE_READY; two owners of
            # one GPIO line is exactly what the D-190 sandbox rules out.
            return BUSY, f"부팅 표시가 BCM {pin} 부저를 쓰는 중 (ROSY_BUZZER_ENABLED=true) — 부팅 때 소리로 확인"
    try:
        system.beep(pin)
    except ImportError as error:
        return UNAVAILABLE, f"RPi.GPIO (rpi-lgpio) 없음: {type(error).__name__}"
    except Exception as error:  # noqa: BLE001 - lgpio raises several kinds
        return FAILED, f"BCM {pin} 구동 실패: {type(error).__name__}"
    return DONE, f"BCM {pin} · 2 kHz · duty {BUZZER_DUTY} % · {BUZZER_BEEPS}×{int(BUZZER_ON_S * 1000)} ms"


def run_lamp(system: System) -> tuple[str, str]:
    if not system.path(LAMP_NODE).exists():
        return UNAVAILABLE, "/dev/ws281x_pwm 없음 (rp1_ws281x_pwm 커널 모듈) — 켜지 않음"
    channel = _read_text(system.path(LAMP_CHANNEL)).strip()
    if channel != LAMP_PWM_CHANNEL:
        return UNAVAILABLE, (f"rp1_ws281x_pwm pwm_channel={channel or '?'} — GPIO19 램프가 아니라 "
                             "LCD 백라이트(GPIO18)를 건드리므로 켜지 않음")
    helper = system.path(LAMP_HELPER)
    if not helper.is_file():
        return UNAVAILABLE, "lamp_selftest 없음 (lamp_control 릴리스)"
    if not system.helper_trusted(helper):
        return UNAVAILABLE, "lamp_selftest 가 root 소유가 아니거나 그룹·다른 사용자가 쓸 수 있음 — 실행하지 않음"
    try:
        code, message = system.lamp_selftest(helper)
    except subprocess.TimeoutExpired:
        return FAILED, f"lamp_selftest {LAMP_TIMEOUT_S:.0f} s 안에 끝나지 않음"
    except OSError as error:
        return FAILED, f"lamp_selftest 실행 실패: {type(error).__name__}"
    if code != 0:
        return FAILED, f"lamp_selftest 종료 {code}: {message[:120]}"
    return DONE, "빨강→초록→파랑 1 s씩 · 8 LED · GPIO19 · 꺼짐"


def group_id(name: str) -> Optional[int]:
    try:
        import grp
        return grp.getgrnam(name).gr_gid
    except (ImportError, KeyError):
        return None


def write_atomic(path: Path, content: str, mode: int, group: Optional[int]) -> None:
    """rosy-hw-probe's write: group and mode on the empty temporary file, then rename."""
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


def _previous_request_id(path: Path) -> Optional[str]:
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("request_id")
    except (OSError, ValueError, AttributeError):
        return None


def main(argv: Optional[list[str]] = None, *, system: Optional[System] = None,
         group: Callable[[str], Optional[int]] = group_id, now: Optional[float] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rosy-hw-test",
        description="Buzzer / lamp test on CORE's request (D-247); writes /run/rosy-boot/hw-test.json.")
    parser.add_argument("--root", type=Path, default=Path("/"), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.root == Path("/") and hasattr(os, "geteuid") and os.geteuid() != 0:
        print("rosy-hw-test: run as root", file=sys.stderr)
        return 1
    system = system or System(args.root)
    request = read_request(args.root / REQUEST, now)
    if request is None:
        print(json.dumps({"hw_test": "ignored"}), flush=True)
        return 0
    if _previous_request_id(args.root / RESULT) == request["request_id"]:
        print(json.dumps({"hw_test": "already_done", "action": request["action"]}), flush=True)
        return 0
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    state, detail = (run_buzzer if request["action"] == "buzzer" else run_lamp)(system)
    result = {"schema": SCHEMA, "request_id": request["request_id"], "action": request["action"],
              "state": state, "detail": detail, "started_at": started,
              "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    write_atomic(args.root / RESULT, json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n",
                 0o640, group(CORE_GROUP))
    print(json.dumps({"hw_test": request["action"], "state": state}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
