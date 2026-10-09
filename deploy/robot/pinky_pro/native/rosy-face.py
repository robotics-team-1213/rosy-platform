#!/usr/bin/env python3
"""rosy-face: the robot's screen, sound and light for its whole life (D-433; D-190, D-260).

D-433: one process outside ROS owns the LCD panel and backlight, the buzzer and
the lamp from power-on to shutdown (formerly rosy-boot-display, which drew only
the boot card). What the LCD draws comes from one rule table,
``core_common.face_screen.screen_for``: status cards (failure, update, e-stop,
AP, booting, CORE not responding, unused login code) hide the face; otherwise
the emotion GIF CORE chose plays under a status bar (text, level colour, battery), or
the D-394 drive / PWR-003 wake card takes its place. The lamp, the bar, the expression and
the sound all come from one core_common.presentation record (D-552).
CORE hands its part over in /run/rosy/face-inputs.json (rosy-core's runtime directory, 0644,
rewritten every second); older than three seconds is no hand-over, so a dead
CORE sends the screen back to the status card. GIF frames are converted to the
panel's bytes once, lazily, and replayed (D-185 budget). The buzzer and lamp
behaviour below is unchanged.

Show the ROSY boot stage on the Pinky Pro LCD and buzzer (D-190, D-174 T1/T2).

A long-running process, outside CORE (D-161), as the unprivileged user
rosy-display. The ST7789 backlight is a software PWM on GPIO18 that lives only
as long as this process (D-190 S0): a one-shot draw leaves the screen dark.

Inputs, all read-only:

* /run/rosy-boot/boot-status.json - stage, failed unit, name, IPv4, release
  (rosy-boot-status, root);
* /run/rosy-boot/network.json - AP mode, SSID, address (rosy-network, root);
* /run/rosy-boot/ap-display.txt - the AP SSID and key, root:rosy-display 0640,
  written by rosy-network only while the AP is up (D-176). Never logged. The
  card draws them as text and as a Wi-Fi join QR (emotion.wifi_qr), which
  holds the key too and is likewise only drawn;
* /run/rosy-boot/login-display.txt - the one-time dashboard login code and its
  role, or BURNED, root:rosy-display 0640, written by rosy-login-code (D-193).
  Shown only at CORE_READY. Never logged;
* the battery ADC on /dev/i2c-1 through ``rosylib.Battery``, which holds the
  same flock as every other Rosy reader of 0x08 (D-192), so it is read
  directly whether rosy-io runs or not.

It polls the files every second and redraws only when what it would draw
changes. The battery is refreshed every BATTERY_INTERVAL_S; a missing battery
bus draws "--" and is retried.

Exit codes (D-190 security review): a board with no /dev/spidev0.0 has no SPI
panel at all, a stable configuration, so the program exits 0 when the buzzer
is off too. A panel node that is there but cannot be driven (libraries missing,
GPIO chip label unreadable or not RP1, open failing after LCD_ATTEMPTS) is a
fault: exit 1, visible in systemd and capped by StartLimitBurst. It never
drives the lines blind. The buzzer (BCM 4 on the Pro, heard on rosy_18 on
2026-09-26; BCM 22 on sibling boards is silent there) is on by default since
D-260 decision 2; ROSY_BUZZER_ENABLED=false in /etc/rosy/boot-display.env turns
it off.

D-260: the same robot state as the dashboard summary line. boot-status.json
also carries the runtime mode and the probe's device states (rosy-boot-status
copies them; runtime.env and hardware.json are not readable here), and
``core_common.robot_state`` (the release's, next to emotion) folds them with
the stage and the battery into one state:

* the buzzer sounds on state changes only: once when ready, three times on
  failure, two low tones on caution; caution is not repeated within
  BUZZER_REPEAT_S. D-381: entering the emergency pattern (an e-stop) adds
  four higher beeps, once per entry, whatever the health state says;
* the WS2812 lamp shows the state's pattern through ``lamp_pattern`` (one
  helper process per pattern, /dev/ws281x_pwm granted to this unit alone),
  and only when the driver runs on PWM0 channel 3 (GPIO19; channel 2 is the
  LCD backlight). Anything missing leaves the lamp out, never the boot.
  D-380: while CORE keeps its hand-over fresh, the lamp also names the
  operating mode (manual/navigating/docking/emergency patterns) beside the
  health state — the rule table's priority decides which one wins;
* the LCD gets the state line and the most urgent todo (ASCII: the card font
  has no Hangul);
* a D-247 buzzer or lamp test that rosy-hw-test hands over while this program
  owns the device is played here (TEST_REQUEST, TEST_RESULT).
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import signal
import sys
import time
import stat
import subprocess
import types
from typing import Callable

sys.dont_write_bytecode = True
# The shared switch parser (rosy_display_env.py) sits beside this program.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import rosy_display_env  # noqa: E402

try:  # the release's rule table (D-260); an older release has none
    from core_common import robot_state
except ImportError:
    robot_state = None
try:  # D-433: the screen's situation table and CORE's hand-over reader
    from core_common import face_screen
except ImportError:
    face_screen = None
try:  # the lamp, bar, expression and sound from one record (D-433 amendment 2026-10-09)
    from core_common import presentation
except ImportError:
    presentation = None

STATUS_DIR = "run/rosy-boot"
#: D-548: root's marker that this robot accepts the shared rosy-dev-* API tokens.
DEV_MODE_FILE = "etc/rosy/dev-mode"
LOGIN_CODE = re.compile(r"^[23456789ABCDEFGHJKMNPQRSTUVWXYZ]{4}-[23456789ABCDEFGHJKMNPQRSTUVWXYZ]{4}$")
LOGIN_ROLES = frozenset({"viewer", "operator", "administrator"})
POLL_S = 0.5  # D-433: the files and the situation table; face frames tick faster
TICK_S = 0.1  # face frames, 10 fps (5 fps at the idle backlight)
#: D-433: CORE's hand-over (rosy-core's /run/rosy, 0644) and its writer's account.
FACE_INPUTS = "run/rosy/face-inputs.json"
CORE_USER = "rosy-core"
#: D-483: CORE's pending peer-request approval code (rosy-core:rosy-display 2750, file 0640).
#: The code is a credential: drawn on the card, never logged.
PEER_APPROVAL = "run/rosy-peer-display/approval.json"
#: The emotion GIFs the running release ships (share/emotion/emotion/<name>.gif).
FACE_DIR = "opt/rosy/current/install/share/emotion/emotion"
FACE_LOAD_SKIP = 1  # 320x240 authored frames match the 10 fps panel tick
FACE_SIZE = (320, 240)
#: D-433 row 3: the updater (root) writes two lines, step and release id, while it applies.
UPDATE_DISPLAY = "run/rosy-boot/update-display.txt"
UPDATE_MAX_AGE_S = 1800.0  # a marker an updater crash left behind stops counting
RELEASE_ID = re.compile(r"[0-9]{4}\.[0-9]{2}\.[0-9]{2}-[0-9]{3}")
#: systemd-user-sessions writes it when the system goes down: SIGTERM then is a shutdown.
SHUTDOWN_MARK = "run/nologin"
BATTERY_INTERVAL_S = 15.0
LCD_ATTEMPTS = 6  # udev may still be applying the device groups at start
LCD_RETRY_S = 5.0
RP1_LABEL = "pinctrl-rp1"
GPIOCHIP = "/dev/gpiochip4"
SPIDEV = "dev/spidev0.0"
# Header BCM lines nothing else owns (board.yaml boot_display.buzzer; checked
# against its header_bcm_owners): not I2C0/1 (0-3), SPI0 (7-11), UART4 motor
# (12/13), UART0 LiDAR (14/15), the LCD (18/25/27) or the bench lamp (19).
BUZZER_LINES = frozenset({4, 5, 6, 16, 17, 20, 21, 22, 23, 24, 26})
# The Pinky Pro buzzer (board.yaml boot_display.buzzer.bcm_line), heard on rosy_18 2026-09-26.
BUZZER_DEFAULT_LINE = 4
BUZZER_FREQUENCY_HZ = 2000
BUZZER_LOW_HZ = 800  # D-260 2: caution is two low tones
BUZZER_DUTY = 10  # percent; a passive piezo is quiet at a low duty cycle
BUZZER_ON_S = 0.08
BUZZER_OFF_S = 0.12
#: D-260 2, per health sound: (beeps, frequency). Ready and held ready share one sound.
#: D-381: an e-stop entry is four higher beeps — failed is three at 2 kHz, so the
#: two alarms never read alike.
#: A fleet identify is not a health sound (D-472). Two middle beeps, once, and it
#: does not replace the health sound the robot is already in.
BUZZER_CALL_HZ = 1400
#: D-546: the reversing alarm — one 80 ms 1 kHz beep every BUZZER_REVERSE_S while CORE
#: names the lane-recovery phase ``retrace``. Not a state sound: it repeats while it lasts.
BUZZER_REVERSE_HZ = 1000
BUZZER_REVERSE_S = 1.0
#: D-546: the recovering lamp and LCD line outlast the last RECOVERING tick by this long, so
#: they do not flicker between phases. The beep and an e-stop do not wait for it.
RECOVERY_HOLD_S = 1.5
BUZZER_PATTERNS = {"ready": (1, BUZZER_FREQUENCY_HZ), "failed": (3, BUZZER_FREQUENCY_HZ),
                   "caution": (2, BUZZER_LOW_HZ), "emergency": (4, 2500),
                   "call": (2, BUZZER_CALL_HZ), "reverse": (1, BUZZER_REVERSE_HZ)}
#: Caution again inside this window stays silent (a battery near the threshold). Ready and
#: failed always sound on a real transition (review L2): they are the news a person waits for.
BUZZER_REPEAT_S = 300.0
REPEAT_LIMITED = frozenset({"caution"})
#: A caution (health or a CORE code) must hold this long before it sounds: a flapping one stays silent.
CAUTION_DEBOUNCE_S = 2.0
#: D-247 6's buzzer test, when handed over: three 150 ms beeps, like rosy-hw-test.
TEST_BEEPS, TEST_ON_S, TEST_OFF_S = 3, 0.15, 0.15
#: robot state -> sound; booting is silent.
#: Only for a release without core_common.presentation (tests pin it equal to presentation.SOUNDS).
SOUNDS = {"ready": "ready", "ready_held": "ready", "failed": "failed", "caution": "caution"}
#: robot state -> lamp_pattern argument (D-260 3). Fallback for a release without the
#: rule table; with it, the table also folds CORE's mode in (D-380, robot_state.lamp_pattern).
LAMP_PATTERNS = {"booting": "booting", "ready": "ready", "ready_held": "ready", "failed": "failed",
                 "caution": "caution"}
LAMP_NODE = "dev/ws281x_pwm"
LAMP_CHANNEL = "sys/module/rp1_ws281x_pwm/parameters/pwm_channel"
LAMP_PWM_CHANNEL = "3"  # GPIO19; the default 2 is GPIO18, the LCD backlight
LAMP_HELPER = "opt/rosy/current/install/lib/lamp_control/lamp_pattern"
LAMP_STOP_S = 2.0
LAMP_TEST_S = 10.0
# D-260 / D-247 6: rosy-hw-test hands a buzzer or lamp test to this program while
# it owns the device. The request is root:rosy-display 0640 in /run/rosy-boot;
# the outcome goes to this unit's own runtime directory, which rosy-hw-test reads.
TEST_REQUEST = "run/rosy-boot/display-test.request"
TEST_RESULT = "run/rosy-display/display-test.json"
TEST_ACTIONS = ("buzzer", "lamp", "identify_blue", "identify_amber")
TEST_REQUEST_MAX_AGE_S = 30.0
#: D-472 4: Fleet's identity window is <= 6 s from its request. rosy-hw-test passes an identify
#: on within 1.5 s, this program must take the hand-over within IDENTIFY_REQUEST_MAX_AGE_S
#: (two polls) and ends the 3 s blink by IDENTIFY_MAX_S whatever the helper does.
IDENTIFY_REQUEST_MAX_AGE_S = 1.0
IDENTIFY_MAX_S = 3.5
#: D-472 addendum 5: a blink may stand in for these normal patterns, moving or not. Booting,
#: failed, emergency, caution and blocked (D-381) always win: refused, or cut short.
IDENTIFY_OVER = frozenset({"ready", "manual", "navigating", "docking", "illumination"})
MAX_TEST_REQUEST_BYTES = 512
TEST_REQUEST_ID = re.compile(r"[0-9a-f]{16,64}")


class Log:
    """stderr lines for the journal; each key is reported once."""

    def __init__(self, write: Callable[[str], None] | None = None) -> None:
        self._write = write or (lambda line: print(line, file=sys.stderr, flush=True))
        self._seen: set[str] = set()

    def once(self, key: str, message: str) -> None:
        if key not in self._seen:
            self._seen.add(key)
            self._write(f"rosy-face: {message}")


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def read_view(root: Path, battery: tuple[float, float] | None) -> dict:
    """What the card shows, from the indicator files and the last battery reading."""
    status = _read_json(root / STATUS_DIR / "boot-status.json")
    network = {key: value for key, value in _read_json(root / STATUS_DIR / "network.json").items()
               if key in {"mode", "ssid", "address"}}
    view = {
        "stage": status.get("stage") or "BOOTING",
        "failed_unit": status.get("failed_unit"),
        "detail": status.get("detail"),
        "device_name": status.get("device_name"),
        "release_id": status.get("release_id"),
        "ipv4": status.get("ipv4") or [],
        "api_port": status.get("api_port") or 8080,
        "network": network,
        "robot_mode": status.get("robot_mode"),
        "nav_state": status.get("nav_state"),
        "swarm_role": status.get("swarm_role"),
        "battery_percent": None if battery is None else round(battery[0]),
        "battery_voltage": None if battery is None else round(battery[1], 2),
    }
    if network.get("mode") == "ap":
        try:
            lines = (root / STATUS_DIR / "ap-display.txt").read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            lines = []
        if len(lines) >= 2 and lines[1]:
            network["ssid"] = network.get("ssid") or lines[0]
            view["ap_login"] = lines[1]
    if view["stage"] == "CORE_READY":
        view.update(_login_view(root))
    view.update(_state_view(view, status))
    if (root / DEV_MODE_FILE).is_file():
        view["dev_mode"] = True
        if view.get("state_line"):
            view["state_line"] = "DEV " + view["state_line"]
    return view


def _state_view(view: dict, status: dict) -> dict:
    """D-260: the robot state, its LCD line and the top todo, from the shared rule table."""
    if robot_state is None:
        return {}
    devices = status.get("devices") if isinstance(status.get("devices"), list) else []
    mode = status.get("runtime_mode") if isinstance(status.get("runtime_mode"), str) else None
    # D-260 M1: CORE's live SAF-005 warning when rosy-boot-status copied it; else the table's default.
    warning = status.get("battery_warning_percent")
    if isinstance(warning, bool) or not isinstance(warning, (int, float)):
        warning = robot_state.BATTERY_WARNING_PERCENT
    result = robot_state.evaluate(view["stage"], devices, battery_percent=view["battery_percent"],
                                  battery_warning_percent=warning, runtime_mode=mode,
                                  failed_unit=view["failed_unit"],
                                  robot_mode=status.get("robot_mode"))
    todos = result["todos"]
    # D-380: the LCD line names the operating mode beside the health state — the
    # lamp shows it as a colour, the card says it in words. D-383: a formation
    # role rides at the end ("Ready - NAVIGATION - LEADER").
    line = (robot_state.state_line(result, lcd=True)
            + robot_state.mode_suffix(status.get("robot_mode"))
            + robot_state.role_suffix(status.get("swarm_role")))
    return {"robot_state": result["state"], "state_line": line,
            "todo": todos[0]["lcd"] if todos else None}


def _login_view(root: Path) -> dict:
    """D-193: the login line from rosy-login-code's hand-off; only well-formed values."""
    try:
        lines = (root / STATUS_DIR / "login-display.txt").read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return {}
    if lines and lines[0] == "BURNED":
        return {"login_burned": True}
    if len(lines) >= 2 and LOGIN_CODE.fullmatch(lines[0]) and lines[1] in LOGIN_ROLES:
        return {"login_code": lines[0], "login_role": lines[1]}
    return {}


