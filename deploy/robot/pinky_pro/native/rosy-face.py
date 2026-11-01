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
import os
import signal
import subprocess  # noqa: F401 - tests reach it as rosy-face.subprocess
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True
# The shared switch parser (rosy_display_env.py) and the rosy_face_* modules sit beside this program.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import rosy_display_env  # noqa: E402
from face_card_renderer import card_renderer  # noqa: E402

from rosy_face_parts import (  # noqa: E402, F401
    BUZZER_CALL_HZ, BUZZER_DUTY, BUZZER_FREQUENCY_HZ, BUZZER_LOW_HZ, BUZZER_OFF_S, BUZZER_ON_S,
    BUZZER_PATTERNS, BUZZER_REVERSE_HZ, BatteryReader, Buzzer, IDENTIFY_MAX_S, LAMP_CHANNEL,
    LAMP_HELPER, LAMP_NODE, LAMP_PWM_CHANNEL, LAMP_STOP_S, LAMP_TEST_S, Lamp, Log, TEST_BEEPS,
    TEST_OFF_S, TEST_ON_S, _spawn_helper,
)
from rosy_face_inputs import (  # noqa: E402, F401
    BUZZER_DEFAULT_LINE, BUZZER_LINES, CORE_USER, FACE_LOAD_SKIP, FACE_SIZE, FaceFrames,
    GPIOCHIP, IDENTIFY_REQUEST_MAX_AGE_S, LCD_ATTEMPTS, LCD_RETRY_S, MAX_TEST_REQUEST_BYTES,
    RELEASE_ID, RP1_LABEL, TEST_ACTIONS, TEST_REQUEST_ID, TEST_REQUEST_MAX_AGE_S,
    UPDATE_DISPLAY, UPDATE_MAX_AGE_S, bar_painter, buzzer_settings, chip_label, core_owner,
    face_converter, lamp_enabled, open_lcd, read_test_request, read_update, write_test_result,
)
from rosy_face_display import (  # noqa: E402, F401
    BATTERY_INTERVAL_S, BUZZER_REPEAT_S, BUZZER_REVERSE_S, CAUTION_DEBOUNCE_S, DEV_MODE_FILE,
    FACE_INPUTS, FaceDisplay, IDENTIFY_OVER, LAMP_PATTERNS, LOGIN_CODE, LOGIN_ROLES,
    PEER_APPROVAL, RECOVERY_HOLD_S, REPEAT_LIMITED, SHUTDOWN_MARK, SOUNDS, STATUS_DIR,
    TEST_REQUEST, TEST_RESULT, _login_view, _read_json, _state_view, read_view, robot_state,
    face_screen, presentation,
)

POLL_S = 0.5  # D-433: the files and the situation table; face frames tick faster
TICK_S = 0.1  # face frames, 10 fps (5 fps at the idle backlight)
#: The emotion GIFs the running release ships (share/emotion/emotion/<name>.gif).
FACE_DIR = "opt/rosy/current/install/share/emotion/emotion"
SPIDEV = "dev/spidev0.0"


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
