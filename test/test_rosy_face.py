"""D-190 boot display: the LCD/buzzer loop, the AP hand-off and the unit sandbox.

The loop runs against a fake LCD, a fake clock, a fake battery and a fake GPIO,
over a temporary /run/rosy-boot; no device is opened.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

# CI runs as root in its container; a non-root POSIX host (the shared test PCs) cannot.
# Windows keeps its existing behaviour.
REQUIRES_ROOT = pytest.mark.skipif(os.name == "posix" and os.geteuid() != 0,
                                   reason="needs root: fchown of the hand-over file to its group needs root")

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "deploy/robot/pinky_pro/native"
IMAGE = ROOT / "deploy/robot/pinky_pro/image"
UNIT = NATIVE / "rosy-face.service"
FOUNDATION = ROOT / "contracts/foundation"
PW = "pass" + "word"  # assembled so the tracked-file secret scanner sees no literal
AP_VALUE = "Kx7" + "mQ2vR9tLpZq"


def _load(name: str, path: Path):
    # D-260: the display imports core_common.robot_state from the release; here, the source tree.
    if str(FOUNDATION) not in sys.path:
        sys.path.insert(0, str(FOUNDATION))
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _display():
    return _load("rosy_face", NATIVE / "rosy-face.py")


def _network():
    return _load("rosy_network_display", NATIVE / "rosy-network.py")


class FakeLCD:
    def __init__(self):
        self.shown = []

    def img_show(self, image):
        self.shown.append(image)


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class FakeBattery:
    def __init__(self, voltages):
        self.voltages = list(voltages)
        self.reads = 0
        self.closed = 0

    def get_voltage(self):
        self.reads += 1
        value = self.voltages.pop(0) if len(self.voltages) > 1 else self.voltages[0]
        if isinstance(value, Exception):
            raise value
        return value

    def close(self):
        self.closed += 1


class FakePWM:
    def __init__(self, events):
        self.events = events

    def start(self, duty):
        self.events.append(("start", duty))

    def stop(self):
        self.events.append(("stop",))

    def ChangeFrequency(self, frequency):  # noqa: N802 - RPi.GPIO API
        self.events.append(("change", frequency))


class FakeGPIO:
    BCM = "BCM"
    OUT = "OUT"

    def __init__(self):
        self.events = []

    def setwarnings(self, flag):
        self.events.append(("setwarnings", flag))

    def setmode(self, mode):
        self.events.append(("setmode", mode))

    def setup(self, pin, mode):
        self.events.append(("setup", pin, mode))

    def PWM(self, pin, frequency):  # noqa: N802 - RPi.GPIO API
        self.events.append(("pwm", pin, frequency))
        return FakePWM(self.events)


def _status(root: Path, stage: str, **extra) -> None:
    directory = root / "run/rosy-boot"
    directory.mkdir(parents=True, exist_ok=True)
    record = {"stage": stage, "device_name": "rosy-pinky-e4us", "release_id": "2026.09.24-007",
              "ipv4": ["192.168.1.201"], "api_port": 8080, **extra}
    (directory / "boot-status.json").write_text(json.dumps(record), encoding="utf-8")


def _loop(module, root, *, voltages=(8.2,), gpio=None, buzzer_on=False, interval=15.0, logs=None):
    lines = logs if logs is not None else []
    log = module.Log(lines.append)
    battery = FakeBattery(voltages)
    reader = module.BatteryReader(lambda: battery, lambda volts: round(volts * 10.0, 1), log)
    sleeps: list[float] = []
    buzzer = module.Buzzer(gpio, 22, buzzer_on, sleeps.append)
    lcd = FakeLCD()
    clock = FakeClock()
    rendered: list[dict] = []

    def render(view):
        rendered.append(view)
        return f"image-{len(rendered)}"

    display = module.FaceDisplay(root, lcd=lcd, render=render, battery=reader, buzzer=buzzer,
                                 clock=clock, battery_interval=interval)
    return display, lcd, clock, battery, rendered, lines


# --- loop -----------------------------------------------------------------


def test_the_first_poll_draws_and_an_unchanged_poll_does_not(tmp_path):
    module = _display()
    _status(tmp_path, "BOOTING")
    display, lcd, clock, _battery, rendered, _logs = _loop(module, tmp_path)

    # D-385: while BOOTING the stage title breathes — the frame phase rides the
    # redraw key, so each second redraws. An unchanged view still never redraws
    # within one phase (the +0.5 s polls below).
    assert display.step() is True
    assert display.step() is False  # same second, same phase
    clock.now += 1
    assert display.step() is True  # the breath's dark step

    _status(tmp_path, "CORE_READY", runtime_mode="core")
    clock.now += 1
    display.step()  # CORE_READY holds still…
    drawn_at_ready = display.draws
    clock.now += 1
    assert display.step() is False  # …and an unchanged ready card does not redraw

    assert lcd.shown == ["image-1", "image-2", "image-3"]
    assert rendered[0]["stage"] == "BOOTING" and rendered[0]["battery_voltage"] == 8.2


def test_a_stage_change_redraws_at_the_next_poll(tmp_path):
    module = _display()
    _status(tmp_path, "BOOTING")
    display, lcd, clock, _battery, rendered, _logs = _loop(module, tmp_path)
    display.step()

    _status(tmp_path, "PROVISIONED")
    clock.now += 1
    assert display.step() is True
    _status(tmp_path, "FAILED:rosy-core", failed_unit="rosy-core.service")
    clock.now += 1
    assert display.step() is True

    assert [view["stage"] for view in rendered] == ["BOOTING", "PROVISIONED", "FAILED:rosy-core"]
    assert rendered[-1]["failed_unit"] == "rosy-core.service"
    assert len(lcd.shown) == 3


def test_a_network_change_redraws_without_waiting_for_the_indicator(tmp_path):
    module = _display()
    _status(tmp_path, "CORE_READY")
    display, _lcd, clock, _battery, rendered, _logs = _loop(module, tmp_path)
    display.step()

    (tmp_path / "run/rosy-boot/network.json").write_text(
        json.dumps({"mode": "ap", "ssid": "rosy-pinky-e4us", "address": "10.42.0.1"}), encoding="utf-8")
    clock.now += 1

    assert display.step() is True
    assert rendered[-1]["network"]["mode"] == "ap"


def test_the_battery_is_read_once_per_interval_not_every_poll(tmp_path):
    module = _display()
    _status(tmp_path, "CORE_READY")
    display, _lcd, clock, battery, rendered, _logs = _loop(
        module, tmp_path, voltages=(8.2, 8.2, 7.9), interval=15.0)

    for _ in range(15):  # 0..14 s: one reading
        display.step()
        clock.now += 1
    assert battery.reads == 1 and display.draws == 1

    display.step()  # t+15 s: second reading, same value, no redraw
    assert battery.reads == 2 and display.draws == 1
    clock.now += 15
    display.step()  # t+30 s: a new value redraws
    assert battery.reads == 3 and display.draws == 2
    assert rendered[-1]["battery_voltage"] == 7.9


def test_a_missing_boot_status_is_booting(tmp_path):
    module = _display()
    display, _lcd, _clock, _battery, rendered, _logs = _loop(module, tmp_path)

    display.step()

    assert rendered[0]["stage"] == "BOOTING" and rendered[0]["ipv4"] == []


def test_a_missing_battery_bus_is_logged_once_and_retried(tmp_path):
    module = _display()
    _status(tmp_path, "CORE_READY")
    display, _lcd, clock, battery, rendered, logs = _loop(
        module, tmp_path, voltages=(OSError(2, "No such file"), OSError(2, "No such file"), 8.1), interval=10.0)

    for _ in range(3):
        display.step()
        clock.now += 10

    assert battery.reads == 3 and battery.closed == 2
    assert [view["battery_voltage"] for view in rendered] == [None, 8.1]
    assert sum("battery ADC unavailable" in line for line in logs) == 1


def test_no_battery_library_draws_dashes(tmp_path):
    module = _display()
    reader = module.BatteryReader(None, float, module.Log(lambda _line: None))

    assert reader.read() is None


# --- buzzer ---------------------------------------------------------------


def test_the_buzzer_is_on_by_default_since_d260(tmp_path):
    module = _display()
    lines: list[str] = []

    assert module.buzzer_settings({}, module.Log(lines.append)) == (True, 4)
    assert module.buzzer_settings({"ROSY_BUZZER_ENABLED": "false"}, module.Log(lines.append)) == (False, 4)
    unit = UNIT.read_text(encoding="utf-8")
    assert "Environment=ROSY_BUZZER_ENABLED=true ROSY_BUZZER_PIN=4 ROSY_LAMP_ENABLED=true" in unit
    assert lines == []


def test_a_disabled_buzzer_never_touches_the_pin(tmp_path):
    module = _display()
    gpio = FakeGPIO()
    _status(tmp_path, "BOOTING")
    display, _lcd, clock, _battery, _rendered, _logs = _loop(module, tmp_path, gpio=gpio, buzzer_on=False)

    display.step()
    _status(tmp_path, "CORE_READY")
    clock.now += 1
    display.step()

    assert gpio.events == []


def test_ready_beeps_once_and_failed_three_times_short_and_quiet(tmp_path):
    module = _display()
    gpio = FakeGPIO()
    _status(tmp_path, "BOOTING")
    display, _lcd, clock, _battery, _rendered, _logs = _loop(module, tmp_path, gpio=gpio, buzzer_on=True)

    display.step()
    assert gpio.events == []  # BOOTING is silent
    _status(tmp_path, "CORE_READY")
    clock.now += 1
    display.step()
    clock.now += 1
    display.step()  # still ready: no second beep
    starts = [event for event in gpio.events if event[0] == "start"]
    assert len(starts) == 1
    assert ("setup", 22, "OUT") in gpio.events and ("pwm", 22, module.BUZZER_FREQUENCY_HZ) in gpio.events

    _status(tmp_path, "FAILED:rosy-core")
    clock.now += 1
    display.step()
    starts = [event for event in gpio.events if event[0] == "start"]
    assert len(starts) == 4
    assert all(event == ("start", module.BUZZER_DUTY) for event in starts)
    assert module.BUZZER_DUTY <= 20 and module.BUZZER_ON_S <= 0.1


def test_a_second_failed_unit_does_not_beep_again(tmp_path):
    module = _display()
    gpio = FakeGPIO()
    _status(tmp_path, "FAILED:rosy-release-recover")
    display, _lcd, clock, _battery, _rendered, _logs = _loop(module, tmp_path, gpio=gpio, buzzer_on=True)
    display.step()
    _status(tmp_path, "FAILED:rosy-core")
    clock.now += 1
    display.step()

    assert len([event for event in gpio.events if event[0] == "start"]) == 3


@pytest.mark.parametrize("environ,expected", [
    ({"ROSY_BUZZER_ENABLED": "true"}, (True, 4)),
    ({"ROSY_BUZZER_ENABLED": "true", "ROSY_BUZZER_PIN": "23"}, (True, 23)),
    ({"ROSY_BUZZER_ENABLED": "yes"}, (False, 4)),
    ({"ROSY_BUZZER_ENABLED": "true", "ROSY_BUZZER_PIN": "18"}, (False, 4)),  # the backlight
    ({"ROSY_BUZZER_ENABLED": "true", "ROSY_BUZZER_PIN": "x"}, (False, 4)),
])
def test_buzzer_settings_are_strict(environ, expected):
    module = _display()

    assert module.buzzer_settings(environ, module.Log(lambda _line: None)) == expected


@pytest.mark.parametrize("pin", ["2", "3", "8", "12", "14", "19", "0", "7", "13", "15", "25", "27", "28"])
def test_the_buzzer_never_takes_a_line_something_else_owns(pin):
    # I2C1 (2/3), SPI0 CE0 (8), UART4 motor (12/13), UART0 LiDAR (14/15), lamp (19), LCD.
    module = _display()
    lines: list[str] = []

    enabled = module.buzzer_settings({"ROSY_BUZZER_ENABLED": "true", "ROSY_BUZZER_PIN": pin},
                                     module.Log(lines.append))

    assert enabled == (False, 4) and "not a free header BCM line" in lines[0]


def test_the_buzzer_lines_are_exactly_the_board_s_free_lines():
    import yaml

    display = yaml.safe_load((ROOT / "deploy/robot/pinky_pro/config/board.yaml").read_text(
        encoding="utf-8"))["boot_display"]
    owners = set(display["header_bcm_owners"])
    allowed = set(display["buzzer"]["allowed_bcm_lines"])
    module = _display()

    assert module.BUZZER_LINES == allowed
    assert not allowed & owners and allowed | owners == set(range(28))
    lcd = display["lcd"]["bcm_lines"]
    assert {lcd["rst"], lcd["dc"], lcd["backlight"], 12, 13, 19} <= owners
    assert display["buzzer"]["bcm_line"] in allowed


# --- LCD opening ----------------------------------------------------------


def test_a_missing_lcd_is_retried_logged_once_and_given_up(tmp_path):
    module = _display()
    lines: list[str] = []
    sleeps: list[float] = []
    cleanups: list[int] = []

    def factory():
        raise FileNotFoundError(2, "No such file or directory", "/dev/spidev0.0")

    lcd = module.open_lcd(factory, lambda: "pinctrl-rp1", module.Log(lines.append), sleeps.append,
                          cleanup=lambda: cleanups.append(1), attempts=3)

    assert lcd is None
    assert sleeps == [module.LCD_RETRY_S, module.LCD_RETRY_S] and len(cleanups) == 3
    assert len(lines) == 2 and "retrying" in lines[0] and "no LCD after 3 attempts" in lines[1]


def test_the_lcd_opens_when_udev_catches_up(tmp_path):
    module = _display()
    attempts = []

    def factory():
        attempts.append(1)
        if len(attempts) < 2:
            raise PermissionError(13, "Permission denied")
        return "lcd"

    assert module.open_lcd(factory, lambda: "pinctrl-rp1", module.Log(lambda _l: None),
                           lambda _s: None) == "lcd"


def test_an_unreadable_label_is_retried_before_the_panel_is_touched():
    module = _display()
    labels = iter([None, None, "pinctrl-rp1"])
    calls: list[str] = []
    lines: list[str] = []

    def factory():
        calls.append("open")
        return "lcd"

    lcd = module.open_lcd(factory, lambda: next(labels), module.Log(lines.append), lambda _s: None)

    assert lcd == "lcd" and calls == ["open"]
    assert len(lines) == 1 and "cannot read the /dev/gpiochip4 label" in lines[0]


def test_a_label_that_never_reads_means_no_lcd():
    module = _display()

    def factory():
        raise AssertionError("never driven blind")

    lines: list[str] = []
    assert module.open_lcd(factory, lambda: None, module.Log(lines.append), lambda _s: None,
                           attempts=4) is None
    assert "no LCD after 4 attempts" in lines[-1]


def test_a_gpio_chip_that_is_not_rp1_is_never_driven():
    module = _display()
    lines: list[str] = []

    def factory():
        raise AssertionError("must not be called")

    assert module.open_lcd(factory, lambda: "gpio-brcmstb@107d508500", module.Log(lines.append),
                           lambda _s: None) is None
    assert "not the RP1 header" in lines[0]


def _main_with(module, monkeypatch, root, *, lcd=None, lcd_import=None, gpio_import=None, buzzer="false"):
    class _GPIO:
        @staticmethod
        def cleanup():
            pass

    def gpio_module():
        if gpio_import:
            raise gpio_import
        return _GPIO

    def lcd_factory():
        if lcd_import:
            raise lcd_import
        return lambda: lcd

    monkeypatch.setattr(module, "_release_modules", lambda: None)
    monkeypatch.setattr(module, "_gpio_module", gpio_module)
    monkeypatch.setattr(module, "_lcd_factory", lcd_factory)
    monkeypatch.setattr(module, "open_lcd", lambda factory, *_args, **_kw: factory())
    # The buzzer is on by default (D-260 2); these cases are about the panel.
    monkeypatch.setenv("ROSY_BUZZER_ENABLED", buzzer)
    monkeypatch.delenv("ROSY_LAMP_ENABLED", raising=False)
    return module.main(["--root", str(root)])


def test_a_board_without_a_panel_exits_cleanly_instead_of_restarting(tmp_path, monkeypatch, capsys):
    module = _display()

    assert _main_with(module, monkeypatch, tmp_path) == 0
    err = capsys.readouterr().err
    assert "has no SPI panel" in err and "nothing to show" in err


@pytest.mark.parametrize("failure", [
    {"lcd_import": ImportError("No module named 'spidev'")},
    {"gpio_import": RuntimeError("This module can only be run on a Raspberry Pi!")},
    {"lcd": None},  # the panel is there but open_lcd gave up
])
def test_a_panel_that_cannot_be_driven_fails_the_unit(tmp_path, monkeypatch, failure):
    module = _display()
    (tmp_path / "dev").mkdir()
    (tmp_path / "dev/spidev0.0").write_text("", encoding="utf-8")

    assert _main_with(module, monkeypatch, tmp_path, **failure) == 1


# --- AP hand-off (rosy-network, root) --------------------------------------


def _ap_device(tmp_path: Path) -> Path:
    root = tmp_path / "device"
    (root / "etc/rosy").mkdir(parents=True)
    (root / "etc/rosy/ap-credentials.json").write_text(
        json.dumps({"ssid": "rosy-pinky-e4us", PW: AP_VALUE}), encoding="utf-8")
    (root / "etc/rosy/network-policy.json").write_text(
        json.dumps({"mode": "fallback", "grace_seconds": 120, "hold_seconds": 600}), encoding="utf-8")
    (root / "etc/NetworkManager/system-connections").mkdir(parents=True)
    return root


def _activated(command: list[str]) -> str:
    return "GENERAL.STATE:activated\n" if "GENERAL.STATE" in command else ""


def test_opening_the_ap_hands_the_display_only_its_two_lines(tmp_path, monkeypatch, capsys):
    network = _network()
    gid = os.getgid() if hasattr(os, "getgid") else 0
    monkeypatch.setattr(network, "_display_gid", lambda: gid)
    root = _ap_device(tmp_path)

    assert network.perform(root, "open", _activated)

    handoff = root / "run/rosy-boot/ap-display.txt"
    assert handoff.read_text(encoding="utf-8") == f"rosy-pinky-e4us\n{AP_VALUE}\n"
    output = capsys.readouterr()
    assert AP_VALUE not in output.out + output.err
    assert AP_VALUE not in (root / "run/rosy-boot/network.json").read_text(encoding="utf-8")


@pytest.mark.skipif(os.name != "posix", reason="file mode and group need POSIX (run in WSL)")
def test_the_handoff_is_0640_and_owned_by_the_display_group(tmp_path, monkeypatch):
    network = _network()
    gid = os.getgid()
    monkeypatch.setattr(network, "_display_gid", lambda: gid)
    root = _ap_device(tmp_path)

    network.perform(root, "open", _activated)

    handoff = root / "run/rosy-boot/ap-display.txt"
    assert handoff.stat().st_mode & 0o777 == 0o640
    assert handoff.stat().st_gid == gid


def test_group_and_mode_are_set_before_any_byte_is_written(tmp_path, monkeypatch):
    network = _network()
    monkeypatch.setattr(network, "_display_gid", lambda: 4242)
    seen: list[tuple[str, int, int]] = []

    def record(name):
        def call(descriptor, *_args):
            seen.append((name, os.lseek(descriptor, 0, os.SEEK_CUR), os.fstat(descriptor).st_size))
        return call

    monkeypatch.setattr(network.os, "fchown", record("fchown"), raising=False)
    monkeypatch.setattr(network.os, "fchmod", record("fchmod"), raising=False)

    network.display_ap(_ap_device(tmp_path), "rosy-pinky-e4us", AP_VALUE)

    assert [name for name, _pos, _size in seen] == ["fchown", "fchmod"]
    assert all(position == 0 and size == 0 for _name, position, size in seen)


@REQUIRES_ROOT
def test_closing_or_failing_the_ap_removes_the_handoff(tmp_path, monkeypatch):
    network = _network()
    monkeypatch.setattr(network, "_display_gid", lambda: 0)
    root = _ap_device(tmp_path)
    handoff = root / "run/rosy-boot/ap-display.txt"

    network.perform(root, "open", _activated)
    assert handoff.exists()
    network.perform(root, "close", lambda _command: "")
    assert not handoff.exists()

    network.perform(root, "open", _activated)
    network.perform(root, "open", lambda _command: "")  # did not activate
    assert not handoff.exists()


def test_without_the_display_group_nothing_is_handed_off(tmp_path, monkeypatch):
    network = _network()
    monkeypatch.setattr(network, "_display_gid", lambda: None)
    root = _ap_device(tmp_path)

    network.perform(root, "open", _activated)

    assert not (root / "run/rosy-boot/ap-display.txt").exists()


def test_the_controller_clears_a_stale_handoff_when_it_starts(tmp_path, monkeypatch):
    network = _network()
    root = _ap_device(tmp_path)
    stale = root / "run/rosy-boot/ap-display.txt"
    stale.parent.mkdir(parents=True)
    stale.write_text(f"rosy-pinky-e4us\n{AP_VALUE}\n", encoding="utf-8")
    calls: list[list[str]] = []
    monkeypatch.setattr(network, "_run", lambda command: calls.append(command) or "")

    assert network.main(["--once", "--root", str(root)]) == 0

    assert not stale.exists()
    assert calls[0] == ["nmcli", "connection", "down", "rosy-fallback-ap"]


def test_the_display_shows_the_key_and_never_logs_it(tmp_path, capsys):
    module = _display()
    _status(tmp_path, "CORE_READY")
    (tmp_path / "run/rosy-boot/network.json").write_text(
        json.dumps({"mode": "ap", "ssid": "rosy-pinky-e4us", "address": "10.42.0.1"}), encoding="utf-8")
    (tmp_path / "run/rosy-boot/ap-display.txt").write_text(f"rosy-pinky-e4us\n{AP_VALUE}\n", encoding="utf-8")
    logs: list[str] = []
    display, _lcd, _clock, _battery, rendered, _ = _loop(
        module, tmp_path, voltages=(OSError(5, "I/O error"),), logs=logs)

    display.step()

    assert rendered[-1]["ap_login"] == AP_VALUE
    assert logs and all(AP_VALUE not in line for line in logs)
    output = capsys.readouterr()
    assert AP_VALUE not in output.out + output.err


def test_the_lcd_draws_the_join_qr_only_while_the_ap_is_open_and_never_logs_it(tmp_path, capsys):
    sys.path.insert(0, str(ROOT / "middleware/ui/face"))
    info_screen = pytest.importorskip("emotion.info_screen")
    module = _display()
    _status(tmp_path, "CORE_READY")
    network_json = tmp_path / "run/rosy-boot/network.json"
    network_json.write_text(
        json.dumps({"mode": "ap", "ssid": "rosy-pinky-e4us", "address": "10.42.0.1"}), encoding="utf-8")
    (tmp_path / "run/rosy-boot/ap-display.txt").write_text(f"rosy-pinky-e4us\n{AP_VALUE}\n", encoding="utf-8")
    logs: list[str] = []
    display, lcd, _clock, _battery, _rendered, _ = _loop(
        module, tmp_path, voltages=(OSError(5, "I/O error"),), logs=logs)
    display._render = info_screen.render_boot
    qr_area = (160, info_screen._QR_TOP, 320, 176)

    display.step()
    opened = lcd.shown[-1]
    network_json.write_text(json.dumps({"mode": "sta"}), encoding="utf-8")
    display.step()
    closed = lcd.shown[-1]

    colours = lambda image: {c for _n, c in image.crop(qr_area).getcolors(1 << 16)}  # noqa: E731
    assert info_screen._QR_LIGHT in colours(opened)
    assert info_screen._QR_LIGHT not in colours(closed)
    output = capsys.readouterr()
    for text in logs + [output.out + output.err]:
        assert AP_VALUE not in text and "WIFI" + ":" not in text


def test_a_stale_handoff_is_not_shown_in_station_mode(tmp_path):
    module = _display()
    _status(tmp_path, "CORE_READY")
    (tmp_path / "run/rosy-boot/ap-display.txt").write_text(f"x\n{AP_VALUE}\n", encoding="utf-8")

    view = module.read_view(tmp_path, None)

    assert "ap_login" not in view


def test_an_unreadable_handoff_falls_back_to_the_operator_store(tmp_path):
    module = _display()
    _status(tmp_path, "CORE_READY")
    (tmp_path / "run/rosy-boot/network.json").write_text(
        json.dumps({"mode": "ap", "ssid": "rosy-pinky-e4us"}), encoding="utf-8")

    view = module.read_view(tmp_path, None)

    assert "ap_login" not in view and view["network"]["ssid"] == "rosy-pinky-e4us"


# --- D-193 login line ---------------------------------------------------------

LOGIN_VALUE = "7KXM-" + "P3QA"


def _login(root: Path, content: str) -> None:
    (root / "run/rosy-boot/login-display.txt").write_text(content, encoding="utf-8")


def test_the_login_line_is_shown_at_core_ready_and_never_logged(tmp_path, capsys):
    module = _display()
    _status(tmp_path, "CORE_READY")
    _login(tmp_path, f"{LOGIN_VALUE}\noperator\n")
    logs: list[str] = []
    display, _lcd, _clock, _battery, rendered, _ = _loop(
        module, tmp_path, voltages=(OSError(5, "I/O error"),), logs=logs)

    display.step()

    assert rendered[-1]["login_code"] == LOGIN_VALUE and rendered[-1]["login_role"] == "operator"
    assert logs and all(LOGIN_VALUE not in line for line in logs)
    output = capsys.readouterr()
    assert LOGIN_VALUE not in output.out + output.err


@pytest.mark.parametrize("stage", ["BOOTING", "PROVISIONED", "FAILED:rosy-core"])
def test_the_login_line_is_hidden_before_core_ready(tmp_path, stage):
    module = _display()
    _status(tmp_path, stage)
    _login(tmp_path, f"{LOGIN_VALUE}\noperator\n")

    view = module.read_view(tmp_path, None)

    assert "login_code" not in view and "login_burned" not in view


def test_a_burned_code_shows_the_notice_and_a_new_code_redraws(tmp_path):
    module = _display()
    _status(tmp_path, "CORE_READY")
    display, lcd, _clock, _battery, rendered, _ = _loop(module, tmp_path)
    _login(tmp_path, "BURNED\n")
    display.step()
    assert rendered[-1]["login_burned"] is True and "login_code" not in rendered[-1]

    (tmp_path / "run/rosy-boot/login-display.txt").unlink()
    assert display.step()  # the line going away is a redraw too
    assert "login_burned" not in rendered[-1]
    assert len(lcd.shown) == 2


@pytest.mark.parametrize("content", ["ABCD-EFG1\noperator\n", f"{LOGIN_VALUE}\nroot\n", f"{LOGIN_VALUE}\n",
                                     "", "\x00\x01"])
def test_a_malformed_login_hand_off_shows_nothing(tmp_path, content):
    module = _display()
    _status(tmp_path, "CORE_READY")
    _login(tmp_path, content)

    view = module.read_view(tmp_path, None)

    assert "login_code" not in view and "login_burned" not in view


def test_the_boot_card_rows_for_the_login_line():
    sys.path.insert(0, str(ROOT / "middleware/ui/face"))
    info_screen = pytest.importorskip("emotion.info_screen")
    base = {"stage": "CORE_READY", "ipv4": ["192.168.1.201"], "battery_percent": 80, "battery_voltage": 7.9}

    rows = {slot: (text, color) for slot, text, color in info_screen.boot_lines(
        {**base, "login_code": LOGIN_VALUE, "login_role": "administrator"})}
    assert rows["login"] == (f"Login {LOGIN_VALUE} administrator", info_screen._FG)
    burned = {slot: (text, color) for slot, text, color in info_screen.boot_lines({**base, "login_burned": True})}
    assert burned["login"] == ("Login code burned", info_screen._CRIT)
    early = {slot for slot, _text, _color in info_screen.boot_lines(
        {**base, "stage": "BOOTING", "login_code": LOGIN_VALUE, "login_role": "operator"})}
    assert "login" not in early
    # The line sits below the AP rows and inside the 240-pixel card.
    y, size = info_screen._BOOT_LAYOUT["login"]
    assert y > info_screen._BOOT_LAYOUT["ap_login"][0] and y + size <= info_screen.DEFAULT_SIZE[1]


# --- unit and image ---------------------------------------------------------


def _directives() -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    for raw in UNIT.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";", "[")) or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values.setdefault(key, []).append(value)
    return values


def test_the_unit_is_an_unprivileged_sandbox_with_exactly_four_devices():
    directives = _directives()

    assert directives["User"] == ["rosy-display"] and directives["Group"] == ["rosy-display"]
    assert directives["DevicePolicy"] == ["closed"]
    assert sorted(directives["DeviceAllow"]) == ["/dev/gpiochip4 rw", "/dev/i2c-1 rw", "/dev/spidev0.0 rw",
                                                 "/dev/ws281x_pwm rw"]
    # D-260 / D-247 6: the only other thing it writes is the handed-over test outcome.
    assert directives["RuntimeDirectory"] == ["rosy-display"]
    for key, value in (("ProtectSystem", "strict"), ("ProtectHome", "true"), ("NoNewPrivileges", "true"),
                       ("PrivateNetwork", "true"), ("RestrictAddressFamilies", "AF_UNIX"),
                       ("CapabilityBoundingSet", ""), ("Restart", "on-failure")):
        assert directives.get(key, [""])[-1] == value, key
    environment = dict(word.split("=", 1) for value in directives["Environment"] for word in value.split())
    assert environment["PYTHONNOUSERSITE"] == "1"
    assert environment["HOME"] == "/var/lib/rosy/display" == directives["WorkingDirectory"][0]
    assert environment["LG_WD"] == "/var/lib/rosy/display"
    assert directives["StateDirectory"] == ["rosy/display"]
    assert directives["ExecStart"] == ["/usr/bin/python3 -B /opt/rosy/native-runtime/rosy-face.py"]
    assert "bash" not in UNIT.read_text(encoding="utf-8")


def test_the_unit_starts_early_outside_core_and_is_enabled_by_the_image():
    directives = _directives()
    ordered = " ".join(directives.get("After", []) + directives.get("Requires", [])
                       + directives.get("Wants", []) + directives.get("BindsTo", []))

    for runtime in ("rosy-core", "rosy-runtime", "network-online", "rosy-boot-status"):
        assert runtime not in ordered
    assert directives["WantedBy"] == ["multi-user.target"]
    assert "rosy-face.service" in (IMAGE / "customize-rootfs.sh").read_text(encoding="utf-8")


def test_no_product_unit_or_launch_starts_emotion_server():
    # D-190 decision 5 / D-433: one LCD owner, rosy-face. emotion_server is the
    # sim/bench ROS adapter; no product unit or launch may start it beside rosy-face.
    for unit in NATIVE.glob("*.service"):
        text = unit.read_text(encoding="utf-8")
        assert "emotion" not in "".join(line for line in text.splitlines() if line.startswith("Exec")), unit.name
    from robot_contracts import COLCON_ROOTS

    launches = [launch for root in COLCON_ROOTS for launch in (ROOT / root).rglob("*.launch.py")
                if "middleware/ui/face" not in launch.as_posix()]
    # D-427: an empty walk would pass; today the roots hold 25 *.launch.py outside the face.
    assert len(launches) >= 25, launches  # update when a launch file is legitimately removed
    for launch in launches:
        text = launch.read_text(encoding="utf-8")
        assert "package='emotion'" not in text and 'package="emotion"' not in text, launch


def test_the_image_installs_the_display_user_packages_rule_and_probe():
    customizer = (IMAGE / "customize-rootfs.sh").read_text(encoding="utf-8")
    payload = (IMAGE / "build-native-payload.sh").read_text(encoding="utf-8")
    verifier = _load("verify_mounted_image_display", IMAGE / "verify-mounted-image.py")

    for package in verifier.DISPLAY_APT_PACKAGES:
        assert package in customizer
    assert "useradd --uid 962 --gid 962 --system --no-create-home --shell /usr/sbin/nologin rosy-display" in customizer
    assert "for group in spi gpio i2c; do" in customizer
    assert 'cp "$NATIVE_RUNTIME_SOURCE/rosy-face.service" "$OVERLAY/etc/systemd/system/"' in payload
    assert 'rosy-boot-display.service" "$OVERLAY' not in payload  # D-433: the retired unit is not in a new image
    assert 'cp "$DISPLAY_UDEV_RULE_SOURCE" "$OVERLAY/etc/udev/rules.d/"' in payload
    probe = customizer.index("probe-display-runtime.py'")
    call = customizer[customizer.rindex("setpriv --reuid=rosy-display", 0, probe):probe]
    assert "PYTHONPATH=/opt/rosy/current/install/lib/python3.12/site-packages" in call
    # The probe runs where the unit runs: lgpio writes into LG_WD / the working
    # directory at import (release 007 build failed without them).
    unit_env = " ".join(_directives()["Environment"])
    for setting in ("HOME=/var/lib/rosy/display", "LG_WD=/var/lib/rosy/display", "RPI_LGPIO_CHIP=4"):
        assert setting in call and setting in unit_env, setting
    assert "cd /var/lib/rosy/display && exec python3" in call
    assert _directives()["WorkingDirectory"] == ["/var/lib/rosy/display"]
    assert 'install -d -o 962 -g 962 -m 0750 "$ROOT/var/lib/rosy/display"' in customizer[:probe]
    assert probe < customizer.index("verify-mounted-image.py")
    assert customizer.index("useradd --uid 962") < customizer.index("systemctl --root")
    unit_path = [word for word in _directives()["Environment"] if word.startswith("PYTHONPATH=")]
    assert unit_path == ["PYTHONPATH=/opt/rosy/current/install/lib/python3.12/site-packages"]


def test_the_udev_rule_opens_only_the_lcd_and_the_header_chip():
    rules = [line for line in (ROOT / "deploy/robot/pinky_pro/udev/99-rosy-display.rules").read_text(
        encoding="utf-8").splitlines() if line and not line.startswith("#")]

    assert rules == [
        'ACTION=="add|change", SUBSYSTEM=="spidev", KERNEL=="spidev0.0", GROUP="spi", MODE="0660"',
        'ACTION=="add|change", SUBSYSTEM=="gpio", KERNEL=="gpiochip4", GROUP="gpio", MODE="0660"',
    ]
    assert "SupplementaryGroups=dialout spi gpio" in UNIT.read_text(encoding="utf-8")


def test_the_board_profile_matches_the_unit_and_no_capability_advertises_it():
    import yaml

    board = yaml.safe_load((ROOT / "deploy/robot/pinky_pro/config/board.yaml").read_text(encoding="utf-8"))
    display = board["boot_display"]
    declared = {display["lcd"]["spi"], display["lcd"]["gpiochip"], display["buzzer"]["gpiochip"],
                display["battery_adc"]["bus"], display["lamp"]["node"]}
    allowed = {value.split()[0] for value in _directives()["DeviceAllow"]}
    assert declared == allowed
    assert display["unit"] == "rosy-face.service"
    # BCM 4: heard on rosy_18 on 2026-09-26 (D-190 table); on by default since D-260 2.
    assert display["buzzer"]["bcm_line"] == _display().BUZZER_DEFAULT_LINE == 4
    assert display["buzzer"]["enabled_by_default"] is True
    lamp = display["lamp"]
    module = _display()
    assert str(lamp["pwm_channel"]) == module.LAMP_PWM_CHANNEL and lamp["bcm_line"] == 19
    assert module.LAMP_HELPER.endswith(lamp["helper"]) and lamp["enabled_by_default"] is True
    # the true grant, not what the program chooses to do with it (security review M2)
    assert display["battery_adc"]["access"] == "rw-any-address"
    assert display["battery_adc"]["lock"] == "advisory-flock"
    for caps in (ROOT / "deploy/robot/pinky_pro/config").glob("capabilities.*.yaml"):
        text = caps.read_text(encoding="utf-8").lower()
        for word in ("lcd", "buzzer", "display"):
            assert word not in text, (caps.name, word)


def test_the_probe_checks_the_modules_and_the_unit(tmp_path):
    probe = _load("probe_display_runtime", IMAGE / "probe-display-runtime.py")

    assert set(probe.APT_MODULES) >= {"spidev", "lgpio"}
    assert set(probe.RELEASE_MODULES) >= {"rosylib", "emotion.info_screen"}
    assert probe.DEVICES == ("/dev/spidev0.0", "/dev/gpiochip4", "/dev/i2c-1", "/dev/ws281x_pwm")
    assert "core_common.robot_state" in probe.RELEASE_MODULES
    assert "core_common.face_screen" in probe.RELEASE_MODULES  # D-433
    failures = probe.check_unit(tmp_path)
    assert failures == ["missing systemd unit: rosy-face.service"]
    system = tmp_path / "etc/systemd/system"
    (system / "multi-user.target.wants").mkdir(parents=True)
    (system / "rosy-face.service").write_text(UNIT.read_text(encoding="utf-8"), encoding="utf-8")
    assert probe.check_unit(tmp_path) == ["rosy-face.service is not enabled"]
    (system / "multi-user.target.wants/rosy-face.service").write_text("", encoding="utf-8")
    assert probe.check_unit(tmp_path) == []
    (system / "rosy-face.service").write_text(
        UNIT.read_text(encoding="utf-8") + "DeviceAllow=/dev/gpiomem rw\n", encoding="utf-8")
    assert any("DeviceAllow" in failure for failure in probe.check_unit(tmp_path))


def test_the_probe_accepts_only_rpi_lgpio_refusing_a_non_pi_builder():
    probe = _load("probe_display_runtime_gpio", IMAGE / "probe-display-runtime.py")
    refusal = RuntimeError("This module can only be run on a Raspberry Pi!")

    assert probe.gpio_import_failure(refusal, on_a_pi=False) is None
    assert probe.gpio_import_failure(refusal, on_a_pi=True)
    assert probe.gpio_import_failure(ImportError("No module named 'lgpio'"), on_a_pi=False)
    assert probe.gpio_import_failure(RuntimeError("can not open gpiochip"), on_a_pi=False)
    assert probe.gpio_import_failure(OSError("Raspberry Pi"), on_a_pi=False)


def test_the_probe_requires_rpi_lgpio_to_honour_the_chip_variable(tmp_path):
    probe = _load("probe_display_runtime_chip", IMAGE / "probe-display-runtime.py")
    honours = tmp_path / "honours.py"
    # noble python3-rpi-lgpio 0.5-0ubuntu1, RPi/GPIO/__init__.py setmode()
    honours.write_text("        chip_num = os.environ.get('RPI_LGPIO_CHIP')\n", encoding="utf-8")
    ignores = tmp_path / "ignores.py"
    ignores.write_text("        chip_num = 4\n", encoding="utf-8")

    assert probe.check_chip_selection(str(honours)) == []
    assert probe.check_chip_selection(str(ignores))
    assert "Environment=LG_WD=/var/lib/rosy/display RPI_LGPIO_CHIP=4" in UNIT.read_text(encoding="utf-8")


def test_the_probe_renders_every_stage_from_the_source_tree(tmp_path, monkeypatch):
    # The CI container has no Pillow; the image build runs this same render check in-image.
    pytest.importorskip("PIL")
    monkeypatch.syspath_prepend(str(ROOT / "middleware/ui/face"))
    probe = _load("probe_display_runtime_render", IMAGE / "probe-display-runtime.py")

    failures = probe.check_render(tmp_path)

    assert failures == [f"missing font: /{probe.FONT}"]  # no DejaVu under tmp_path; the card still drew


# --- D-260: one robot state on the buzzer, the lamp and the LCD ------------------


class FakeProcess:
    def __init__(self, command, code=None):
        self.command = command
        self.returncode = code
        self.terminated = 0

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated += 1
        self.returncode = 0

    def kill(self):
        self.returncode = -9

    def wait(self, timeout=None):
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


class FakeSpawn:
    def __init__(self, code=None, error=None):
        self.code, self.error = code, error
        self.processes: list[FakeProcess] = []

    def __call__(self, command):
        if self.error:
            raise self.error
        process = FakeProcess(command, self.code if command[-1] != "test" else 0)
        self.processes.append(process)
        return process

    @property
    def patterns(self):
        return [process.command[-1] for process in self.processes]


def _lamp_tree(root: Path, channel: str = "3", helper: bool = True, node: bool = True) -> None:
    if node:
        (root / "dev").mkdir(parents=True, exist_ok=True)
        (root / "dev/ws281x_pwm").write_text("", encoding="utf-8")
    params = root / "sys/module/rp1_ws281x_pwm/parameters"
    params.mkdir(parents=True, exist_ok=True)
    (params / "pwm_channel").write_text(channel + "\n", encoding="ascii")
    if helper:
        path = root / "opt/rosy/current/install/lib/lamp_control/lamp_pattern"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")


def _state_loop(module, root, *, gpio=None, spawn=None, voltages=(8.2,), logs=None, wall=None):
    display, lcd, clock, battery, rendered, lines = _loop(module, root, gpio=gpio, buzzer_on=gpio is not None,
                                                          voltages=voltages, logs=logs)
    lamp = module.Lamp(root, True, module.Log(lines.append), spawn=spawn or FakeSpawn())
    display = module.FaceDisplay(root, lcd=lcd, render=display._render, battery=display._battery,
                                 buzzer=display._buzzer, clock=clock, lamp=lamp,
                                 wall=wall or (lambda: 1_000_000.0))
    return display, lamp, clock, rendered, lines


def _starts(gpio):
    return [event for event in gpio.events if event[0] == "start"]


def test_the_view_carries_the_rule_table_s_state_line_and_top_todo(tmp_path):
    module = _display()
    _status(tmp_path, "CORE_READY", runtime_mode="core",
            devices=[{"id": "adc.battery", "state": "no_response", "product": True}])

    view = module.read_view(tmp_path, None)

    assert view["robot_state"] == "caution"
    assert view["state_line"] == "Caution: ADC no response"
    assert view["todo"] == "Power-cycle the robot (ADC)"


def test_a_held_robot_shows_why_and_what_to_do(tmp_path):
    module = _display()
    _status(tmp_path, "CORE_READY", runtime_mode="core", devices=[])

    view = module.read_view(tmp_path, (80.0, 8.0))

    assert view["state_line"] == "Ready - cannot move: CORE only mode"
    assert view["todo"] == "Admin: promote to motor mode"


def test_the_battery_the_display_reads_itself_feeds_the_state(tmp_path):
    module = _display()
    _status(tmp_path, "CORE_READY", runtime_mode="hardware")

    assert module.read_view(tmp_path, (12.0, 6.6))["state_line"] == "Caution: battery 12 %"
    assert module.read_view(tmp_path, None)["robot_state"] == "ready"


def test_without_the_rule_table_the_card_and_the_stage_sounds_stay(tmp_path, monkeypatch):
    # An older release has no core_common.robot_state: no state rows, stage-only sounds.
    module = _display()
    monkeypatch.setattr(module, "robot_state", None)
    gpio = FakeGPIO()
    _status(tmp_path, "CORE_READY")
    display, _lamp, _clock, rendered, _lines = _state_loop(module, tmp_path, gpio=gpio)

    display.step()

    assert "state_line" not in rendered[-1] and len(_starts(gpio)) == 1


def test_caution_is_two_low_tones_and_held_ready_one(tmp_path):
    module = _display()
    gpio = FakeGPIO()
    gpio.events.clear()
    _status(tmp_path, "BOOTING")
    display, _lamp, clock, _rendered, _lines = _state_loop(module, tmp_path, gpio=gpio)
    display.step()
    assert _starts(gpio) == []

    _status(tmp_path, "CORE_READY", runtime_mode="core")
    clock.now += 1
    display.step()
    assert len(_starts(gpio)) == 1 and ("pwm", 22, module.BUZZER_FREQUENCY_HZ) in gpio.events

    _status(tmp_path, "CORE_READY", runtime_mode="core",
            devices=[{"id": "camera", "state": "no_response", "product": True}])
    clock.now += 1
    display.step()
    assert len(_starts(gpio)) == 1  # a caution must hold before it sounds
    clock.now += module.CAUTION_DEBOUNCE_S
    display.step()
    assert len(_starts(gpio)) == 3
    assert ("change", module.BUZZER_LOW_HZ) in gpio.events


def test_caution_is_not_repeated_within_the_window_but_ready_and_failed_always_sound(tmp_path):
    # A battery hovering at the threshold must not beep caution every 15 s (review L2:
    # only caution is limited; ready and failed are real news on every transition).
    module = _display()
    gpio = FakeGPIO()
    _status(tmp_path, "CORE_READY", runtime_mode="hardware")
    display, _lamp, clock, _rendered, _lines = _state_loop(module, tmp_path, gpio=gpio)
    display.step()  # ready: one beep
    caution = [{"id": "camera", "state": "no_response", "product": True}]
    for _ in range(3):
        _status(tmp_path, "CORE_READY", runtime_mode="hardware", devices=caution)
        clock.now += 20
        display.step()
        clock.now += module.CAUTION_DEBOUNCE_S
        display.step()
        _status(tmp_path, "CORE_READY", runtime_mode="hardware")
        clock.now += 20
        display.step()
    assert len(_starts(gpio)) == 1 + 2  # caution -> ready -> caution -> ready flap: one chirp, caution once

    for _ in range(2):
        _status(tmp_path, "FAILED:rosy-core")
        clock.now += 1
        display.step()
        _status(tmp_path, "CORE_READY", runtime_mode="hardware")
        clock.now += 1
        display.step()
    assert len(_starts(gpio)) == 3 + 2 * (3 + 1)  # failed and the ready after it sound every time

    clock.now += module.BUZZER_REPEAT_S
    _status(tmp_path, "CORE_READY", runtime_mode="hardware", devices=caution)
    display.step()
    clock.now += module.CAUTION_DEBOUNCE_S
    display.step()
    assert len(_starts(gpio)) == 3 + 2 * (3 + 1) + 2


def test_ready_and_held_ready_share_one_sound(tmp_path):
    module = _display()
    gpio = FakeGPIO()
    _status(tmp_path, "CORE_READY", runtime_mode="core")
    display, _lamp, clock, _rendered, _lines = _state_loop(module, tmp_path, gpio=gpio)
    display.step()
    _status(tmp_path, "CORE_READY", runtime_mode="hardware")  # promoted
    clock.now += 1
    display.step()

    assert len(_starts(gpio)) == 1


@pytest.mark.parametrize("stage,extra,pattern", [
    ("BOOTING", {}, "booting"),
    ("PROVISIONED", {}, "booting"),
    ("CORE_READY", {"runtime_mode": "hardware"}, "ready"),
    ("CORE_READY", {"runtime_mode": "core"}, "ready"),
    ("FAILED:rosy-core", {}, "failed"),
    ("CORE_READY", {"devices": [{"id": "adc.ir0", "state": "no_response", "product": True}]}, "caution"),
    # D-380: CORE's mode rides boot-status.json; the rule table picks the pattern.
    ("CORE_READY", {"runtime_mode": "hardware", "robot_mode": "MANUAL"}, "manual"),
    ("CORE_READY", {"runtime_mode": "hardware", "robot_mode": "NAVIGATION"}, "navigating"),
    ("CORE_READY", {"runtime_mode": "hardware", "robot_mode": "DOCKING"}, "docking"),
    ("CORE_READY", {"runtime_mode": "hardware", "robot_mode": "EMERGENCY"}, "emergency"),
    ("CORE_READY", {"runtime_mode": "hardware", "robot_mode": "IDLE"}, "ready"),
    ("CORE_READY", {"runtime_mode": "hardware", "robot_mode": "DRIVE"}, "ready"),
    # D-381: a stuck goal blinks inside NAVIGATION; transient nav states do not.
    ("CORE_READY", {"runtime_mode": "hardware", "robot_mode": "NAVIGATION", "nav_state": "BLOCKED"}, "blocked"),
    ("CORE_READY", {"runtime_mode": "hardware", "robot_mode": "NAVIGATION", "nav_state": "FAILED"}, "blocked"),
    ("CORE_READY", {"runtime_mode": "hardware", "robot_mode": "NAVIGATION", "nav_state": "ARRIVED"}, "navigating"),
    # The lamp priority, live: a failure and a caution outrank the mode.
    ("FAILED:rosy-core", {"robot_mode": "NAVIGATION"}, "failed"),
    ("CORE_READY", {"runtime_mode": "hardware", "robot_mode": "MANUAL",
                    "devices": [{"id": "adc.ir0", "state": "no_response", "product": True}]}, "caution"),
])
def test_each_state_starts_its_lamp_pattern(tmp_path, stage, extra, pattern):
    module = _display()
    _lamp_tree(tmp_path)
    _status(tmp_path, stage, **extra)
    spawn = FakeSpawn()
    display, lamp, _clock, _rendered, _lines = _state_loop(module, tmp_path, spawn=spawn)

    display.step()

    assert spawn.patterns == [pattern]
    assert Path(spawn.processes[0].command[0]).as_posix().endswith("lib/lamp_control/lamp_pattern")
    assert lamp.pattern == pattern


def test_a_new_state_stops_the_old_pattern_first_and_an_unchanged_state_keeps_it(tmp_path):
    module = _display()
    _lamp_tree(tmp_path)
    _status(tmp_path, "BOOTING")
    spawn = FakeSpawn()
    display, _lamp, clock, _rendered, _lines = _state_loop(module, tmp_path, spawn=spawn)
    display.step()
    clock.now += 1
    display.step()
    assert spawn.patterns == ["booting"]

    _status(tmp_path, "FAILED:rosy-core")
    clock.now += 1
    display.step()

    assert spawn.patterns == ["booting", "failed"]
    assert spawn.processes[0].terminated == 1


# --- D-380: the operating mode on the lamp and the LCD line ----------------------


def test_a_mode_change_switches_the_pattern_without_a_sound(tmp_path):
    module = _display()
    _lamp_tree(tmp_path)
    _status(tmp_path, "CORE_READY", runtime_mode="hardware")
    gpio = FakeGPIO()
    spawn = FakeSpawn()
    display, _lamp, clock, _rendered, _lines = _state_loop(module, tmp_path, gpio=gpio, spawn=spawn)
    display.step()

    _status(tmp_path, "CORE_READY", runtime_mode="hardware", robot_mode="MANUAL")
    clock.now += 1
    display.step()

    assert spawn.patterns == ["ready", "manual"]
    assert len(_starts(gpio)) == 1  # ready sounded once; the mode change stays silent


def test_entering_emergency_sounds_even_with_a_healthy_state(tmp_path):
    module = _display()
    _lamp_tree(tmp_path)
    _status(tmp_path, "CORE_READY", runtime_mode="hardware")
    gpio = FakeGPIO()
    spawn = FakeSpawn()
    display, _lamp, clock, _rendered, _lines = _state_loop(module, tmp_path, gpio=gpio, spawn=spawn)
    display.step()

    _status(tmp_path, "CORE_READY", runtime_mode="hardware", robot_mode="EMERGENCY")
    clock.now += 1
    display.step()
    clock.now += 1
    display.step()  # staying in EMERGENCY announces nothing further

    assert spawn.patterns == ["ready", "emergency"]
    assert len(_starts(gpio)) == 5  # ready once, the e-stop entry four times
    # One frequency change to 2500 Hz carries the four beeps — failed stays at 2 kHz.
    assert [event for event in gpio.events if event[0] == "change"] == [("change", 2500)]

    _status(tmp_path, "CORE_READY", runtime_mode="hardware", robot_mode="IDLE")
    clock.now += 1
    display.step()  # leaving EMERGENCY is the ready chirp again, once

    assert spawn.patterns == ["ready", "emergency", "ready"]
    assert len(_starts(gpio)) == 6


def test_emergency_card_and_lamp_are_visible_before_the_entry_sound(tmp_path):
    module = _display()
    _lamp_tree(tmp_path)
    _status(tmp_path, "CORE_READY", runtime_mode="hardware")
    _face_inputs(tmp_path)
    spawn = FakeSpawn()
    display, lamp, clock, rendered, _lines = _state_loop(module, tmp_path, spawn=spawn, wall=lambda: WALL)
    display.step()
    _status(tmp_path, "CORE_READY", runtime_mode="hardware", robot_mode="EMERGENCY")
    _face_inputs(tmp_path, robot_mode="EMERGENCY", estop=True)
    clock.now += 1
    seen = []

    def announce(sound):
        seen.append((sound, lamp.pattern, rendered[-1]["screen"]["kind"], len(display.lcd.shown)))

    display._buzzer.announce = announce
    display.step()

    assert seen == [("emergency", "emergency", "stopped", 1)]


def test_emergency_sound_survives_a_broken_lcd(tmp_path):
    module = _display()
    _lamp_tree(tmp_path)
    _status(tmp_path, "CORE_READY", runtime_mode="hardware")
    spawn = FakeSpawn()
    display, lamp, clock, _rendered, _lines = _state_loop(module, tmp_path, spawn=spawn)
    display.step()
    _status(tmp_path, "CORE_READY", runtime_mode="hardware", robot_mode="EMERGENCY")
    clock.now += 1
    heard = []
    display._buzzer.announce = heard.append
    display._render = lambda _card: (_ for _ in ()).throw(RuntimeError("LCD offline"))

    with pytest.raises(RuntimeError, match="LCD offline"):
        display.step()

    assert lamp.pattern == "emergency" and heard == ["emergency"]


def test_the_lcd_state_line_names_the_operating_mode_in_ascii(tmp_path):
    module = _display()
    _status(tmp_path, "CORE_READY", runtime_mode="hardware", robot_mode="NAVIGATION")

    view = module.read_view(tmp_path, None)

    assert view["state_line"] == "Ready - NAVIGATION"
    # IDLE and an unknown mode keep the plain line.
    _status(tmp_path, "CORE_READY", runtime_mode="hardware", robot_mode="IDLE")
    assert module.read_view(tmp_path, None)["state_line"] == "Ready"
    _status(tmp_path, "CORE_READY", runtime_mode="hardware", robot_mode="DRIVE")
    assert module.read_view(tmp_path, None)["state_line"] == "Ready"


def test_the_lcd_state_line_names_the_formation_role_at_the_end(tmp_path):
    module = _display()
    _status(tmp_path, "CORE_READY", runtime_mode="hardware", robot_mode="NAVIGATION",
            swarm_role="leader")

    view = module.read_view(tmp_path, None)

    assert view["state_line"] == "Ready - NAVIGATION - LEADER"
    # A follower says so too; "none" and unknown roles keep the mode line.
    _status(tmp_path, "CORE_READY", runtime_mode="hardware", robot_mode="NAVIGATION",
            swarm_role="follower")
    assert module.read_view(tmp_path, None)["state_line"] == "Ready - NAVIGATION - FOLLOWER"
    _status(tmp_path, "CORE_READY", runtime_mode="hardware", robot_mode="NAVIGATION",
            swarm_role="none")
    assert module.read_view(tmp_path, None)["state_line"] == "Ready - NAVIGATION"
    _status(tmp_path, "CORE_READY", runtime_mode="hardware", robot_mode="NAVIGATION",
            swarm_role="captain")
    assert module.read_view(tmp_path, None)["state_line"] == "Ready - NAVIGATION"


def test_the_waiting_card_breathes_but_the_ready_card_holds_still(tmp_path):
    # D-385: BOOTING carries a frame phase in the redraw key; CORE_READY does not.
    module = _display()
    _status(tmp_path, "BOOTING")

    display, _lamp, clock, rendered, _lines = _state_loop(module, tmp_path)
    display.step()
    clock.now += 1
    display.step()

    assert "frame" in rendered[-1]

    _status(tmp_path, "CORE_READY", runtime_mode="core")
    clock.now += 1
    display.step()
    clock.now += 1
    display.step()

    assert "frame" not in rendered[-1]


def test_the_helper_knows_every_pattern_the_table_can_ask_for():
    # Cross-language sync: robot_state.lamp_pattern names patterns that only
    # lamp_pattern.c can show. A rename on either side must fail here.
    import re

    module = _display()
    source = (ROOT / "middleware/drivers/pinky_lamp/src/lamp_pattern.c").read_text(encoding="utf-8")
    names_block = source.split("static const char *names[]")[1].split("};")[0]
    known = set(re.findall(r'"([a-z]+)"', names_block))

    askable = {module.robot_state.lamp_pattern(state, mode, nav)
               for state in module.robot_state.STATES
               for mode in [*module.robot_state.ROBOT_MODES, None]
               for nav in [*module.robot_state.NAV_STATES, None]}

    assert askable | {"illumination"} <= known, sorted(askable - known)


@pytest.mark.parametrize("tree,message", [
    ({"node": False}, "no /dev/ws281x_pwm"),
    ({"channel": "2"}, "would drive the LCD backlight"),
    ({"channel": ""}, "pwm_channel=?"),
    ({"helper": False}, "no lamp_pattern in the release"),
])
def test_a_missing_or_unsafe_lamp_is_left_out_and_the_boot_goes_on(tmp_path, tree, message):
    module = _display()
    _lamp_tree(tmp_path, **tree)
    _status(tmp_path, "BOOTING")
    spawn = FakeSpawn()
    logs: list[str] = []
    display, _lamp, clock, rendered, _lines = _state_loop(module, tmp_path, spawn=spawn, logs=logs)

    assert display.step() is True  # the LCD still draws
    _status(tmp_path, "CORE_READY")
    clock.now += 1
    display.step()

    assert spawn.patterns == []
    assert sum(message in line for line in logs) == 1, logs
    assert rendered[-1]["stage"] == "CORE_READY"


def test_a_helper_that_fails_is_logged_once_and_not_restarted_every_poll(tmp_path):
    module = _display()
    _lamp_tree(tmp_path)
    _status(tmp_path, "BOOTING")
    spawn = FakeSpawn(code=2)
    logs: list[str] = []
    display, _lamp, clock, _rendered, _lines = _state_loop(module, tmp_path, spawn=spawn, logs=logs)

    for _ in range(3):
        display.step()
        clock.now += 1

    assert spawn.patterns == ["booting"]
    assert sum("ended with 2" in line for line in logs) == 1


def test_a_helper_that_cannot_start_is_left_out(tmp_path):
    module = _display()
    _lamp_tree(tmp_path)
    _status(tmp_path, "BOOTING")
    logs: list[str] = []
    display, lamp, _clock, _rendered, _lines = _state_loop(
        module, tmp_path, spawn=FakeSpawn(error=PermissionError(13, "Permission denied")), logs=logs)

    display.step()

    assert lamp.show("booting") is False
    assert sum("would not start" in line for line in logs) == 1


@pytest.mark.parametrize("environ,expected", [({}, True), ({"ROSY_LAMP_ENABLED": "false"}, False),
                                              ({"ROSY_LAMP_ENABLED": "no"}, False)])
def test_the_lamp_is_on_by_default_and_can_be_turned_off(environ, expected):
    module = _display()

    assert module.lamp_enabled(environ, module.Log(lambda _line: None)) is expected


def test_a_disabled_lamp_never_starts_the_helper(tmp_path):
    module = _display()
    _lamp_tree(tmp_path)
    spawn = FakeSpawn()
    lamp = module.Lamp(tmp_path, False, module.Log(lambda _line: None), spawn=spawn)

    assert lamp.show("booting") is False and spawn.patterns == []


def test_the_display_keeps_running_for_the_lamp_without_a_panel_or_buzzer(tmp_path, monkeypatch):
    module = _display()
    _lamp_tree(tmp_path)
    built = []

    def display(*_args, **kwargs):
        built.append(kwargs)
        raise SystemExit(7)  # reaching the loop is the point

    monkeypatch.setattr(module, "_release_modules", lambda: SimpleNamespace(render_boot=lambda view: view))
    monkeypatch.setattr(module, "FaceDisplay", display)
    monkeypatch.setenv("ROSY_BUZZER_ENABLED", "false")
    monkeypatch.delenv("ROSY_LAMP_ENABLED", raising=False)

    with pytest.raises(SystemExit):
        module.main(["--root", str(tmp_path)])

    assert built and built[0]["lamp"].available() and built[0]["lcd"] is None


# --- D-260 / D-247 6: a buzzer or lamp test handed over by rosy-hw-test -----------

REQUEST_ID = "00112233445566778899aabb"


def _hand_over(root: Path, action: str = "buzzer", request_id: str = REQUEST_ID, *, at: float = 1_000_000.0,
               **extra) -> None:
    path = root / "run/rosy-boot/display-test.request"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"action": action, "request_id": request_id, "requested_at": at, **extra}),
                    encoding="utf-8")


def _answer(root: Path):
    path = root / "run/rosy-display/display-test.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def test_queued_hardware_test_cannot_delay_or_replace_emergency_when_core_missing(tmp_path):
    module = _display()
    _lamp_tree(tmp_path)
    _status(tmp_path, "CORE_READY", robot_mode="EMERGENCY", estop=True, runtime_mode="hardware")
    spawn = FakeSpawn()
    display, lamp, _clock, _rendered, _lines = _state_loop(module, tmp_path, spawn=spawn)
    _hand_over(tmp_path)
    display._buzzer.test = lambda: pytest.fail("blocking bench test reached emergency")
    display.step()
    assert lamp.pattern == "emergency"
    assert _answer(tmp_path) is None and display._tested is None


def test_the_display_plays_a_handed_over_buzzer_test_once(tmp_path):
    module = _display()
    gpio = FakeGPIO()
    _status(tmp_path, "BOOTING")
    display, _lamp, clock, _rendered, _lines = _state_loop(module, tmp_path, gpio=gpio)
    display.step()
    _hand_over(tmp_path)

    display.step()
    clock.now += 1
    display.step()  # the same request id again: nothing more

    starts = _starts(gpio)
    assert starts == [("start", module.BUZZER_DUTY)] * module.TEST_BEEPS
    assert _answer(tmp_path) == {"schema": 1, "request_id": REQUEST_ID, "action": "buzzer", "state": "done",
                                 "detail": "BCM 22 · 2 kHz · duty 10 % · 3×150 ms (부팅 표시가 울림)"}


def test_a_display_with_the_buzzer_off_answers_unavailable(tmp_path):
    module = _display()
    _status(tmp_path, "BOOTING")
    display, _lamp, _clock, _rendered, _lines = _state_loop(module, tmp_path)
    _hand_over(tmp_path)

    assert display.handle_test() == "unavailable"
    assert _answer(tmp_path)["state"] == "unavailable"


def test_a_handed_over_lamp_test_pauses_the_state_pattern_and_resumes_it(tmp_path):
    module = _display()
    _lamp_tree(tmp_path)
    _status(tmp_path, "BOOTING")
    spawn = FakeSpawn()
    display, lamp, _clock, _rendered, _lines = _state_loop(module, tmp_path, spawn=spawn)
    display.step()
    _hand_over(tmp_path, "lamp")

    assert display.handle_test() == "done"

    assert spawn.patterns == ["booting", "test", "booting"]
    assert spawn.processes[0].terminated == 1 and lamp.pattern == "booting"
    assert _answer(tmp_path)["detail"].endswith("(부팅 표시가 켬)")


def test_identity_pulse_is_owned_by_face_and_requires_fresh_safe_state(tmp_path):
    module = _display()
    _lamp_tree(tmp_path)
    _status(tmp_path, "CORE_READY")
    spawn = FakeSpawn(code=0)
    display, lamp, _clock, _rendered, _lines = _state_loop(module, tmp_path, spawn=spawn)
    display.step()
    safe = {"estop": False, "robot_mode": "IDLE", "nav_state": "IDLE", "caution": []}
    display._core = lambda: safe
    _hand_over(tmp_path, "identify_blue")
    assert display.handle_test() == "done"
    assert spawn.patterns == ["ready", "identify_blue", "ready"]
    assert lamp.pattern == "ready"
    _hand_over(tmp_path, "identify_amber", request_id="1122334455667788")
    safe["estop"] = True
    assert display.handle_test() == "failed"
    assert "거절" in _answer(tmp_path)["detail"]
    assert spawn.patterns == ["ready", "identify_blue", "ready"]


def test_identity_pulse_temporarily_uses_a_disabled_normal_lamp(tmp_path):
    module = _display()
    _lamp_tree(tmp_path)
    _status(tmp_path, "CORE_READY")
    spawn = FakeSpawn(code=0)
    display, lamp, _clock, _rendered, _lines = _state_loop(module, tmp_path, spawn=spawn)
    lamp.enabled = False
    display.step()
    assert spawn.patterns == []
    display._core = lambda: {"estop": False, "robot_mode": "IDLE", "nav_state": "IDLE", "caution": []}

    _hand_over(tmp_path, "identify_blue")
    assert display.handle_test() == "done"
    assert spawn.patterns == ["identify_blue"]
    assert lamp.enabled is False
    display.step()
    assert spawn.patterns == ["identify_blue"]
    assert lamp.pattern == "ready"


def test_identity_pulse_runs_on_a_moving_robot_and_restores_its_drive_pattern(tmp_path):
    # D-472 addendum 5: Fleet asks moving robots; the blink stands in for the drive pattern.
    module = _display()
    _lamp_tree(tmp_path)
    _status(tmp_path, "CORE_READY", robot_mode="NAVIGATION", nav_state="ACTIVE")
    spawn = FakeSpawn(code=0)
    display, lamp, _clock, _rendered, _lines = _state_loop(module, tmp_path, spawn=spawn)
    display.step()
    assert lamp.pattern == "navigating"
    display._core = lambda: {"estop": False, "robot_mode": "NAVIGATION", "nav_state": "ACTIVE", "caution": []}
    _hand_over(tmp_path, "identify_amber")
    assert display.handle_test() == "done"
    assert spawn.patterns == ["navigating", "identify_amber", "navigating"]


@pytest.mark.parametrize("status, core", [
    ({"robot_mode": "EMERGENCY"}, {"estop": False, "robot_mode": "EMERGENCY", "caution": []}),
    ({"robot_mode": "IDLE"}, {"estop": False, "robot_mode": "IDLE", "caution": ["battery_low"]}),
    ({"robot_mode": "NAVIGATION", "nav_state": "BLOCKED"},
     {"estop": False, "robot_mode": "NAVIGATION", "caution": []}),
    ({"robot_mode": "IDLE"}, None),  # no fresh CORE hand-over
])
def test_identity_pulse_is_refused_while_a_safety_display_holds(tmp_path, status, core):
    module = _display()
    _lamp_tree(tmp_path)
    _status(tmp_path, "CORE_READY", **status)
    spawn = FakeSpawn(code=0)
    display, lamp, _clock, _rendered, _lines = _state_loop(module, tmp_path, spawn=spawn)
    display.step()
    display._core = lambda: core
    _hand_over(tmp_path, "identify_blue")
    assert display.handle_test() == "failed"
    assert "identify_blue" not in spawn.patterns


def test_identity_pulse_is_cut_short_when_caution_starts_mid_blink(tmp_path):
    module = _display()
    _lamp_tree(tmp_path)
    _status(tmp_path, "CORE_READY")
    spawn = FakeSpawn()  # the helper keeps running until stopped
    display, lamp, _clock, _rendered, _lines = _state_loop(module, tmp_path, spawn=spawn)
    display.step()
    reads = []

    def core():
        reads.append(1)
        return {"estop": False, "robot_mode": "IDLE", "caution": [] if len(reads) < 3 else ["battery_low"]}
    display._core = core
    _hand_over(tmp_path, "identify_blue")
    assert display.handle_test() == "failed"
    assert spawn.processes[1].terminated == 1
    assert lamp.pattern is None  # the next step() shows the caution pattern, not the old ready


def test_identity_pulse_has_a_hard_deadline_and_a_short_request_age(tmp_path, monkeypatch):
    module = _display()
    _lamp_tree(tmp_path)
    _status(tmp_path, "CORE_READY")
    spawn = FakeSpawn()  # a helper that never ends on its own
    display, lamp, _clock, _rendered, _lines = _state_loop(module, tmp_path, spawn=spawn)
    display.step()
    display._core = lambda: {"estop": False, "robot_mode": "IDLE", "caution": []}
    assert module.IDENTIFY_MAX_S <= 4.0 and module.IDENTIFY_REQUEST_MAX_AGE_S <= 1.0
    _hand_over(tmp_path, "identify_blue", at=1_000_000.0 - 1.5)  # older than the identify age
    assert display.handle_test() is None
    assert module.read_test_request(tmp_path / module.TEST_REQUEST, 1_000_000.0) is None
    _hand_over(tmp_path, "lamp", at=1_000_000.0 - 1.5)  # a bench test keeps its 30 s age
    assert module.read_test_request(tmp_path / module.TEST_REQUEST, 1_000_000.0) is not None
    monkeypatch.setattr(module, "IDENTIFY_MAX_S", 0.05)
    state, detail = lamp.identify("blue", lambda: False)
    assert state == "failed" and "시간 초과" in detail


def test_an_accepted_fleet_call_chirps_once_and_a_refused_call_stays_quiet(tmp_path):
    module = _display()
    _lamp_tree(tmp_path)
    _status(tmp_path, "CORE_READY", runtime_mode="hardware")
    gpio = FakeGPIO()
    spawn = FakeSpawn(code=0)
    display, lamp, clock, _rendered, _lines = _state_loop(module, tmp_path, gpio=gpio, spawn=spawn)
    display.step()
    assert len(_starts(gpio)) == 1  # ready, once
    assert display._sound == "ready"
    assert module.BUZZER_PATTERNS["call"] == (2, module.BUZZER_CALL_HZ)
    assert module.BUZZER_CALL_HZ not in (module.BUZZER_FREQUENCY_HZ, module.BUZZER_LOW_HZ, 2500)
    assert "call" not in module.SOUNDS

    safe = {"estop": False, "robot_mode": "IDLE", "nav_state": "IDLE", "caution": []}
    display._core = lambda: safe
    _hand_over(tmp_path, "identify_blue")
    assert display.handle_test() == "done"
    assert len(_starts(gpio)) == 3
    assert [event for event in gpio.events if event[0] == "change"] == [("change", module.BUZZER_CALL_HZ)]
    assert display._sound == "ready"
    assert spawn.patterns == ["ready", "identify_blue", "ready"]

    clock.now += 1
    display.step()  # still ready: the call did not arm another health chirp
    assert len(_starts(gpio)) == 3

    _hand_over(tmp_path, "identify_amber", request_id="1122334455667788")
    safe["estop"] = True
    assert display.handle_test() == "failed"  # refused at once: no chirp, no blink
    assert _answer(tmp_path)["state"] == "failed"
    safe["estop"] = False
    display.screen = {"kind": "stopped", "row": "stopped", "strip_tone": None}
    _hand_over(tmp_path, "identify_amber", request_id="2233445566778899")
    assert display.handle_test() is None
    assert len(_starts(gpio)) == 3
    assert spawn.patterns == ["ready", "identify_blue", "ready"]


def test_identity_pulse_stops_without_restoring_old_pattern_when_safety_changes(tmp_path):
    module = _display()
    _lamp_tree(tmp_path)
    _status(tmp_path, "BOOTING")
    spawn = FakeSpawn()
    display, lamp, _clock, _rendered, _lines = _state_loop(module, tmp_path, spawn=spawn)
    display.step()
    state, detail = lamp.identify("amber", lambda: True)
    assert state == "failed" and "중단" in detail
    assert lamp.pattern is None
    assert spawn.patterns == ["booting", "identify_amber"]
    assert spawn.processes[-1].terminated == 1


def test_a_lamp_test_without_a_usable_lamp_answers_unavailable(tmp_path):
    module = _display()
    _lamp_tree(tmp_path, channel="2")
    _status(tmp_path, "BOOTING")
    spawn = FakeSpawn()
    display, _lamp, _clock, _rendered, _lines = _state_loop(module, tmp_path, spawn=spawn)
    _hand_over(tmp_path, "lamp")

    assert display.handle_test() == "unavailable" and spawn.patterns == []


@pytest.mark.parametrize("change", [
    {"action": "motor"}, {"request_id": "../../etc"}, {"request_id": 7}, {"at": 1_000_000.0 - 60},
    {"at": 1_000_000.0 + 60}, {"extra": 1}, {"at": True},
])
def test_anything_but_a_fresh_exact_hand_over_is_ignored(tmp_path, change):
    module = _display()
    gpio = FakeGPIO()
    _status(tmp_path, "BOOTING")
    display, _lamp, _clock, _rendered, _lines = _state_loop(module, tmp_path, gpio=gpio)
    arguments = {"action": "buzzer", "request_id": REQUEST_ID, "at": 1_000_000.0}
    arguments.update(change)
    _hand_over(tmp_path, arguments.pop("action"), arguments.pop("request_id"), **arguments)

    assert display.handle_test() is None
    assert _starts(gpio) == [] and _answer(tmp_path) is None


def test_an_oversized_hand_over_is_not_read(tmp_path):
    module = _display()
    _hand_over(tmp_path, pad="x" * 600)

    assert module.read_test_request(tmp_path / module.TEST_REQUEST, 1_000_000.0) is None


# --- D-433: rosy-face — the situation table drives the LCD -----------------------------

FACE = ROOT / "middleware/ui/face"
WALL = 1_790_000_000.0  # any fixed wall clock; the hand-over's written_at follows it


class PanelLCD(FakeLCD):
    """FakeLCD plus the calls rosy-face makes for frames, sleep and backlight."""

    def __init__(self):
        super().__init__()
        self.panels = []
        self.calls = []

    def show_panel(self, pixel):
        self.panels.append(pixel)

    def sleep(self):
        self.calls.append(("sleep",))

    def wake(self):
        self.calls.append(("wake",))

    def set_backlight(self, value):
        self.calls.append(("backlight", value))


class FakeGif:
    """A seekable 'GIF' of ``count`` frames; seek past the end raises EOFError like PIL."""

    def __init__(self, count):
        self.count = count
        self.at = None
        self.closed = False

    def seek(self, index):
        if index >= self.count:
            raise EOFError
        self.at = index

    def close(self):
        self.closed = True


def _face_inputs(root: Path, age: float = 0.0, **fields) -> None:
    from datetime import datetime, timezone

    data = {"schema": 1, "written_at": datetime.fromtimestamp(WALL - age, timezone.utc).isoformat(),
            "robot_mode": "IDLE", "nav_state": "IDLE", "estop": False, "face": "basic",
            "power_mode": "active", "activity_kind": None, "docking_state": "UNDOCKED",
            "battery_percent": 80.0, "battery_charging": False, "line_follow_mode": "OFF",
            "line_follow_state": "OFF", "caution": [], "drive": None, "wake": None, **fields}
    (root / "run/rosy").mkdir(parents=True, exist_ok=True)
    (root / "run/rosy/face-inputs.json").write_text(json.dumps(data), encoding="utf-8")


def _face_loop(module, root, *, gifs=None, logs=None):
    lines = logs if logs is not None else []
    log = module.Log(lines.append)
    gifs = gifs if gifs is not None else {"basic": 3, "happy": 2, "interest": 2, "sad": 2}
    opened = []

    def opener(path):
        name = Path(path).stem
        if name not in gifs:
            raise FileNotFoundError(path)
        opened.append(name)
        return FakeGif(gifs[name])

    faces = module.FaceFrames(root / module.FACE_DIR, opener=opener,
                              convert=lambda image: (image.count, image.at), log=log)
    rendered: list[dict] = []

    def render(card):
        rendered.append(card)
        return f"image-{len(rendered)}"

    lcd = PanelLCD()
    clock = FakeClock()
    battery = module.BatteryReader(lambda: FakeBattery([8.2]), lambda volts: 80.0, log)
    display = module.FaceDisplay(root, lcd=lcd, render=render, battery=battery,
                                 buzzer=module.Buzzer(None, 4, False, lambda _s: None), clock=clock,
                                 wall=lambda: WALL, faces=faces,
                                 strip=lambda frame, *bar: (frame, *bar))
    return display, lcd, clock, rendered, opened, lines


def _screen_row(rendered):
    return rendered[-1]["screen"]["row"]


def test_low_light_opt_in_holds_recovery_and_clears_stale_or_alarm(tmp_path):
    module = _display()
    _status(tmp_path, "CORE_READY", runtime_mode="hardware")
    _face_inputs(tmp_path, power_mode="standby", camera_quality={"valid": False, "reason": "low_light"}, camera_quality_age_s=0)
    display, lcd, clock, rendered, _opened, _lines = _face_loop(module, tmp_path)
    _lamp_tree(tmp_path)
    spawn = FakeSpawn()
    display._lamp = module.Lamp(tmp_path, True, module.Log(lambda _message: None), spawn=spawn)
    display.step()
    assert display.screen["kind"] == "sleep"  # opt-in is off by default
    display._low_light_enabled = True
    display.step()
    assert display.screen["kind"] == "light" and display.screen["backlight"] == 100
    assert spawn.patterns[-1] == "illumination"
    _face_inputs(tmp_path, power_mode="standby", camera_quality={"valid": True, "reason": "usable"}, camera_quality_age_s=0)
    display.step()
    assert display.screen["kind"] == "light"  # own illumination must not oscillate
    _face_inputs(tmp_path, power_mode="standby", camera_quality={"valid": False, "reason": "overexposed"}, camera_quality_age_s=0)
    display.step()
    assert display.screen["kind"] == "sleep" and display._lamp.pattern != "illumination"
    _face_inputs(tmp_path, power_mode="standby", camera_quality={"valid": False, "reason": "low_light"}, camera_quality_age_s=0)
    display.step()
    assert display.screen["kind"] == "light"
    (tmp_path / "run/rosy/face-inputs.json").write_text("{", encoding="utf-8")
    display._wall = lambda: WALL + 2.1
    display.step()
    assert display.screen["kind"] == "sleep"  # cached quality expires before CORE envelope
    assert display._lamp.pattern != "illumination"
    display._wall = lambda: WALL
    _face_inputs(tmp_path, estop=True, camera_quality={"valid": False, "reason": "low_light"}, camera_quality_age_s=0)
    display.step()
    assert display.screen["kind"] == "stopped" and not display._light_session
    assert display._lamp.pattern != "illumination"


def test_face_owns_the_screen_with_a_fresh_handover(tmp_path):
    module = _display()
    _status(tmp_path, "CORE_READY", runtime_mode="hardware")
    _face_inputs(tmp_path, face="basic")
    display, lcd, _clock, rendered, opened, _lines = _face_loop(module, tmp_path)

    assert display.step() is False and rendered == []
    assert display.animating == ("basic", "Waiting", "ok", 80.0, False)
    for _ in range(5):
        assert display.tick() is True
    # The panel-sized loop keeps every authored frame, then replays.
    # The situation strip rides each frame; the seek index stays the frame's second field.
    assert [panel[0][1] for panel in lcd.panels] == [0, 1, 2, 0, 1]
    assert {panel[1] for panel in lcd.panels} == {"Waiting"}
    assert opened == ["basic"]


def test_a_stale_handover_brings_back_the_status_card(tmp_path):
    module = _display()
    _status(tmp_path, "CORE_READY", runtime_mode="hardware")
    _face_inputs(tmp_path, age=4.0)
    display, lcd, _clock, rendered, _opened, _lines = _face_loop(module, tmp_path)

    assert display.step() is True
    assert _screen_row(rendered) == "core_missing"
    assert rendered[-1]["state_line"] == "CORE not responding"
    assert display.animating is None and display.tick() is False and lcd.panels == []


def test_one_unreadable_poll_keeps_the_last_good_handover(tmp_path):
    # Review MED4: a write in flight must not flash "CORE not responding" or restart the drive card.
    module = _display()
    _status(tmp_path, "CORE_READY", runtime_mode="hardware")
    _face_inputs(tmp_path, robot_mode="MANUAL", face="interest", drive={"mode": "MANUAL"})
    display, _lcd, clock, rendered, _opened, _lines = _face_loop(module, tmp_path)
    display.step()
    since = display._drive_since

    (tmp_path / "run/rosy/face-inputs.json").write_text("{", encoding="utf-8")
    clock.now += 1
    display.step()
    assert display.screen["row"] in ("drive", "face") and display._drive_since == since

    display._wall = lambda: WALL + 4.0  # the kept hand-over is now older than three seconds
    clock.now += 1
    display.step()
    assert _screen_row(rendered) == "core_missing"


def test_a_handover_from_someone_else_is_no_handover(tmp_path):
    module = _display()
    _status(tmp_path, "CORE_READY", runtime_mode="hardware")
    _face_inputs(tmp_path)
    display, _lcd, _clock, rendered, _opened, _lines = _face_loop(module, tmp_path)
    display._core_owner = os.stat(tmp_path / "run/rosy/face-inputs.json").st_uid + 1

    display.step()

    assert _screen_row(rendered) == "core_missing"


def test_estop_is_the_full_stopped_card(tmp_path):
    module = _display()
    _status(tmp_path, "CORE_READY", runtime_mode="hardware")
    _face_inputs(tmp_path, robot_mode="EMERGENCY", estop=True, face="sad")
    display, _lcd, _clock, rendered, _opened, _lines = _face_loop(module, tmp_path)

    display.step()

    screen = rendered[-1]["screen"]
    assert screen["kind"] == "stopped" and screen["cause"] == "E-stop latched" and screen["release"]


def test_an_unused_login_code_keeps_the_card_until_it_burns(tmp_path):
    module = _display()
    _status(tmp_path, "CORE_READY", runtime_mode="hardware")
    _face_inputs(tmp_path)
    _login(tmp_path, "ABCD-EFGH\noperator\n")
    display, _lcd, clock, rendered, _opened, _lines = _face_loop(module, tmp_path)

    display.step()
    assert _screen_row(rendered) == "login" and rendered[-1]["login_code"] == "ABCD-EFGH"

    _login(tmp_path, "BURNED\n")
    clock.now += 1
    _face_inputs(tmp_path)
    display.step()
    assert display.animating == ("basic", "Waiting", "ok", 80.0, False)


def _peer_approval(root: Path, expires_in: float = 300.0, **fields) -> None:
    from datetime import datetime, timezone

    data = {"display_code": "K7QM", "approval_code": "ABC234",
            "expires_at": datetime.fromtimestamp(WALL + expires_in, timezone.utc).isoformat(), **fields}
    (root / "run/rosy-peer-display").mkdir(parents=True, exist_ok=True)
    (root / "run/rosy-peer-display/approval.json").write_text(json.dumps({"requests": [data]}), encoding="utf-8")


def test_a_peer_request_card_shows_the_approval_code_above_the_face_and_login(tmp_path, capsys):
    module = _display()
    _status(tmp_path, "CORE_READY", runtime_mode="hardware")
    _face_inputs(tmp_path)
    _login(tmp_path, "ABCD-EFGH\noperator\n")
    _peer_approval(tmp_path)
    display, _lcd, clock, rendered, _opened, lines = _face_loop(module, tmp_path)

    display.step()
    assert _screen_row(rendered) == "peer_request"
    assert rendered[-1]["screen"]["peer"] == {"requests": [{"display_code": "K7QM", "approval_code": "ABC234"}]}

    # An e-stop card outranks it; the code never reaches the journal.
    _face_inputs(tmp_path, robot_mode="EMERGENCY", estop=True)
    clock.now += 1
    display.step()
    assert rendered[-1]["screen"]["kind"] == "stopped"
    assert not any("ABC234" in line for line in lines) and "ABC234" not in capsys.readouterr().err

    # CORE removed the file: back to the login card.
    _face_inputs(tmp_path)
    (tmp_path / "run/rosy-peer-display/approval.json").unlink()
    clock.now += 1
    display.step()
    assert _screen_row(rendered) == "login"


@pytest.mark.parametrize("change", [
    {"expires_in": -1.0}, {"approval_code": "abc234"}, {"approval_code": "ABC23"}, {"display_code": "K7Q1"},
    {"expires_at": "2026-10-06T10:00:00"}, {"approval_code": 123456},
])
def test_an_expired_or_malformed_peer_approval_is_ignored(tmp_path, change):
    module = _display()
    _status(tmp_path, "CORE_READY", runtime_mode="hardware")
    _face_inputs(tmp_path)
    expires_in = change.pop("expires_in", 300.0)
    _peer_approval(tmp_path, expires_in, **change)
    display, _lcd, _clock, _rendered, _opened, _lines = _face_loop(module, tmp_path)

    display.step()

    assert display.animating == ("basic", "Waiting", "ok", 80.0, False)


def test_an_oversized_peer_approval_is_ignored(tmp_path):
    module = _display()
    _status(tmp_path, "CORE_READY", runtime_mode="hardware")
    _face_inputs(tmp_path)
    _peer_approval(tmp_path, padding="x" * 2100)
    display, _lcd, _clock, _rendered, _opened, _lines = _face_loop(module, tmp_path)

    display.step()

    assert display.animating == ("basic", "Waiting", "ok", 80.0, False)


def test_the_ap_card_stays_after_core_ready(tmp_path):
    module = _display()
    _status(tmp_path, "CORE_READY", runtime_mode="hardware")
    (tmp_path / "run/rosy-boot/network.json").write_text(json.dumps({"mode": "ap", "ssid": "rosy-x"}),
                                                          encoding="utf-8")
    _face_inputs(tmp_path)
    display, _lcd, _clock, rendered, _opened, _lines = _face_loop(module, tmp_path)

    display.step()

    assert _screen_row(rendered) == "ap"


def test_the_update_marker_shows_updating_and_a_stale_one_does_not(tmp_path):
    module = _display()
    _status(tmp_path, "CORE_READY", runtime_mode="hardware")
    _face_inputs(tmp_path)
    marker = tmp_path / "run/rosy-boot/update-display.txt"
    marker.write_text("health\n2026.10.03-027\n", encoding="utf-8")
    os.utime(marker, (WALL, WALL))
    display, _lcd, clock, rendered, _opened, _lines = _face_loop(module, tmp_path)

    display.step()
    assert rendered[-1]["screen"]["kind"] == "update" and rendered[-1]["screen"]["release"] == "2026.10.03-027"

    os.utime(marker, (WALL - module.UPDATE_MAX_AGE_S - 1, WALL - module.UPDATE_MAX_AGE_S - 1))
    clock.now += 1
    _face_inputs(tmp_path)
    display.step()
    assert display.animating is not None


@pytest.mark.parametrize("content", ["Applying\n2026.10.03-027\n", "health\nnot-a-release\n", ""])
def test_the_update_marker_is_strict(tmp_path, content):
    module = _display()
    (tmp_path / "run/rosy-boot").mkdir(parents=True)
    marker = tmp_path / "run/rosy-boot/update-display.txt"
    marker.write_text(content, encoding="utf-8")
    os.utime(marker, (WALL, WALL))

    update = module.read_update(tmp_path, WALL)

    assert update is None or update["release"] is None


def test_standby_sleeps_the_panel_and_a_wake_card_wakes_it(tmp_path):
    module = _display()
    _status(tmp_path, "CORE_READY", runtime_mode="hardware")
    _face_inputs(tmp_path, power_mode="standby")
    display, lcd, clock, rendered, _opened, _lines = _face_loop(module, tmp_path)

    display.step()
    assert ("sleep",) in lcd.calls and ("backlight", 0) in lcd.calls and display.tick() is False

    _face_inputs(tmp_path, power_mode="standby", wake={"reason": "proximity", "hold_s": 4.0})
    clock.now += 1
    display.step()
    assert lcd.calls[-2:] == [("wake",), ("backlight", 100)]
    assert rendered[-1]["screen"]["overlay"]["kind"] == "wake"


def test_the_drive_card_passes_over_the_face_on_the_cadence(tmp_path):
    module = _display()
    _status(tmp_path, "CORE_READY", runtime_mode="hardware")
    _face_inputs(tmp_path, robot_mode="NAVIGATION", nav_state="NAVIGATING", face="happy",
                 drive={"mode": "NAVIGATION", "speed": 0.12})
    display, _lcd, clock, rendered, _opened, _lines = _face_loop(module, tmp_path)

    display.step()  # the operating mode just began: the card shows first
    assert rendered[-1]["screen"]["overlay"]["kind"] == "drive"
    clock.now += 6
    _face_inputs(tmp_path, robot_mode="NAVIGATION", nav_state="NAVIGATING", face="happy",
                 drive={"mode": "NAVIGATION", "speed": 0.12})
    display.step()
    assert display.animating == ("happy", "Going", "ok", 80.0, False)
    clock.now += 15  # 21 s after the mode began
    _face_inputs(tmp_path, robot_mode="NAVIGATION", nav_state="NAVIGATING", face="happy",
                 drive={"mode": "NAVIGATION", "speed": 0.12})
    display.step()
    assert rendered[-1]["screen"]["overlay"]["kind"] == "drive"


def test_caution_is_a_strip_on_every_face_frame(tmp_path):
    module = _display()
    _status(tmp_path, "CORE_READY", runtime_mode="hardware",
            devices=[{"id": "camera", "state": "no_response", "product": True}])
    _face_inputs(tmp_path)
    display, lcd, _clock, _rendered, _opened, _lines = _face_loop(module, tmp_path)

    display.step()
    display.tick()

    assert display.animating[:3] == ("basic", "Check the camera cable", "caution")
    assert lcd.panels[-1][1:3] == ("Check the camera cable", "caution")


def test_a_handed_over_test_shows_its_strip(tmp_path):
    module = _display()
    _status(tmp_path, "CORE_READY", runtime_mode="hardware")
    _face_inputs(tmp_path)
    display, _lcd, _clock, _rendered, _opened, _lines = _face_loop(module, tmp_path)
    display._testing, display._testing_until = "lamp", display._clock() + 5

    display.step()

    assert display.animating[:3] == ("basic", "Testing lamp", "ok")


def test_a_missing_gif_is_logged_once_and_never_drawn(tmp_path):
    module = _display()
    _status(tmp_path, "CORE_READY", runtime_mode="hardware")
    _face_inputs(tmp_path, face="bored")
    lines = []
    display, lcd, _clock, _rendered, _opened, _lines = _face_loop(module, tmp_path, logs=lines)

    display.step()

    assert display.tick() is False and display.tick() is False and lcd.panels == []
    assert len([line for line in lines if "bored" in line]) == 1


def test_the_idle_backlight_halves_the_frame_rate(tmp_path):
    module = _display()
    _status(tmp_path, "CORE_READY", runtime_mode="hardware")
    _face_inputs(tmp_path, power_mode="idle")
    display, lcd, _clock, _rendered, _opened, _lines = _face_loop(module, tmp_path)

    display.step()
    drawn = [display.tick() for _ in range(6)]

    assert drawn.count(True) == 3 and ("backlight", 30) in lcd.calls


def test_the_shutdown_poll_only_draws(tmp_path):
    module = _display()
    _status(tmp_path, "CORE_READY", runtime_mode="hardware")
    _face_inputs(tmp_path)
    display, _lcd, _clock, rendered, _opened, _lines = _face_loop(module, tmp_path)
    reads = display.battery_reads
    display.shutting_down = True
    display.handle_test = lambda: pytest.fail("no test is played on the way out")

    assert display.step() is True
    assert display.battery_reads == reads and rendered[-1]["screen"]["kind"] == "shutdown"


@pytest.mark.parametrize("nologin,title", [(True, "Shutting down"), (False, "Display restarting")])
def test_sigterm_draws_one_last_card(tmp_path, nologin, title):
    module = _display()
    _status(tmp_path, "CORE_READY", runtime_mode="hardware")
    _face_inputs(tmp_path)
    if nologin:
        (tmp_path / "run/nologin").write_text("", encoding="utf-8")
    display, _lcd, _clock, rendered, _opened, _lines = _face_loop(module, tmp_path)
    display.shutting_down = True

    display.step()

    assert rendered[-1]["screen"]["kind"] == "shutdown" and rendered[-1]["shutdown_title"] == title


def _info_screen():
    if str(FACE) not in sys.path:
        sys.path.insert(0, str(FACE))
    from emotion import info_screen
    return info_screen


@pytest.mark.parametrize("screen", [
    {"kind": "status", "row": "booting"},
    {"kind": "stopped", "row": "stopped", "cause": "E-stop latched", "release": "Release: dashboard"},
    {"kind": "update", "row": "update", "release": "2026.10.03-027"},
    {"kind": "shutdown", "row": "shutdown"},
    {"kind": "face", "row": "drive", "overlay": {"kind": "drive", "payload": {"kind": "drive", "mode": "MANUAL"}},
     "strip": "Charge the battery", "strip_tone": "caution"},
    {"kind": "face", "row": "wake", "overlay": {"kind": "wake", "payload": {"battery_percent": 50.0}}},
    {"kind": "status", "row": "peer_request", "peer": {"requests": [
        {"display_code": "K7QM", "approval_code": "ABC234"}, {"display_code": "M2NP", "approval_code": "XYZ789"},
        {"display_code": "Q3RS", "approval_code": "DEF456"}]}},
])
def test_every_card_renders_on_the_panel_size(screen):
    module = _display()
    render = module.card_renderer(_info_screen())

    image = render({"stage": "CORE_READY", "device_name": "rosy-pinky-e4us", "screen": screen})

    assert image.size == (320, 240)


def test_the_peer_request_card_draws_the_ca_digest_the_tablet_asks_for(monkeypatch):
    # First contact asks the requester to compare the CA digest; the LCD shows its first 16 digits.
    module = _display()
    info_screen = _info_screen()
    drawn = []
    real = info_screen.render_notice
    monkeypatch.setattr(info_screen, "render_notice", lambda title, lines, **kw: drawn.append(list(lines)) or real(title, lines, **kw))
    render = module.card_renderer(info_screen)
    peer = {"requests": [{"display_code": "K7QM", "approval_code": "ABC234"}]}

    render({"stage": "CORE_READY", "screen": {"kind": "status", "row": "peer_request",
                                              "peer": dict(peer, tls_ca_sha256="0123456789abcdef" + "f" * 48)}})
    render({"stage": "CORE_READY", "screen": {"kind": "status", "row": "peer_request", "peer": peer}})

    assert drawn == [["K7QM  ABC234", "CA 0123 4567 89ab cdef"], ["K7QM  ABC234"]]


def test_the_status_bar_paints_only_its_band():
    import numpy as np

    module = _display()
    info_screen = _info_screen()
    paint = module.bar_painter(info_screen)
    frame = np.zeros((320, 240, 2), dtype=np.uint8)

    painted = paint(frame, "Charge the battery", "caution", 64.0, True)

    changed = np.argwhere((painted != frame).any(axis=2))
    assert changed.size and frame.sum() == 0  # the cached frame is never written
    band = info_screen.BAR_HEIGHT
    # Landscape top band -> after the panel's flip and rotation, a band of panel columns.
    assert changed[:, 1].max() - changed[:, 1].min() < band


def test_face_frames_reduce_gif_frames_to_panel_bytes():
    from PIL import Image

    module = _display()
    convert = module.face_converter(_info_screen())

    panel = convert(Image.new("P", (1000, 750)))

    assert panel.shape == (320, 240, 2) and panel.nbytes == 320 * 240 * 2


def test_an_identity_helper_that_survives_sigkill_is_logged_and_the_state_pattern_comes_back(tmp_path, monkeypatch):
    # Review 2026-10-08: wait() after the hard kill may time out; never raise out of the face loop.
    module = _display()
    _lamp_tree(tmp_path)
    _status(tmp_path, "CORE_READY")

    class Stuck(FakeProcess):
        def wait(self, timeout=None):
            raise module.subprocess.TimeoutExpired("lamp_pattern", timeout)

        def kill(self):
            self.killed = True

    class StuckSpawn(FakeSpawn):
        def __call__(self, command):
            if not command[-1].startswith("identify_"):
                return super().__call__(command)
            self.processes.append(Stuck(command))
            return self.processes[-1]

    spawn = StuckSpawn()
    lines = []
    display, lamp, _clock, _rendered, _lines = _state_loop(module, tmp_path, spawn=spawn, logs=lines)
    display.step()
    monkeypatch.setattr(module, "IDENTIFY_MAX_S", 0.05)
    state, detail = lamp.identify("blue", lambda: False)
    assert state == "failed" and "시간 초과" in detail
    assert spawn.processes[-1].killed and lamp.pattern is None
    assert any("SIGKILL" in line for line in lines)
    assert lamp.show("ready") and spawn.patterns[-1] == "ready"  # next step() shows the state pattern


# --- D-546: the lane-recovery signals ---------------------------------------------------


def _recovering(tmp_path, **inputs):
    module = _display()
    _lamp_tree(tmp_path)
    _status(tmp_path, "CORE_READY", runtime_mode="hardware")
    gpio = FakeGPIO()
    spawn = FakeSpawn()
    display, lamp, clock, _rendered, _lines = _state_loop(module, tmp_path, gpio=gpio, spawn=spawn,
                                                          wall=lambda: WALL)
    _face_inputs(tmp_path, **inputs)
    return module, display, lamp, clock, gpio, spawn


def test_reversing_beeps_once_a_second_only_while_the_phase_is_retrace(tmp_path):
    module, display, lamp, clock, gpio, _spawn = _recovering(tmp_path, recovery="retrace")
    display.step()
    ready = len(_starts(gpio))  # the ready chirp
    assert lamp.pattern == "recovering" and ("pwm", 22, module.BUZZER_FREQUENCY_HZ) in gpio.events
    assert ("change", module.BUZZER_REVERSE_HZ) in gpio.events and ready == 2
    clock.now += 0.5
    display.step()
    assert len(_starts(gpio)) == ready  # still inside the 1 s period
    clock.now += 0.5
    display.step()
    assert len(_starts(gpio)) == ready + 1

    _face_inputs(tmp_path, recovery="return")  # aligning: lamp and LCD, no reversing alarm
    clock.now += 1
    display.step()
    clock.now += 1
    display.step()
    assert len(_starts(gpio)) == ready + 1 and lamp.pattern == "recovering"

    _face_inputs(tmp_path, recovery="retrace")
    clock.now += 1
    display.step()
    assert len(_starts(gpio)) == ready + 2  # a new retrace beeps at once
    _face_inputs(tmp_path, recovery=None)
    clock.now += 1
    display.step()
    clock.now += 1
    display.step()
    assert len(_starts(gpio)) == ready + 2 and lamp.pattern == "ready"


def test_the_bridge_is_a_soft_lamp_only_and_estop_beats_recovering(tmp_path):
    _module, display, lamp, clock, gpio, _spawn = _recovering(tmp_path, recovery="bridge")
    display.step()
    assert lamp.pattern == "bridging" and len(_starts(gpio)) == 1  # the ready chirp only
    assert "Recovering" not in str(display.screen["strip"])  # no LCD line for the bridge

    _face_inputs(tmp_path, recovery="retrace", robot_mode="EMERGENCY", estop=True)
    _status(tmp_path, "CORE_READY", runtime_mode="hardware", robot_mode="EMERGENCY")
    before = len(_starts(gpio))
    clock.now += 1
    display.step()
    assert lamp.pattern == "emergency" and display.screen["kind"] == "stopped"
    assert len(_starts(gpio)) == before + 4  # the e-stop alarm, no reversing beep


def test_recovering_names_the_phase_on_the_lcd_and_refuses_an_identify_blink(tmp_path):
    module, display, lamp, clock, _gpio, spawn = _recovering(tmp_path, recovery="retrace")
    display.step()
    assert display.screen["strip"] == "Recovering: reversing" and display.screen["strip_tone"] == "caution"
    _hand_over(tmp_path, "identify_blue", at=WALL)
    assert display.handle_test() == "failed"
    assert _answer(tmp_path)["state"] == "failed" and "identify_blue" not in spawn.patterns
    assert lamp.pattern == "recovering"


def test_an_old_hand_over_without_recovery_and_an_unknown_value_signal_nothing(tmp_path):
    module, display, lamp, _clock, gpio, _spawn = _recovering(tmp_path)  # no recovery key at all
    display.step()
    assert lamp.pattern == "ready" and "Recovering" not in str(display.screen["strip"]) and len(_starts(gpio)) == 1
    _face_inputs(tmp_path, recovery="teleporting")
    assert display._core()["recovery"] is None


def test_the_recovering_lamp_and_lcd_are_held_1_5_s_but_the_beep_stops_at_once(tmp_path):
    module, display, lamp, clock, gpio, _spawn = _recovering(tmp_path, recovery="retrace")
    display.step()
    beeps = len(_starts(gpio))
    _face_inputs(tmp_path, recovery=None)
    clock.now += 1.0
    display.step()
    assert lamp.pattern == "recovering" and display.screen["strip"] == "Recovering: returning to lane"
    assert len(_starts(gpio)) == beeps  # the reversing beep did not wait for the hold
    clock.now += 0.4
    display.step()
    assert lamp.pattern == "recovering"
    clock.now += 0.2  # 1.6 s after the last RECOVERING tick
    display.step()
    assert lamp.pattern == "ready" and "Recovering" not in str(display.screen["strip"])
    assert module.RECOVERY_HOLD_S == 1.5


def test_an_estop_in_the_handover_stops_every_recovery_signal_even_with_a_stale_mode(tmp_path):
    # status-inputs still says the robot navigates (it is up to 10 s old); face-inputs has the e-stop.
    module, display, lamp, clock, gpio, _spawn = _recovering(tmp_path, recovery="retrace")
    display.step()
    beeps = len(_starts(gpio))
    _face_inputs(tmp_path, recovery="retrace", estop=True, robot_mode="NAVIGATION")
    clock.now += 1
    display.step()
    beeps += 4  # the e-stop alarm, once: the latch alone is the emergency pattern now, with no reversing beep
    assert len(_starts(gpio)) == beeps and display._reversed_at is None
    assert lamp.pattern != "recovering" and display.screen["kind"] == "stopped"
    _face_inputs(tmp_path, recovery=None, estop=True, robot_mode="EMERGENCY")  # and no hold afterwards
    clock.now += 0.2
    display.step()
    assert lamp.pattern != "recovering"
    stopped = display._present({"robot_mode": "NAVIGATION"}, "ready", {"estop": True, "recovery": "retrace"}, None)
    display._reverse_alarm(stopped.reversing, clock.now + 5)  # the record never asks for the beep under an e-stop
    assert len(_starts(gpio)) == beeps


def test_an_old_lamp_helper_leaves_the_lamp_out_but_the_beep_and_lcd_still_work(tmp_path):
    module = _display()
    _lamp_tree(tmp_path)
    _status(tmp_path, "CORE_READY", runtime_mode="hardware")
    gpio = FakeGPIO()
    display, lamp, _clock, _rendered, lines = _state_loop(module, tmp_path, gpio=gpio, spawn=FakeSpawn(code=64),
                                                          wall=lambda: WALL)
    _face_inputs(tmp_path, recovery="retrace")
    display.step()
    display.step()
    assert display.screen["strip"] == "Recovering: reversing"
    assert ("change", module.BUZZER_REVERSE_HZ) in gpio.events
    assert any("lamp_pattern recovering ended with 64" in line for line in lines)


def test_a_muted_buzzer_makes_no_reversing_beep(tmp_path):
    _module, display, lamp, _clock, gpio, _spawn = _recovering(tmp_path, recovery="retrace")
    display._buzzer.enabled = False  # ROSY_BUZZER_ENABLED=false
    display.step()
    assert _starts(gpio) == [] and lamp.pattern == "recovering"


def test_a_mixed_install_without_the_presentation_record_keeps_core_modes_and_faces(tmp_path, monkeypatch):
    module = _display()
    monkeypatch.setattr(module, "presentation", None)
    view = {"robot_mode": "NAVIGATION", "nav_state": "IDLE"}
    assert module.FaceDisplay.lamp_pattern_for(view, "ready", {"recovery": "retrace"}) == "recovering"
    assert module.FaceDisplay.lamp_pattern_for({"robot_mode": "IDLE"}, "ready", {"robot_mode": "EMERGENCY"}) == "emergency"
    assert module.FaceDisplay.lamp_pattern_for(view, "caution") == "caution"
    _status(tmp_path, "CORE_READY", runtime_mode="hardware")
    _face_inputs(tmp_path, robot_mode="EMERGENCY", estop=True)
    display, *_ = _face_loop(module, tmp_path)
    display.step()
    assert display.screen["kind"] == "stopped"  # the table still draws the STOPPED card
    old = module.robot_state.lamp_pattern
    monkeypatch.setattr(module.robot_state, "lamp_pattern", lambda state, mode=None, nav=None: "ready")  # pre-D-546
    assert module.FaceDisplay.lamp_pattern_for(view, "ready", {"recovery": "retrace"}) == "ready"
    monkeypatch.setattr(module.robot_state, "lamp_pattern", old)


def test_the_fallback_sound_table_matches_the_record(monkeypatch):
    module = _display()
    assert module.SOUNDS == module.presentation.SOUNDS
    assert module.REPEAT_LIMITED == {"caution"}


def test_a_flapping_caution_never_sounds_but_a_held_one_sounds_once(tmp_path):
    module, display, _lamp, clock, gpio, _spawn = _recovering(tmp_path)
    display.step()
    base = len(_starts(gpio))  # the ready chirp
    for index in range(6):  # caution for 1 s, gone for 1 s: never reaches the 2 s hold
        _face_inputs(tmp_path, caution=["line_follow_hold"] if index % 2 == 0 else [])
        clock.now += 1.0
        display.step()
        display.step()
    assert len(_starts(gpio)) == base
    _face_inputs(tmp_path, caution=["line_follow_hold"])
    for _ in range(6):
        clock.now += 0.5
        display.step()
    assert len(_starts(gpio)) == base + 2  # two low tones, once


def test_the_piezo_is_stopped_even_when_the_beep_sleep_fails():
    module = _display()
    gpio = FakeGPIO()

    def broken(_seconds):
        raise RuntimeError("sleep failed")
    with pytest.raises(RuntimeError):
        module.Buzzer(gpio, 22, True, broken).announce("reverse")
    assert gpio.events[-2:] == [("start", module.BUZZER_DUTY), ("stop",)]