class BatteryReader:
    """``rosylib.Battery`` opened lazily; any failure is None, logged once."""

    def __init__(self, factory: Callable[[], object] | None, percent: Callable[[float], float],
                 log: Log) -> None:
        self._factory = factory
        self._percent = percent
        self._log = log
        self._battery = None

    def read(self) -> tuple[float, float] | None:
        if self._factory is None:
            return None
        try:
            if self._battery is None:
                self._battery = self._factory()
            voltage = float(self._battery.get_voltage())
        except OSError as exc:
            self._log.once("battery", f"battery ADC unavailable ({exc}); showing '--' and retrying")
            self.close()
            return None
        return self._percent(voltage), voltage

    def close(self) -> None:
        battery, self._battery = self._battery, None
        if battery is not None:
            try:
                battery.close()
            except OSError:
                pass


class Buzzer:
    """Short, quiet beeps on robot-state changes (D-260 2): ready once, failed three times, caution two low."""

    def __init__(self, gpio, pin: int, enabled: bool, sleep: Callable[[float], None]) -> None:
        self._gpio = gpio
        self._pin = pin
        self.enabled = enabled and gpio is not None
        self._sleep = sleep
        self._pwm = None
        self._frequency: int | None = None

    def _tones(self, count: int, frequency: int, on_s: float, off_s: float) -> int:
        if self._pwm is None:
            # The LCD sets BCM mode too; set it here for a display without an LCD.
            self._gpio.setwarnings(False)
            self._gpio.setmode(self._gpio.BCM)
            self._gpio.setup(self._pin, self._gpio.OUT)
            self._pwm = self._gpio.PWM(self._pin, frequency)
            self._frequency = frequency
        elif frequency != self._frequency:
            self._pwm.ChangeFrequency(frequency)
            self._frequency = frequency
        for index in range(count):
            self._pwm.start(BUZZER_DUTY)
            try:
                self._sleep(on_s)
            finally:
                self._pwm.stop()  # a failed sleep must not leave the piezo on
            if index + 1 < count:
                self._sleep(off_s)
        return count

    def announce(self, sound: str | None) -> int:
        """Play the pattern for ``sound`` (a BUZZER_PATTERNS key); the number of beeps."""
        count, frequency = BUZZER_PATTERNS.get(sound or "", (0, BUZZER_FREQUENCY_HZ))
        if not self.enabled or not count:
            return 0
        return self._tones(count, frequency, BUZZER_ON_S, BUZZER_OFF_S)

    def test(self) -> tuple[str, str]:
        """D-247 6's test pattern, played for rosy-hw-test: (state, detail) in its words."""
        if not self.enabled:
            return "unavailable", "부팅 표시의 부저가 꺼져 있음"
        try:
            self._tones(TEST_BEEPS, BUZZER_FREQUENCY_HZ, TEST_ON_S, TEST_OFF_S)
        except Exception as exc:  # noqa: BLE001 - lgpio raises several kinds
            return "failed", f"BCM {self._pin} 구동 실패: {type(exc).__name__}"
        return "done", (f"BCM {self._pin} · 2 kHz · duty {BUZZER_DUTY} % · "
                        f"{TEST_BEEPS}×{int(TEST_ON_S * 1000)} ms (부팅 표시가 울림)")


