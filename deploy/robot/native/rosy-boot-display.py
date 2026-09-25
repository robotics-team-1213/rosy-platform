#!/usr/bin/env python3
"""Show the ROSY boot stage on the Pinky Pro LCD and buzzer (D-190, D-174 T1/T2).

A long-running process, outside CORE (D-161), as the unprivileged user
rosy-display. The ST7789 backlight is a software PWM on GPIO18 that lives only
as long as this process (D-190 S0): a one-shot draw leaves the screen dark.

Inputs, all read-only:

* /run/rosy-boot/boot-status.json - stage, failed unit, name, IPv4, release
  (rosy-boot-status, root);
* /run/rosy-boot/network.json - AP mode, SSID, address (rosy-network, root);
* /run/rosy-boot/ap-display.txt - the AP SSID and key, root:rosy-display 0640,
  written by rosy-network only while the AP is up (D-176). Never logged;
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
  BUZZER_REPEAT_S;
* the WS2812 lamp shows the state's pattern through ``lamp_pattern`` (one
  helper process per pattern, /dev/ws281x_pwm granted to this unit alone),
  and only when the driver runs on PWM0 channel 3 (GPIO19; channel 2 is the
  LCD backlight). Anything missing leaves the lamp out, never the boot;
* the LCD gets the state line and the most urgent todo (ASCII: the card font
  has no Hangul);
* a D-247 buzzer or lamp test that rosy-hw-test hands over while this program
  owns the device is played here (TEST_REQUEST, TEST_RESULT).
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import signal
import sys
import time
import stat
import subprocess
from typing import Callable

sys.dont_write_bytecode = True
# The shared switch parser (rosy_display_env.py) sits beside this program.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import rosy_display_env  # noqa: E402

try:  # the release's rule table (D-260); an older release has none
    from core_common import robot_state
except ImportError:
    robot_state = None

STATUS_DIR = "run/rosy-boot"
LOGIN_CODE = re.compile(r"^[23456789ABCDEFGHJKMNPQRSTUVWXYZ]{4}-[23456789ABCDEFGHJKMNPQRSTUVWXYZ]{4}$")
LOGIN_ROLES = frozenset({"viewer", "operator", "administrator"})
POLL_S = 1.0
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
#: D-260 2, per sound: (beeps, frequency). Ready and held ready share one sound.
BUZZER_PATTERNS = {"ready": (1, BUZZER_FREQUENCY_HZ), "failed": (3, BUZZER_FREQUENCY_HZ),
                   "caution": (2, BUZZER_LOW_HZ)}
#: Caution again inside this window stays silent (a battery near the threshold). Ready and
#: failed always sound on a real transition (review L2): they are the news a person waits for.
BUZZER_REPEAT_S = 300.0
REPEAT_LIMITED = frozenset({"caution"})
#: D-247 6's buzzer test, when handed over: three 150 ms beeps, like rosy-hw-test.
TEST_BEEPS, TEST_ON_S, TEST_OFF_S = 3, 0.15, 0.15
#: robot state -> sound; booting is silent.
SOUNDS = {"ready": "ready", "ready_held": "ready", "failed": "failed", "caution": "caution"}
#: robot state -> lamp_pattern argument (D-260 3).
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
TEST_ACTIONS = ("buzzer", "lamp")
TEST_REQUEST_MAX_AGE_S = 30.0
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
            self._write(f"rosy-boot-display: {message}")


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
                                  failed_unit=view["failed_unit"])
    todos = result["todos"]
    return {"robot_state": result["state"], "state_line": robot_state.state_line(result, lcd=True),
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
            self._sleep(on_s)
            self._pwm.stop()
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

    def available(self) -> bool:
        if not self.enabled:
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
    if not -5.0 <= now - float(requested) <= TEST_REQUEST_MAX_AGE_S:
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


class BootDisplay:
    """One poll: read the view, redraw the LCD when it changed, sound and light a new state."""

    def __init__(self, root: Path, *, lcd, render: Callable[[dict], object], battery: BatteryReader,
                 buzzer: Buzzer, clock: Callable[[], float], lamp: Lamp | None = None,
                 wall: Callable[[], float] = time.time,
                 battery_interval: float = BATTERY_INTERVAL_S) -> None:
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
        self._tested: str | None = None
        self.draws = 0
        self.battery_reads = 0

    @staticmethod
    def robot_state_of(view: dict) -> str:
        """The rule table's state, or the stage alone on a release without the table."""
        if view.get("robot_state"):
            return str(view["robot_state"])
        kind = str(view["stage"]).split(":", 1)[0]
        return {"CORE_READY": "ready", "FAILED": "failed"}.get(kind, "booting")

    def _announce(self, state: str, now: float) -> None:
        sound = SOUNDS.get(state)
        # Ready and held ready are one sound: moving between them is not a new sound.
        previous, self._sound = self._sound, sound
        if sound is None or sound == previous:
            return
        last = self._sounded.get(sound)
        if sound in REPEAT_LIMITED and last is not None and now - last < BUZZER_REPEAT_S:
            return
        self._sounded[sound] = now
        self._buzzer.announce(sound)

    def handle_test(self) -> str | None:
        """Play a D-247 test rosy-hw-test handed over; each request id once. The state played, or None."""
        request = read_test_request(self.root / TEST_REQUEST, self._wall())
        if request is None or request["request_id"] == self._tested:
            return None
        self._tested = request["request_id"]
        if request["action"] == "buzzer":
            state, detail = self._buzzer.test()
        elif self._lamp is not None:
            state, detail = self._lamp.test()
        else:
            state, detail = "unavailable", "부팅 표시에 램프가 없음"
        write_test_result(self.root / TEST_RESULT, json.dumps(
            {"schema": 1, "request_id": request["request_id"], "action": request["action"],
             "state": state, "detail": detail}, ensure_ascii=False, sort_keys=True) + "\n")
        return state

    def step(self) -> bool:
        """True when the LCD was redrawn."""
        now = self._clock()
        if self._battery_due is None or now >= self._battery_due:
            self._battery_value = self._battery.read()
            self.battery_reads += 1
            self._battery_due = now + self._battery_interval
        view = read_view(self.root, self._battery_value)
        state = self.robot_state_of(view)
        if state != self._state:
            self._state = state
            if self._lamp is not None:
                self._lamp.show(LAMP_PATTERNS.get(state))
            self._announce(state, now)
        if self._lamp is not None:
            self._lamp.poll()
        self.handle_test()
        key = json.dumps(view, sort_keys=True)
        if key == self._drawn or self.lcd is None:
            return False
        self.lcd.img_show(self._render(view))
        self._drawn = key
        self.draws += 1
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

    display = BootDisplay(args.root, lcd=lcd, render=info_screen.render_boot, battery=battery,
                          buzzer=buzzer, clock=time.monotonic, lamp=lamp)
    try:
        while not stop["now"]:
            try:
                display.step()
            except Exception as exc:  # noqa: BLE001 - one bad poll must not end the display
                # The type only: a message could quote what was on the card (the AP key).
                log.once(f"step-{type(exc).__name__}", f"poll failed: {type(exc).__name__}")
            time.sleep(POLL_S)
    finally:
        battery.close()
        lamp.stop()  # the helper leaves the lamp dark on SIGTERM
        if lcd is not None:
            lcd.close()  # stops the backlight PWM and releases the lines
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
