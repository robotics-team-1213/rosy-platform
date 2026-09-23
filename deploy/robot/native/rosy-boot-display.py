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
* the battery ADC on /dev/i2c-1 through ``rosylib.Battery``, which holds the
  same flock as every other Rosy reader of 0x08 (D-192), so it is read
  directly whether rosy-io runs or not.

It polls the files every second and redraws only when what it would draw
changes. The battery is refreshed every BATTERY_INTERVAL_S. A missing LCD, SPI
bus, GPIO chip or battery bus is logged once and never crash-loops the unit.
The buzzer (BCM 22 on sibling boards, unconfirmed on the Pro) stays off until
a person confirms it on the device and sets ROSY_BUZZER_ENABLED=true.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import sys
import time
from typing import Callable

sys.dont_write_bytecode = True

STATUS_DIR = "run/rosy-boot"
POLL_S = 1.0
BATTERY_INTERVAL_S = 15.0
LCD_ATTEMPTS = 6  # udev may still be applying the device groups at start
LCD_RETRY_S = 5.0
RP1_LABEL = "pinctrl-rp1"
GPIOCHIP = "/dev/gpiochip4"
BUZZER_PATTERNS = {"CORE_READY": 1, "FAILED": 3}
BUZZER_FREQUENCY_HZ = 2000
BUZZER_DUTY = 10  # percent; a passive piezo is quiet at a low duty cycle
BUZZER_ON_S = 0.08
BUZZER_OFF_S = 0.12


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
    return view


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
    """Short, quiet beeps on stage changes: once for CORE_READY, three times for FAILED."""

    def __init__(self, gpio, pin: int, enabled: bool, sleep: Callable[[float], None]) -> None:
        self._gpio = gpio
        self._pin = pin
        self.enabled = enabled and gpio is not None
        self._sleep = sleep
        self._pwm = None

    def announce(self, stage_kind: str) -> int:
        """Beep the pattern for ``stage_kind``; the number of beeps."""
        count = BUZZER_PATTERNS.get(stage_kind, 0)
        if not self.enabled or not count:
            return 0
        if self._pwm is None:
            # The LCD sets BCM mode too; set it here for a display without an LCD.
            self._gpio.setwarnings(False)
            self._gpio.setmode(self._gpio.BCM)
            self._gpio.setup(self._pin, self._gpio.OUT)
            self._pwm = self._gpio.PWM(self._pin, BUZZER_FREQUENCY_HZ)
        for index in range(count):
            self._pwm.start(BUZZER_DUTY)
            self._sleep(BUZZER_ON_S)
            self._pwm.stop()
            if index + 1 < count:
                self._sleep(BUZZER_OFF_S)
        return count


def buzzer_settings(environ: dict[str, str], log: Log) -> tuple[bool, int]:
    """ROSY_BUZZER_ENABLED (exactly true/false, default false) and ROSY_BUZZER_PIN (BCM)."""
    enabled_text = environ.get("ROSY_BUZZER_ENABLED", "false")
    if enabled_text not in {"true", "false"}:
        log.once("buzzer-config", f"ROSY_BUZZER_ENABLED must be true or false, got {enabled_text!r}; buzzer off")
        enabled_text = "false"
    pin_text = environ.get("ROSY_BUZZER_PIN", "22")
    if not pin_text.isdigit() or not 2 <= int(pin_text) <= 27 or int(pin_text) in {18, 25, 27}:
        log.once("buzzer-config", f"ROSY_BUZZER_PIN {pin_text!r} is not a free header BCM line; buzzer off")
        return False, 22
    return enabled_text == "true", int(pin_text)


class BootDisplay:
    """One poll: read the view, redraw the LCD when it changed, beep on a new stage."""

    def __init__(self, root: Path, *, lcd, render: Callable[[dict], object], battery: BatteryReader,
                 buzzer: Buzzer, clock: Callable[[], float],
                 battery_interval: float = BATTERY_INTERVAL_S) -> None:
        self.root = root
        self.lcd = lcd
        self._render = render
        self._battery = battery
        self._buzzer = buzzer
        self._clock = clock
        self._battery_interval = battery_interval
        self._battery_due: float | None = None
        self._battery_value: tuple[float, float] | None = None
        self._drawn: str | None = None
        self._stage_kind: str | None = None
        self.draws = 0
        self.battery_reads = 0

    def step(self) -> bool:
        """True when the LCD was redrawn."""
        now = self._clock()
        if self._battery_due is None or now >= self._battery_due:
            self._battery_value = self._battery.read()
            self.battery_reads += 1
            self._battery_due = now + self._battery_interval
        view = read_view(self.root, self._battery_value)
        kind = str(view["stage"]).split(":", 1)[0]
        if kind != self._stage_kind:
            self._stage_kind = kind
            self._buzzer.announce(kind)
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
    """The LCD, or None after ``attempts`` tries; the first failure and the give-up are logged."""
    found = label()
    if found is not None and found != RP1_LABEL:
        log.once("lcd", f"{GPIOCHIP} is {found!r}, not the RP1 header ({RP1_LABEL}); LCD not driven")
        return None
    for attempt in range(1, attempts + 1):
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
    log.once("lcd-give-up", f"no LCD after {attempts} attempts; running without it")
    return None


def _release_modules():
    """The display modules the running release ships (emotion, rosylib)."""
    from emotion import info_screen
    return info_screen


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

    gpio = None
    lcd = None
    try:
        import RPi.GPIO as gpio  # noqa: N813 - vendor name; rpi-lgpio on the Pi 5
        from emotion.rosy_lcd import LCD
        lcd = open_lcd(LCD, chip_label, log, time.sleep, cleanup=gpio.cleanup)
    except (ImportError, RuntimeError) as exc:
        log.once("lcd", f"LCD libraries unavailable ({exc}); running without the LCD")
    enabled, pin = buzzer_settings(dict(os.environ), log)
    buzzer = Buzzer(gpio, pin, enabled, time.sleep)
    if lcd is None and not buzzer.enabled:
        log.once("idle", "no LCD and the buzzer is off; nothing to show")
        return 0

    display = BootDisplay(args.root, lcd=lcd, render=info_screen.render_boot, battery=battery,
                          buzzer=buzzer, clock=time.monotonic)
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
        if lcd is not None:
            lcd.close()  # stops the backlight PWM and releases the lines
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