class Lamp:
    """The WS2812 lamp through ``lamp_pattern``; fail-open (D-260 3).

    One helper process per pattern; a new state stops the old one (SIGTERM, the
    helper leaves the lamp dark) before the next starts. The driver must be on
    PWM0 channel 3: channel 2 would drive GPIO18, the LCD backlight.
    """

    def __init__(self, root: Path, enabled: bool, log: Log,
                 spawn: Callable[[list[str]], object] | None = None) -> None:
        self._root = root
        self.enabled = enabled
        self._log = log
        self._spawn = spawn or _spawn_helper
        self._process = None
        self.pattern: str | None = None

    def available(self, *, for_identify: bool = False) -> bool:
        if not self.enabled and not for_identify:
            return False
        if not (self._root / LAMP_NODE).exists():
            self._log.once("lamp-node", "no /dev/ws281x_pwm (rp1_ws281x_pwm); lamp left out")
            return False
        try:
            channel = (self._root / LAMP_CHANNEL).read_text(encoding="ascii").strip()
        except (OSError, UnicodeDecodeError):
            channel = ""
        if channel != LAMP_PWM_CHANNEL:
            self._log.once("lamp-channel", f"rp1_ws281x_pwm pwm_channel={channel or '?'}, not 3 (GPIO19); "
                                           "lamp left out: it would drive the LCD backlight")
            return False
        if not (self._root / LAMP_HELPER).is_file():
            self._log.once("lamp-helper", "no lamp_pattern in the release; lamp left out")
            return False
        return True

    def show(self, pattern: str | None) -> bool:
        """Start ``pattern`` unless it already shows; False when the lamp is left out."""
        if pattern == self.pattern:
            return self._process is not None
        self.stop()
        self.pattern = pattern
        if pattern is None or not self.available():
            return False
        try:
            self._process = self._spawn([str(self._root / LAMP_HELPER), pattern])
        except OSError as exc:
            self._log.once("lamp-spawn", f"lamp_pattern would not start ({type(exc).__name__}); lamp left out")
            return False
        return True

    def poll(self) -> None:
        """Reap a helper that ended; a failure is logged once and not restarted until the state changes."""
        process = self._process
        if process is None or process.poll() is None:
            return
        self._process = None
        if process.returncode not in (0, None):
            self._log.once(f"lamp-exit-{process.returncode}",
                           f"lamp_pattern {self.pattern} ended with {process.returncode}; lamp left out")

    def stop(self) -> None:
        process, self._process = self._process, None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=LAMP_STOP_S)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=LAMP_STOP_S)

    def test(self) -> tuple[str, str]:
        """D-247 6's lamp test, played for rosy-hw-test; the state pattern resumes after it."""
        resume, self.pattern = self.pattern, None
        self.stop()
        if not self.available():
            self.show(resume)
            return "unavailable", "부팅 표시가 램프를 쓸 수 없음 (드라이버·채널·lamp_pattern)"
        process = None
        try:
            process = self._spawn([str(self._root / LAMP_HELPER), "test"])
            code = process.wait(timeout=LAMP_TEST_S)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=LAMP_STOP_S)
            code = "timeout"
        except OSError as exc:
            code = type(exc).__name__
        self.show(resume)
        if code != 0:
            return "failed", f"lamp_pattern test 종료 {code}"
        return "done", "빨강→초록→파랑 1 s씩 · 8 LED · GPIO19 · 꺼짐 (부팅 표시가 켬)"

    def identify(self, color: str, unsafe: Callable[[], bool]) -> tuple[str, str]:
        """Temporary blue/amber pulse, then restore the state pattern."""
        resume, self.pattern = self.pattern if self.enabled else None, None
        self.stop()
        if not self.available(for_identify=True):
            self.show(resume)
            return "unavailable", "램프를 사용할 수 없음"
        process = None
        try:
            process = self._spawn([str(self._root / LAMP_HELPER), f"identify_{color}"])
            deadline = time.monotonic() + IDENTIFY_MAX_S
            while process.poll() is None:
                if unsafe():
                    process.terminate()
                    try:
                        process.wait(timeout=LAMP_STOP_S)
                    except subprocess.TimeoutExpired:
                        self._reap_killed(process)
                    self.show(None)
                    return "failed", "안전·운행 상태가 바뀌어 식별 점멸 중단"
                if time.monotonic() >= deadline:
                    self._reap_killed(process)
                    self.show(None)
                    return "failed", "식별 점멸 시간 초과"
                time.sleep(0.05)
            code = process.returncode
        except OSError as exc:
            code = type(exc).__name__
        if unsafe():
            self.show(None)
            return "failed", "안전·운행 상태가 바뀌어 식별 점멸 중단"
        self.show(resume)
        return ("done", f"{color} 식별 점멸 완료") if code == 0 else ("failed", f"식별 점멸 종료 {code}")

    def _reap_killed(self, process) -> None:
        """SIGKILL; a helper that still does not exit is logged and left, never raised (review 2026-10-08).

        The caller goes on to show(None) and the next step() shows the state pattern."""
        process.kill()
        try:
            process.wait(timeout=LAMP_STOP_S)
        except subprocess.TimeoutExpired:
            self._log.once("lamp-identify-kill", "lamp_pattern identify did not exit after SIGKILL; "
                                                 "going on to the state pattern")


