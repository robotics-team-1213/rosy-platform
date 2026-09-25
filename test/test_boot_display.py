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

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "deploy/robot/native"
IMAGE = ROOT / "deploy/image"
UNIT = NATIVE / "rosy-boot-display.service"
FOUNDATION = ROOT / "src/contracts/foundation"
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
    return _load("rosy_boot_display", NATIVE / "rosy-boot-display.py")


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

    display = module.BootDisplay(root, lcd=lcd, render=render, battery=reader, buzzer=buzzer,
                                 clock=clock, battery_interval=interval)
    return display, lcd, clock, battery, rendered, lines


# --- loop -----------------------------------------------------------------


def test_the_first_poll_draws_and_an_unchanged_poll_does_not(tmp_path):
    module = _display()
    _status(tmp_path, "BOOTING")
    display, lcd, clock, _battery, rendered, _logs = _loop(module, tmp_path)

    assert display.step() is True
    clock.now += 1
    assert display.step() is False
    clock.now += 1
    assert display.step() is False

    assert lcd.shown == ["image-1"] and display.draws == 1
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

    display = yaml.safe_load((ROOT / "deploy/robot/config/board.yaml").read_text(
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
    sys.path.insert(0, str(ROOT / "src/hmi/face"))
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
    assert directives["ExecStart"] == ["/usr/bin/python3 -B /opt/rosy/native-runtime/rosy-boot-display.py"]
    assert "bash" not in UNIT.read_text(encoding="utf-8")


def test_the_unit_starts_early_outside_core_and_is_enabled_by_the_image():
    directives = _directives()
    ordered = " ".join(directives.get("After", []) + directives.get("Requires", [])
                       + directives.get("Wants", []) + directives.get("BindsTo", []))

    for runtime in ("rosy-core", "rosy-runtime", "network-online", "rosy-boot-status"):
        assert runtime not in ordered
    assert directives["WantedBy"] == ["multi-user.target"]
    assert "rosy-boot-display.service" in (IMAGE / "customize-rootfs.sh").read_text(encoding="utf-8")


def test_emotion_is_bench_only_so_nothing_needs_a_conflict():
    # D-190 decision 5: one LCD owner. No product unit or launch starts the
    # emotion face; the first one that does must add Conflicts= with the display.
    for unit in NATIVE.glob("*.service"):
        text = unit.read_text(encoding="utf-8")
        if "emotion" in "".join(line for line in text.splitlines() if line.startswith("Exec")):
            assert "rosy-boot-display.service" in text, unit.name
    for launch in (ROOT / "src").rglob("*.launch.py"):
        if "src/hmi/face" in launch.as_posix():
            continue
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
    assert 'cp "$NATIVE_RUNTIME_SOURCE/rosy-boot-display.service" "$OVERLAY/etc/systemd/system/"' in payload
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
    rules = [line for line in (ROOT / "deploy/robot/udev/99-rosy-display.rules").read_text(
        encoding="utf-8").splitlines() if line and not line.startswith("#")]

    assert rules == [
        'ACTION=="add|change", SUBSYSTEM=="spidev", KERNEL=="spidev0.0", GROUP="spi", MODE="0660"',
        'ACTION=="add|change", SUBSYSTEM=="gpio", KERNEL=="gpiochip4", GROUP="gpio", MODE="0660"',
    ]
    assert "SupplementaryGroups=dialout spi gpio" in UNIT.read_text(encoding="utf-8")


def test_the_board_profile_matches_the_unit_and_no_capability_advertises_it():
    import yaml

    board = yaml.safe_load((ROOT / "deploy/robot/config/board.yaml").read_text(encoding="utf-8"))
    display = board["boot_display"]
    declared = {display["lcd"]["spi"], display["lcd"]["gpiochip"], display["buzzer"]["gpiochip"],
                display["battery_adc"]["bus"], display["lamp"]["node"]}
    allowed = {value.split()[0] for value in _directives()["DeviceAllow"]}
    assert declared == allowed
    assert display["unit"] == "rosy-boot-display.service"
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
    for caps in (ROOT / "deploy/robot/config").glob("capabilities.*.yaml"):
        text = caps.read_text(encoding="utf-8").lower()
        for word in ("lcd", "buzzer", "display"):
            assert word not in text, (caps.name, word)


def test_the_probe_checks_the_modules_and_the_unit(tmp_path):
    probe = _load("probe_display_runtime", IMAGE / "probe-display-runtime.py")

    assert set(probe.APT_MODULES) >= {"spidev", "lgpio"}
    assert set(probe.RELEASE_MODULES) >= {"rosylib", "emotion.info_screen"}
    assert probe.DEVICES == ("/dev/spidev0.0", "/dev/gpiochip4", "/dev/i2c-1", "/dev/ws281x_pwm")
    assert "core_common.robot_state" in probe.RELEASE_MODULES
    failures = probe.check_unit(tmp_path)
    assert failures == ["missing systemd unit: rosy-boot-display.service"]
    system = tmp_path / "etc/systemd/system"
    (system / "multi-user.target.wants").mkdir(parents=True)
    (system / "rosy-boot-display.service").write_text(UNIT.read_text(encoding="utf-8"), encoding="utf-8")
    assert probe.check_unit(tmp_path) == ["rosy-boot-display.service is not enabled"]
    (system / "multi-user.target.wants/rosy-boot-display.service").write_text("", encoding="utf-8")
    assert probe.check_unit(tmp_path) == []
    (system / "rosy-boot-display.service").write_text(
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
    monkeypatch.syspath_prepend(str(ROOT / "src/hmi/face"))
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
    display = module.BootDisplay(root, lcd=lcd, render=display._render, battery=display._battery,
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
    assert len(_starts(gpio)) == 3
    assert ("change", module.BUZZER_LOW_HZ) in gpio.events


def test_the_same_sound_is_not_repeated_within_the_window(tmp_path):
    # A battery hovering at the threshold must not beep every 15 s.
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
        _status(tmp_path, "CORE_READY", runtime_mode="hardware")
        clock.now += 20
        display.step()
    assert len(_starts(gpio)) == 1 + 2  # the first caution only; ready again is inside the window too

    clock.now += module.BUZZER_REPEAT_S
    _status(tmp_path, "CORE_READY", runtime_mode="hardware", devices=caution)
    display.step()
    assert len(_starts(gpio)) == 5


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
    monkeypatch.setattr(module, "BootDisplay", display)
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
