#!/usr/bin/env python3
"""Beep the buzzer or flash the lamp once, as root, on an administrator's request (D-247 6).

The buzzer and the WS2812 lamp are devices a machine cannot judge: a person
has to hear or see them. CORE never opens a device (D-161); an administrator
presses the test on the dashboard, CORE writes /run/rosy/hw-test.request, and
rosy-hw-test.path starts this program, which does exactly one of:

* buzzer: three 150 ms beeps, 2 kHz, 10 % duty, on the BCM line
  /etc/rosy/boot-display.env names (ROSY_BUZZER_PIN, default 4, the lines
  rosy-boot-display.py allows).
* lamp: lamp_selftest (built with lamp_control against the pinned rpi_ws281x)
  shows dim red, green and blue for a second each, then turns the lamp off.
  Only when the rp1_ws281x_pwm driver runs on PWM0 channel 3 (GPIO19); its
  default channel 2 is GPIO18, the LCD backlight.

D-260: rosy-boot-display owns the buzzer (on by default) and the lamp (state
patterns) while it runs. Two owners of one GPIO line or of the lamp node is
what the D-190 sandbox rules out, so the test is handed over instead of
refused: this program writes /run/rosy-boot/display-test.request
(root:rosy-display 0640, the same request id), the boot display plays the
same pattern and writes /run/rosy-display/display-test.json, and this program
copies that outcome into its own result. An answer of ``unavailable`` means
the display does not hold the device (buzzer off, lamp left out), so it is
driven here as before. No answer within HANDOFF_WAIT_S is ``failed``: nothing
is driven behind the display's back.

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
# The shared switch parser (rosy_display_env.py) sits beside this program.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import rosy_display_env  # noqa: E402

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
DISPLAY_GROUP = "rosy-display"
#: D-260: the hand-over to rosy-boot-display (its TEST_REQUEST / TEST_RESULT).
HANDOFF_REQUEST = "run/rosy-boot/display-test.request"
HANDOFF_RESULT = "run/rosy-display/display-test.json"
#: The display polls every second; the lamp test itself takes three.
HANDOFF_WAIT_S = 15.0
HANDOFF_POLL_S = 0.2
HANDOFF_STATES = ("done", "unavailable", "failed")
MAX_HANDOFF_BYTES = 1024
MAX_DETAIL = 200
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
    """(ROSY_BUZZER_ENABLED, pin) from boot-display.env; pin None when it is not an allowed line.

    The display's buzzer is on by default since D-260 2 (its unit sets true);
    only an explicit ``false`` leaves the line free.
    """
    values = rosy_display_env.parse_env(text)
    enabled, _valid = rosy_display_env.flag(values, rosy_display_env.BUZZER_KEY)
    pin_text = values.get("ROSY_BUZZER_PIN", str(BUZZER_DEFAULT_LINE))
    if not pin_text.isdigit() or int(pin_text) not in BUZZER_LINES:
        return enabled, None
    return enabled, int(pin_text)


def lamp_owned(text: str) -> bool:
    """D-260 3: the display shows state patterns unless boot-display.env says ROSY_LAMP_ENABLED=false."""
    return rosy_display_env.flag(rosy_display_env.parse_env(text), rosy_display_env.LAMP_KEY)[0]


def read_handoff_result(path: Path, request_id: str) -> Optional[tuple[str, str]]:
    """The boot display's answer for ``request_id``, strictly, or None (not yet, or not trusted)."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) \
        | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_HANDOFF_BYTES:
            return None
        raw = os.read(descriptor, MAX_HANDOFF_BYTES + 1)
    except OSError:
        return None
    finally:
        os.close(descriptor)
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("schema") != 1 or data.get("request_id") != request_id:
        return None
    state, detail = data.get("state"), data.get("detail")
    if state not in HANDOFF_STATES or not isinstance(detail, str):
        return None
    return state, detail[:MAX_DETAIL]


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

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def clock(self) -> float:
        return time.monotonic()

    def display_group(self) -> Optional[int]:
        return group_id(DISPLAY_GROUP)

    def handoff(self, action: str, request_id: str) -> tuple[str, str]:
        """D-260: let rosy-boot-display play the test on the device it owns; its (state, detail)."""
        request = self.path(HANDOFF_REQUEST)
        result = self.path(HANDOFF_RESULT)
        payload = json.dumps({"action": action, "request_id": request_id, "requested_at": time.time()},
                             sort_keys=True) + "\n"
        write_atomic(request, payload, 0o640, self.display_group())
        try:
            deadline = self.clock() + HANDOFF_WAIT_S
            while True:
                answer = read_handoff_result(result, request_id)
                if answer is not None:
                    return answer
                if self.clock() >= deadline:
                    return FAILED, f"부팅 표시가 {HANDOFF_WAIT_S:.0f} s 안에 시험에 답하지 않음 — 구동하지 않음"
                self.sleep(HANDOFF_POLL_S)
        finally:
            request.unlink(missing_ok=True)

    def lamp_selftest(self, helper: Path) -> tuple[int, str]:
        done = subprocess.run([str(helper)], capture_output=True, text=True, timeout=LAMP_TIMEOUT_S,
                              check=False, env={"PATH": "/usr/bin:/bin"})
        return done.returncode, (done.stderr or "").strip()


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _display_takes_it(system: System) -> bool:
    """Hand over only to a display that is up (ActiveState exactly "active") and can read the request.

    activating / auto-restart / an unreadable state: the display is not polling, so
    the device is driven here as before (review M2). Without the rosy-display
    group the display could not read the request (review L4): said once, driven here.
    """
    if system.unit_state(DISPLAY_UNIT) != "active":
        return False
    if system.display_group() is None:
        print(f"rosy-hw-test: no {DISPLAY_GROUP} group; the boot display cannot read a hand-over, "
              "driving the device here", file=sys.stderr, flush=True)
        return False
    return True