def _spawn_helper(command: list[str]):
    return subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, env={"PATH": "/usr/bin:/bin"}, close_fds=True)


def read_test_request(path: Path, now: float) -> dict | None:
    """rosy-hw-test's hand-over, strictly: regular file, no link, small, known keys, fresh."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) \
        | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_TEST_REQUEST_BYTES:
            return None
        raw = os.read(descriptor, MAX_TEST_REQUEST_BYTES + 1)
    except OSError:
        return None
    finally:
        os.close(descriptor)
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(data, dict) or set(data) != {"action", "request_id", "requested_at"}:
        return None
    if data["action"] not in TEST_ACTIONS or not isinstance(data["request_id"], str) \
            or not TEST_REQUEST_ID.fullmatch(data["request_id"]):
        return None
    requested = data["requested_at"]
    if isinstance(requested, bool) or not isinstance(requested, (int, float)):
        return None
    limit = IDENTIFY_REQUEST_MAX_AGE_S if data["action"].startswith("identify_") else TEST_REQUEST_MAX_AGE_S
    if not -5.0 <= now - float(requested) <= limit:
        return None
    return data


def write_test_result(path: Path, content: str) -> None:
    """The outcome, replaced atomically in this unit's own runtime directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(temporary, flags, 0o644)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(content)
    os.replace(temporary, path)


def buzzer_settings(environ: dict[str, str], log: Log) -> tuple[bool, int]:
    """ROSY_BUZZER_ENABLED (exactly true/false, default true since D-260 2) and ROSY_BUZZER_PIN (BCM)."""
    enabled, valid = rosy_display_env.flag(environ, rosy_display_env.BUZZER_KEY)
    if not valid:
        log.once("buzzer-config", "ROSY_BUZZER_ENABLED must be true or false, got "
                                  f"{environ.get('ROSY_BUZZER_ENABLED')!r}; buzzer off")
    pin_text = rosy_display_env.unquote(environ.get("ROSY_BUZZER_PIN", str(BUZZER_DEFAULT_LINE)))
    if not pin_text.isdigit() or int(pin_text) not in BUZZER_LINES:
        log.once("buzzer-config", f"ROSY_BUZZER_PIN {pin_text!r} is not a free header BCM line "
                                  f"{sorted(BUZZER_LINES)}; buzzer off")
        return False, BUZZER_DEFAULT_LINE
    return enabled, int(pin_text)


def lamp_enabled(environ: dict[str, str], log: Log) -> bool:
    """ROSY_LAMP_ENABLED (exactly true/false, default true, D-260 3)."""
    enabled, valid = rosy_display_env.flag(environ, rosy_display_env.LAMP_KEY)
    if not valid:
        log.once("lamp-config", "ROSY_LAMP_ENABLED must be true or false, got "
                                f"{environ.get('ROSY_LAMP_ENABLED')!r}; lamp off")
    return enabled


