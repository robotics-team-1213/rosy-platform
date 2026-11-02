"""rosy-face outputs: the log, battery reader, buzzer and WS2812 lamp (D-433; moved out of rosy-face.py by D-766)."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from typing import Callable


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
BUZZER_PATTERNS = {"ready": (1, BUZZER_FREQUENCY_HZ), "failed": (3, BUZZER_FREQUENCY_HZ),
                   "caution": (2, BUZZER_LOW_HZ), "emergency": (4, 2500),
                   "call": (2, BUZZER_CALL_HZ), "reverse": (1, BUZZER_REVERSE_HZ)}
#: D-247 6's buzzer test, when handed over: three 150 ms beeps, like rosy-hw-test.
TEST_BEEPS, TEST_ON_S, TEST_OFF_S = 3, 0.15, 0.15
LAMP_NODE = "dev/ws281x_pwm"
LAMP_CHANNEL = "sys/module/rp1_ws281x_pwm/parameters/pwm_channel"
LAMP_PWM_CHANNEL = "3"  # GPIO19; the default 2 is GPIO18, the LCD backlight
LAMP_HELPER = "opt/rosy/current/install/lib/lamp_control/lamp_pattern"
LAMP_STOP_S = 2.0
LAMP_TEST_S = 10.0
IDENTIFY_MAX_S = 3.5


class Log:
    """stderr lines for the journal; each key is reported once."""

    def __init__(self, write: Callable[[str], None] | None = None) -> None:
        self._write = write or (lambda line: print(line, file=sys.stderr, flush=True))
        self._seen: set[str] = set()

    def once(self, key: str, message: str) -> None:
        if key not in self._seen:
            self._seen.add(key)
            self._write(f"rosy-face: {message}")


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