def run_buzzer(system: System, request_id: str) -> tuple[str, str]:
    enabled, pin = buzzer_settings(_read_text(system.path(DISPLAY_ENV)))
    if pin is None:
        return UNAVAILABLE, f"ROSY_BUZZER_PIN이 허용 목록 {sorted(BUZZER_LINES)} 밖 — 울리지 않음"
    if enabled and _display_takes_it(system):
        # The boot display holds the line (D-260 2): it plays the test. Two owners of
        # one GPIO line is exactly what the D-190 sandbox rules out.
        state, detail = system.handoff("buzzer", request_id)
        if state != UNAVAILABLE:
            return state, detail
    try:
        system.beep(pin)
    except ImportError as error:
        return UNAVAILABLE, f"RPi.GPIO (rpi-lgpio) 없음: {type(error).__name__}"
    except Exception as error:  # noqa: BLE001 - lgpio raises several kinds
        return FAILED, f"BCM {pin} 구동 실패: {type(error).__name__}"
    return DONE, f"BCM {pin} · 2 kHz · duty {BUZZER_DUTY} % · {BUZZER_BEEPS}×{int(BUZZER_ON_S * 1000)} ms"


def run_lamp(system: System, request_id: str) -> tuple[str, str]:
    if not system.path(LAMP_NODE).exists():
        return UNAVAILABLE, "/dev/ws281x_pwm 없음 (rp1_ws281x_pwm 커널 모듈) — 켜지 않음"
    channel = _read_text(system.path(LAMP_CHANNEL)).strip()
    if channel != LAMP_PWM_CHANNEL:
        return UNAVAILABLE, (f"rp1_ws281x_pwm pwm_channel={channel or '?'} — GPIO19 램프가 아니라 "
                             "LCD 백라이트(GPIO18)를 건드리므로 켜지 않음")
    if lamp_owned(_read_text(system.path(DISPLAY_ENV))) and _display_takes_it(system):
        # The boot display shows the state pattern (D-260 3): it pauses it and plays the test.
        state, detail = system.handoff("lamp", request_id)
        if state != UNAVAILABLE:
            return state, detail
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
    state, detail = (run_buzzer if request["action"] == "buzzer" else run_lamp)(system, request["request_id"])
    result = {"schema": SCHEMA, "request_id": request["request_id"], "action": request["action"],
              "state": state, "detail": detail, "started_at": started,
              "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    write_atomic(args.root / RESULT, json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n",
                 0o640, group(CORE_GROUP))
    print(json.dumps({"hw_test": request["action"], "state": state}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