def read_update(root: Path, wall: float) -> dict | None:
    """D-433 row 3: the update marker the updater (root) writes while it applies, or None.

    Two lines, ``<step>`` and the candidate release id; nothing secret. A marker
    older than UPDATE_MAX_AGE_S is ignored, so a crashed updater cannot pin the screen.
    """
    path = root / UPDATE_DISPLAY
    try:
        if path.is_symlink() or not path.is_file() or wall - path.stat().st_mtime > UPDATE_MAX_AGE_S:
            return None
        lines = path.read_text(encoding="utf-8")[:256].splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    if not lines or not re.fullmatch(r"[a-z-]{1,32}", lines[0]):
        return None
    release = lines[1] if len(lines) > 1 and RELEASE_ID.fullmatch(lines[1]) else None
    return {"step": lines[0], "release": release}


class FaceFrames:
    """The emotion GIFs as panel bytes, converted once and lazily (D-433 decision 4).

    A face's frames are converted one per call while it first plays (every
    FACE_LOAD_SKIP-th GIF frame), so no single tick pays for a whole GIF and a
    face that is never shown is never loaded. Afterwards the bytes replay.
    """

    def __init__(self, directory: Path, *, opener: Callable[[Path], object],
                 convert: Callable[[object], object], log: Log, skip: int = FACE_LOAD_SKIP) -> None:
        self._directory = directory
        self._open = opener
        self._convert = convert
        self._log = log
        self._skip = skip
        self._faces: dict[str, dict] = {}

    def frame_count(self, name: str) -> int:
        return len(self._faces.get(name, {}).get("frames", []))

    def next(self, name: str):
        """The next panel frame of ``name``, or None when that GIF cannot be read."""
        entry = self._faces.get(name)
        if entry is None:
            entry = {"frames": [], "image": None, "done": False, "source": 0, "position": -1}
            try:
                entry["image"] = self._open(self._directory / f"{name}.gif")
            except (OSError, ValueError) as exc:
                self._log.once(f"face-{name}", f"face {name!r} unavailable ({type(exc).__name__})")
                entry["done"] = True
            self._faces[name] = entry
        if not entry["done"]:
            image = entry["image"]
            try:
                image.seek(entry["source"])
                entry["frames"].append(self._convert(image))
                entry["source"] += self._skip
                entry["position"] = len(entry["frames"]) - 1
                return entry["frames"][-1]
            except EOFError:
                pass
            except (OSError, ValueError) as exc:
                self._log.once(f"face-{name}-frame", f"face {name!r} frame unreadable ({type(exc).__name__})")
            entry["done"] = True
            entry["image"] = None
            if hasattr(image, "close"):
                image.close()
        if not entry["frames"]:
            return None
        entry["position"] = (entry["position"] + 1) % len(entry["frames"])
        return entry["frames"][entry["position"]]


class FaceDisplay:
    """One poll: read the view, decide the screen, sound and light a new state; tick the face."""

    def __init__(self, root: Path, *, lcd, render: Callable[[dict], object], battery: BatteryReader,
                 buzzer: Buzzer, clock: Callable[[], float], lamp: Lamp | None = None,
                 wall: Callable[[], float] = time.time,
                 battery_interval: float = BATTERY_INTERVAL_S,
                 faces: FaceFrames | None = None,
                 strip: Callable[[object, str, str], object] | None = None,
                 core_owner: int | None = None, low_light_assist: bool = False) -> None:
        self.root = root
        self.lcd = lcd
        self._render = render
        self._battery = battery
        self._buzzer = buzzer
        self._lamp = lamp
        self._clock = clock
        self._wall = wall
        self._battery_interval = battery_interval
        self._battery_due: float | None = None
        self._battery_value: tuple[float, float] | None = None
        self._drawn: str | None = None
        self._state: str | None = None
        self._sounded: dict[str, float] = {}
        self._sound: str | None = None
        self._reversed_at: float | None = None
        self._caution_since: float | None = None
        self._held: tuple[str, float] | None = None
        self._tested: str | None = None
        self._faces = faces
        self._strip = strip
        self._core_owner = core_owner
        self._last_core: dict | None = None
        self._low_light_enabled = low_light_assist
        self._light_session = False
        self._mode: str | None = None
        self._drive_since: float | None = None
        self._testing: str | None = None
        self._testing_until = 0.0
        self._awake = True
        self._backlight = 100
        self._ticks = 0
        self.shutting_down = False
        self.animating: tuple | None = None
        self.screen: dict | None = None
        self.draws = 0
        self.frames = 0
        self.battery_reads = 0

    @staticmethod
    def robot_state_of(view: dict) -> str:
        """The rule table's state, or the stage alone on a release without the table."""
        if view.get("robot_state"):
            return str(view["robot_state"])
        kind = str(view["stage"]).split(":", 1)[0]
        return {"CORE_READY": "ready", "FAILED": "failed"}.get(kind, "booting")

    @staticmethod
    def _present(view: dict, state: str, core: dict | None, screen: dict | None):
        """The one record for lamp, bar, expression and sound (core_common.presentation). A release
        with the rule table but not the record gets the same fields from the old rules."""
        if robot_state is not None and presentation is not None:
            return presentation.present(state=state, robot_mode=view.get("robot_mode"),
                                        nav_state=view.get("nav_state"), core=core, screen=screen,
                                        battery_percent=view.get("battery_percent"))
        lamp = LAMP_PATTERNS.get(state)
        if robot_state is not None:
            args = (state, (core or {}).get("robot_mode") or view.get("robot_mode"),
                    (core or {}).get("nav_state") or view.get("nav_state"))
            recovery = (core or {}).get("recovery")
            signal = (core or {}).get("signal")
            try:
                lamp = robot_state.lamp_pattern(*args, recovery, signal)
            except TypeError:  # before the turn signal, then before D-546's recovery argument
                try:
                    lamp = robot_state.lamp_pattern(*args, recovery)
                except TypeError:
                    lamp = robot_state.lamp_pattern(*args)
        bar = None if not screen or screen["kind"] != "face" else (
            screen["face"], screen["strip"] or "", "caution" if screen["strip_tone"] == "caution" else "ok", None, None)
        return types.SimpleNamespace(
            state=state, lamp=lamp, bar=bar, sound="emergency" if lamp == "emergency" else SOUNDS.get(state),
            reversing=bool(core) and core.get("estop") is False and lamp == "recovering"
            and core.get("recovery") == "retrace")

    @staticmethod
    def lamp_pattern_for(view: dict, state: str, core: dict | None = None) -> str | None:
        return FaceDisplay._present(view, state, core, None).lamp

    def _announce(self, sound: str | None, now: float) -> None:
        """Sound ``pres.sound`` on a change (D-381: the e-stop alarm replaces the health sound; ready and
        held ready are one sound). A caution must hold CAUTION_DEBOUNCE_S first; caution, and the ready that
        follows it, repeat at most every BUZZER_REPEAT_S. The e-stop, failed and the ready after them always sound."""
        if sound == "caution":
            self._caution_since = now if self._caution_since is None else self._caution_since
            if now - self._caution_since < CAUTION_DEBOUNCE_S:
                return  # not yet a caution: self._sound keeps the sound it had
        else:
            self._caution_since = None
        previous, self._sound = self._sound, sound
        if sound is None or sound == previous:
            return
        last = self._sounded.get(sound)
        # ready is limited only when it follows a caution (the flapping case); after an e-stop or a failure it is news.
        if ((sound in REPEAT_LIMITED or (sound == "ready" and previous == "caution"))
                and last is not None and now - last < BUZZER_REPEAT_S):
            return
        self._sounded[sound] = now
        self._buzzer.announce(sound)

    def handle_test(self) -> str | None:
        """Play a D-247 test rosy-hw-test handed over; each request id once. The state played, or None."""
        request = read_test_request(self.root / TEST_REQUEST, self._wall())
        if request is None or request["request_id"] == self._tested:
            return None
        def unsafe_identity() -> bool:
            # D-472 5: e-stop, fault, caution or no CORE hand-over: the safety display wins.
            # The pattern is recomputed from the files (the lamp's own is None mid-blink).
            core = self._core()
            if core is None or core.get("estop") is not False or core.get("caution"):
                return True
            view = read_view(self.root, self._battery_value)
            return self.lamp_pattern_for(view, self.robot_state_of(view), core) not in IDENTIFY_OVER
        identifying = request["action"].startswith("identify_")
        identify_ready = identifying and self._lamp is not None and self._lamp.available(for_identify=True)
        if identifying and (not identify_ready or unsafe_identity()):
            # Answered at once, so rosy-hw-test does not wait out its hand-over timeout.
            self._tested = request["request_id"]
            state = "failed" if identify_ready else "unavailable"
            write_test_result(self.root / TEST_RESULT, json.dumps(
                {"schema": 1, "request_id": request["request_id"], "action": request["action"],
                 "state": state, "detail": "안전·상태 표시가 우선 — 식별 점멸 거절"},
                ensure_ascii=False, sort_keys=True) + "\n")
            return state
        if self._lamp is not None and self._lamp.pattern in ("emergency", "failed", "caution", "recovering", "bridging"):
            return None
        if self.screen and (self.screen["kind"] in ("stopped", "update", "shutdown")
                            or self.screen["row"] == "failed" or self.screen.get("strip_tone") == "caution"):
            return None  # Alarm outputs must never wait for a blocking bench test.
        if self._lamp is not None and self._light_session:
            self._lamp.show(None)
        self._tested = request["request_id"]
        # D-433 row 10: the strip names the test while it plays.
        self._testing, self._testing_until = request["action"], self._clock() + LAMP_TEST_S
        if request["action"] == "buzzer":
            state, detail = self._buzzer.test()
        elif self._lamp is not None and request["action"].startswith("identify_"):
            # Once, at accept. self._sound stays the health sound, so the next
            # ready transition still chirps. A refused call returns before this.
            self._buzzer.announce("call")
            state, detail = self._lamp.identify(request["action"].removeprefix("identify_"), unsafe_identity)
        elif self._lamp is not None:
            state, detail = self._lamp.test()
        else:
            state, detail = "unavailable", "부팅 표시에 램프가 없음"
        write_test_result(self.root / TEST_RESULT, json.dumps(
            {"schema": 1, "request_id": request["request_id"], "action": request["action"],
             "state": state, "detail": detail}, ensure_ascii=False, sort_keys=True) + "\n")
        return state

    def _core(self) -> dict | None:
        """CORE's face hand-over with D-546's recovery hold: an e-stop clears ``recovery`` at
        once; a phase that just ended is held 1.5 s as ``return`` (lamp and LCD, no beep)."""
        core = self._read_core()
        if core is None:
            return None
        now = self._clock()
        phase = core.get("recovery")
        if core.get("estop") is not False:
            self._held = None
            return {**core, "recovery": None} if phase else core
        if phase:
            self._held = (phase, now)
        elif self._held and now - self._held[1] < RECOVERY_HOLD_S:
            return {**core, "recovery": "return" if self._held[0] == "retrace" else self._held[0]}
        else:
            self._held = None
        return core

    def _read_core(self) -> dict | None:
        """CORE's face hand-over, strictly read; None when missing, stale or not CORE's."""
        if face_screen is None:
            return None
        wall = self._wall()
        now = datetime.fromtimestamp(wall, timezone.utc)
        core = face_screen.read_face_inputs(str(self.root / FACE_INPUTS), now, owner_uid=self._core_owner)
        if core is not None:
            self._last_core = core
            return core
        # One unreadable poll (a write in flight, a short read) is not a dead CORE:
        # keep the last good hand-over until it is FACE_INPUTS_FRESH_S old.
        last = self._last_core
        if last is not None and wall - last["written_ts"] <= face_screen.FACE_INPUTS_FRESH_S:
            return last
        self._last_core = None
        return None

    def screen_of(self, view: dict, now: float) -> dict | None:
        """D-433: the situation table's answer for this poll (None on a release without it)."""
        if face_screen is None or robot_state is None:
            return None
        core = self._core()
        mode = core.get("robot_mode") if core else None
        if mode != self._mode:  # the drive card's cadence starts with each operating mode
            self._mode = mode
            self._drive_since = now if mode in robot_state.OPERATING_MODES else None
        login = "code" if view.get("login_code") else ("burned" if view.get("login_burned") else None)
        # D-483: a release without the reader has no peer row in its table either.
        extra = {}
        if hasattr(face_screen, "read_peer_approval"):
            extra["peer"] = face_screen.read_peer_approval(
                str(self.root / PEER_APPROVAL), datetime.fromtimestamp(self._wall(), timezone.utc),
                owner_uid=self._core_owner)
        quality = core.get("camera_quality") if core else None
        expires = core.get("camera_quality_until") if core else None
        fresh = quality is not None and expires is not None and self._wall() <= expires
        if not self._low_light_enabled or not fresh or quality.get("reason") == "overexposed":
            self._light_session = False
        elif quality.get("valid") is False and quality.get("reason") == "low_light":
            self._light_session = True
        screen = face_screen.screen_for(
            stage=view["stage"], state=self.robot_state_of(view), todo=view.get("todo"),
            ap_mode=(view.get("network") or {}).get("mode") == "ap", login=login, core=core,
            update=read_update(self.root, self._wall()),
            test=self._testing if now < self._testing_until else None,
            shutting_down=self.shutting_down, drive_since=self._drive_since, now=now,
            light_assist=self._light_session, **extra)
        if screen["kind"] != "light":
            self._light_session = False
        return screen

    def _lcd_call(self, name: str, *args) -> None:
        action = getattr(self.lcd, name, None)
        if action is not None:
            action(*args)

    def _power(self, screen: dict | None) -> None:
        """Panel sleep and backlight follow the table (D-385 4: standby is dark)."""
        if self.lcd is None:
            return
        awake = screen["awake"] if screen else True
        backlight = screen["backlight"] if screen else 100
        if awake != self._awake:
            self._lcd_call("wake" if awake else "sleep")
            self._awake = awake
            if awake:
                self._drawn = None  # redraw what the sleeping panel stopped showing
        if backlight != self._backlight:
            self._lcd_call("set_backlight", backlight)
            self._backlight = backlight

    def step(self) -> bool:
        """True when the LCD was redrawn."""
        now = self._clock()
        if self.shutting_down:
            # Review LOW: the last poll only draws the shutdown card — no battery read,
            # no sound, no lamp, no handed-over test on the way out.
            return self._draw_shutdown(now)
        if self._battery_due is None or now >= self._battery_due:
            self._battery_value = self._battery.read()
            self.battery_reads += 1
            self._battery_due = now + self._battery_interval
        view = read_view(self.root, self._battery_value)
        # D-385: 기다리는 동안 무대 제목이 1 fps 로 숨쉰다 — 끝난 상태는 고요히 그대로.
        if str(view["stage"]).split(":", 1)[0] in ("BOOTING", "PROVISIONED"):
            view["frame"] = int(now) % 2
        state = self.robot_state_of(view)
        if state != self._state:
            self._state = state
        core = self._core()
        screen = self.screen = self.screen_of(view, now)
        pres = self._present(view, state, core, screen)
        pattern = pres.lamp
        if self._lamp is not None:
            # D-380: a mode change switches the pattern without a sound; show() is
            # idempotent, so an unchanged pattern costs nothing.
            self._lamp.show(pattern)
            self._lamp.poll()
        if self.handle_test() is not None:
            screen = self.screen = self.screen_of(view, now)
        self._power(screen)
        kind = screen["kind"] if screen else "status"
        redrawn = False
        bar = pres.bar  # None without the presentation record (a mixed install)
        if bar is not None and view.get("dev_mode"):  # D-548: DEV on every face frame and card bar
            bar = (bar[0], f"DEV {bar[1]}" if bar[1] else "DEV MODE", *bar[2:])
        if kind == "face" and screen["overlay"] is None:
            # The face plays from tick(); the status bar rides every frame.
            self.animating = bar
            self._drawn = None
        else:
            self.animating = None
            if kind == "sleep":
                self._drawn = "sleep"
            else:
                card = dict(view)
                if screen is not None:
                    card["screen"] = screen
                    if kind == "face":
                        card["bar"] = bar[1:] if bar is not None else None
                    if screen.get("line"):
                        card["state_line"] = screen["line"]  # D-433 row 7: CORE not responding
                    if kind == "update":
                        card["frame"] = int(now) % 2
                key = json.dumps(card, sort_keys=True)
                if key != self._drawn and self.lcd is not None:
                    try:
                        self.lcd.img_show(self._render(card))
                    except Exception:
                        # A broken LCD must not swallow the entry alarm.
                        self._announce(pres.sound, now)
                        raise
                    self._drawn = key
                    self.draws += 1
                    redrawn = True
        # A synchronous buzzer pattern can last hundreds of milliseconds. Show
        # the lamp and any status card first, especially on emergency entry.
        self._announce(pres.sound, now)
        self._reverse_alarm(pres.reversing, now)
        return redrawn

    def _reverse_alarm(self, reversing: bool, now: float) -> None:
        """D-546: one reversing beep per BUZZER_REVERSE_S while ``Presentation.reversing``; silent otherwise."""
        if not reversing:
            self._reversed_at = None
        elif self._reversed_at is None or now - self._reversed_at >= BUZZER_REVERSE_S:
            self._reversed_at = now
            self._buzzer.announce("reverse")

    def _draw_shutdown(self, now: float) -> bool:
        view = read_view(self.root, self._battery_value)
        screen = face_screen.screen_for(shutting_down=True) if face_screen is not None else None
        self.animating = None
        if screen is None or self.lcd is None:
            return False
        self._power(screen)
        card = {**view, "screen": screen,
                "shutdown_title": ("Shutting down" if (self.root / SHUTDOWN_MARK).exists()
                                   else "Display restarting")}
        self.lcd.img_show(self._render(card))
        self.draws += 1
        return True

    def tick(self) -> bool:
        """Push the next face frame while the face owns the screen. True when one was drawn."""
        if self.animating is None or self.lcd is None or self._faces is None:
            return False
        self._ticks += 1
        if self._backlight < 100 and self._ticks % 2:
            return False  # D-185: the dimmed (idle) face plays at half rate
        face, *bar = self.animating
        frame = self._faces.next(face)
        if frame is None:
            return False
        if self._strip is not None:
            frame = self._strip(frame, *bar)
        self.lcd.show_panel(frame)
        self.frames += 1
        return True


def chip_label(path: str = GPIOCHIP) -> str | None:
    """The kernel label of a GPIO chip (GPIO_GET_CHIPINFO_IOCTL), or None."""
    import fcntl
    import struct

    info = bytearray(68)  # struct gpiochip_info: name[32], label[32], u32 lines
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
    except OSError:
        return None
    try:
        fcntl.ioctl(descriptor, 0x8044B401, info)
    except OSError:
        return None
    finally:
        os.close(descriptor)
    return struct.unpack_from("32s", info, 32)[0].split(b"\0", 1)[0].decode("ascii", "replace")


def open_lcd(factory: Callable[[], object], label: Callable[[], str | None], log: Log,
             sleep: Callable[[float], None], cleanup: Callable[[], None] = lambda: None,
             attempts: int = LCD_ATTEMPTS):
    """The LCD, or None after ``attempts`` tries; the first failure and the give-up are logged.

    The GPIO chip label is read on every attempt, before the panel is touched:
    unreadable (udev race, ioctl error) is retried like a failed open and never
    driven blind; readable but not RP1 is final.
    """
    for attempt in range(1, attempts + 1):
        found = label()
        if found is not None and found != RP1_LABEL:
            log.once("lcd", f"{GPIOCHIP} is {found!r}, not the RP1 header ({RP1_LABEL}); LCD not driven")
            return None
        if found is None:
            log.once("lcd-label", f"cannot read the {GPIOCHIP} label yet; retrying")
        else:
            try:
                return factory()
            except Exception as exc:  # noqa: BLE001 - spidev/GPIO raise several kinds
                log.once("lcd", f"LCD unavailable ({type(exc).__name__}: {exc}); retrying")
                try:
                    cleanup()
                except Exception:  # noqa: BLE001
                    pass
        if attempt < attempts:
            sleep(LCD_RETRY_S)
    log.once("lcd-give-up", f"no LCD after {attempts} attempts")
    return None


def _release_modules():
    """The display modules the running release ships (emotion, rosylib)."""
    from emotion import info_screen
    return info_screen


def _gpio_module():
    import RPi.GPIO as gpio  # noqa: N813 - vendor name; rpi-lgpio on the Pi 5
    return gpio


def _lcd_factory():
    from emotion.rosy_lcd import LCD
    return LCD


def card_renderer(info_screen) -> Callable[[dict], object]:
    """D-433: one entry for every card the table can ask for; a release image each.

    ``card["screen"]`` is ``face_screen.screen_for``'s answer (absent on a release
    without it: the boot card, as before).
    """

    def render(card: dict):
        screen = card.get("screen") or {}
        kind = screen.get("kind")
        frame = int(card.get("frame") or 0)
        if kind == "stopped":
            image = info_screen.render_stopped({"device_name": card.get("device_name"),
                                                "cause": screen.get("cause"), "release": screen.get("release")})
        elif kind == "light":
            image = info_screen.render_light_assist()
        elif kind == "update":
            image = info_screen.render_notice("Updating", [f"to {screen.get('release') or '?'}",
                                                           f"now {card.get('release_id') or '?'}"], frame=frame)
        elif kind == "shutdown":
            image = info_screen.render_notice(str(card.get("shutdown_title") or "Shutting down"),
                                              [str(card.get("device_name") or "")])
        elif kind == "face" and screen.get("overlay"):  # a card takes the expression area, under the bar
            image = info_screen.render_overlay(screen["overlay"]["payload"])
        elif screen.get("row") == "peer_request":
            # D-483: ASCII, as every card (the DejaVu card font has no Hangul).
            # One "XXXX  CODE" line per live request, so each requester reads its own code.
            peer = screen.get("peer") or {}
            lines = [f"{r['display_code']}  {r['approval_code']}" for r in peer.get("requests") or []]
            if peer.get("tls_ca_sha256"):
                # What the tablet asks a first-contact requester to compare (its first 16 digits).
                ca = peer["tls_ca_sha256"][:16]
                lines.append("CA " + " ".join(ca[i:i + 4] for i in range(0, 16, 4)))
            image = info_screen.render_notice("Pair request", lines)
        else:
            image = info_screen.render_boot(card, frame=frame)
        if kind == "face" and card.get("bar"):
            band, mask = info_screen.render_bar(*card["bar"][:4])
            image.paste(band, (0, 0), mask)
        return image

    return render


def face_converter(info_screen) -> Callable[[object], object]:
    """A GIF frame (any size) -> panel bytes, the reduction done once per frame (D-185)."""
    from PIL import Image

    def convert(frame):
        landscape = frame.convert("RGB").resize(FACE_SIZE, Image.LANCZOS, reducing_gap=3.0)
        return info_screen.to_panel(info_screen.compose_face(landscape))

    return convert


def bar_painter(info_screen) -> Callable[..., object]:
    """Lay the status bar over a panel frame; the bar and its mask are made once per content."""
    from PIL import Image

    cache: dict[tuple, tuple] = {}

    def paint(frame, text: str, level: str, percent=None, charging=None):
        key = (text, level, percent, charging)
        if key not in cache:
            band, mask = info_screen.render_bar(text, level, percent, charging)
            cache.clear()  # one bar at a time
            cache[key] = (info_screen.to_panel(band),
                          info_screen.to_panel(Image.merge("RGB", (mask, mask, mask)))[..., 0] != 0)
        panel, where = cache[key]
        out = frame.copy()
        out[where] = panel[where]
        return out

    return paint


def core_owner(log: Log) -> int | None:
    """rosy-core's uid: face-inputs.json from anyone else is not CORE's (D-433 decision 3)."""
    try:
        import pwd
        return pwd.getpwnam(CORE_USER).pw_uid
    except (ImportError, KeyError):
        log.once("core-user", f"no {CORE_USER} account; face-inputs.json owner not checked")
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path("/"))
    args = parser.parse_args(argv)
    log = Log()
    stop = {"now": False}

    def _stop(_signum, _frame):
        stop["now"] = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    info_screen = _release_modules()
    try:
        from rosylib import Battery
        from rosylib.battery import voltage_to_percent
        battery = BatteryReader(Battery, voltage_to_percent, log)
    except ImportError as exc:
        log.once("battery-import", f"rosylib unavailable ({exc}); no battery on the card")
        battery = BatteryReader(None, float, log)

    enabled, pin = buzzer_settings(dict(os.environ), log)
    panel = (args.root / SPIDEV).exists()
    if not panel:
        log.once("no-panel", f"no /{SPIDEV}: this board has no SPI panel")
    gpio = None
    lcd = None
    if panel or enabled:
        try:
            gpio = _gpio_module()
        except (ImportError, RuntimeError) as exc:
            log.once("gpio-import", f"RPi.GPIO (rpi-lgpio) unavailable: {exc}")
            return 1
    if panel:
        try:
            lcd_factory = _lcd_factory()
        except (ImportError, RuntimeError) as exc:
            log.once("lcd-import", f"LCD libraries unavailable: {exc}")
            return 1
        lcd = open_lcd(lcd_factory, chip_label, log, time.sleep, cleanup=gpio.cleanup)
        if lcd is None:
            return 1  # the panel is there and was not driven: a fault, not a quiet idle
    buzzer = Buzzer(gpio, pin, enabled, time.sleep)
    lamp = Lamp(args.root, lamp_enabled(dict(os.environ), log), log)
    if lcd is None and not buzzer.enabled and not lamp.available():
        log.once("idle", "no LCD, the buzzer is off and no lamp; nothing to show")
        return 0

    from PIL import Image

    faces = FaceFrames(args.root / FACE_DIR, opener=Image.open, convert=face_converter(info_screen), log=log)
    display = FaceDisplay(args.root, lcd=lcd, render=card_renderer(info_screen), battery=battery,
                          buzzer=buzzer, clock=time.monotonic, lamp=lamp, faces=faces,
                          strip=bar_painter(info_screen), core_owner=core_owner(log),
                          low_light_assist=rosy_display_env.flag(dict(os.environ), rosy_display_env.LOW_LIGHT_KEY)[0])
    polls_per_step = max(1, round(POLL_S / TICK_S))
    tick = 0
    try:
        while not stop["now"]:
            try:
                if tick % polls_per_step == 0:
                    display.step()
                display.tick()
            except Exception as exc:  # noqa: BLE001 - one bad poll must not end the display
                # The type only: a message could quote what was on the card (the AP key).
                log.once(f"step-{type(exc).__name__}", f"poll failed: {type(exc).__name__}")
            tick += 1
            time.sleep(TICK_S)
        # D-433 row 1: say so before the backlight goes with the process.
        display.shutting_down = True
        try:
            display.step()
        except Exception as exc:  # noqa: BLE001
            log.once(f"stop-{type(exc).__name__}", f"last card failed: {type(exc).__name__}")
    finally:
        battery.close()
        lamp.stop()  # the helper leaves the lamp dark on SIGTERM
        if lcd is not None:
            lcd.close()  # stops the backlight PWM and releases the lines
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
