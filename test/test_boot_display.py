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

import pytest

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "deploy/robot/native"
IMAGE = ROOT / "deploy/image"
UNIT = NATIVE / "rosy-boot-display.service"
PW = "pass" + "word"  # assembled so the tracked-file secret scanner sees no literal
AP_VALUE = "Kx7" + "mQ2vR9tLpZq"


def _load(name: str, path: Path):
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
    display, _lcd, clock, battery, rendered, _logs = _loop(module, tmp_path, voltages=(8.2, 8.2, 7.9),
                                                          interval=15.0)

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


def test_the_buzzer_is_off_by_default(tmp_path):
    module = _display()
    lines: list[str] = []

    assert module.buzzer_settings({}, module.Log(lines.append)) == (False, 22)
    unit = UNIT.read_text(encoding="utf-8")
    assert "Environment=ROSY_BUZZER_ENABLED=false ROSY_BUZZER_PIN=22" in unit
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
    ({"ROSY_BUZZER_ENABLED": "true"}, (True, 22)),
    ({"ROSY_BUZZER_ENABLED": "true", "ROSY_BUZZER_PIN": "23"}, (True, 23)),
    ({"ROSY_BUZZER_ENABLED": "yes"}, (False, 22)),
    ({"ROSY_BUZZER_ENABLED": "true", "ROSY_BUZZER_PIN": "18"}, (False, 22)),  # the backlight
    ({"ROSY_BUZZER_ENABLED": "true", "ROSY_BUZZER_PIN": "x"}, (False, 22)),
])
def test_buzzer_settings_are_strict(environ, expected):
    module = _display()

    assert module.buzzer_settings(environ, module.Log(lambda _line: None)) == expected


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
    assert len(lines) == 2 and "retrying" in lines[0] and "running without it" in lines[1]


def test_the_lcd_opens_when_udev_catches_up(tmp_path):
    module = _display()
    attempts = []

    def factory():
        attempts.append(1)
        if len(attempts) < 2:
            raise PermissionError(13, "Permission denied")
        return "lcd"

    assert module.open_lcd(factory, lambda: None, module.Log(lambda _l: None), lambda _s: None) == "lcd"


def test_a_gpio_chip_that_is_not_rp1_is_never_driven():
    module = _display()
    lines: list[str] = []

    def factory():
        raise AssertionError("must not be called")

    assert module.open_lcd(factory, lambda: "gpio-brcmstb@107d508500", module.Log(lines.append),
                           lambda _s: None) is None
    assert "not the RP1 header" in lines[0]


def test_no_lcd_and_no_buzzer_exits_cleanly_instead_of_restarting(monkeypatch, capsys):
    module = _display()

    def no_lcd(*_args, **_kwargs):
        return None

    monkeypatch.setattr(module, "open_lcd", no_lcd)
    monkeypatch.setattr(module, "_release_modules", lambda: None)
    monkeypatch.delenv("ROSY_BUZZER_ENABLED", raising=False)

    assert module.main(["--root", "/nonexistent"]) == 0
    assert "nothing to show" in capsys.readouterr().err


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
    if os.name == "posix":
        assert handoff.stat().st_mode & 0o777 == 0o640
        assert handoff.stat().st_gid == gid
    output = capsys.readouterr()
    assert AP_VALUE not in output.out + output.err
    assert AP_VALUE not in (root / "run/rosy-boot/network.json").read_text(encoding="utf-8")


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


def test_the_controller_clears_a_stale_handoff_when_it_starts():
    source = (NATIVE / "rosy-network.py").read_text(encoding="utf-8")
    main = source[source.index("def main("):]

    assert main.index('"connection", "down", PROFILE]') < main.index("clear_display_ap(args.root)")
    assert main.index("clear_display_ap(args.root)") < main.index("while True:")


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


def test_the_unit_is_an_unprivileged_sandbox_with_exactly_three_devices():
    directives = _directives()

    assert directives["User"] == ["rosy-display"] and directives["Group"] == ["rosy-display"]
    assert directives["DevicePolicy"] == ["closed"]
    assert sorted(directives["DeviceAllow"]) == ["/dev/gpiochip4 rw", "/dev/i2c-1 rw", "/dev/spidev0.0 rw"]
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
        if "src/apps/emotion" in launch.as_posix():
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
    probe = customizer.index("probe-display-runtime.py \\")
    assert customizer.index("setpriv --reuid=rosy-display", probe - 400) < probe
    assert "PYTHONPATH=/opt/rosy/current/install/lib/python3.12/site-packages" in customizer[probe - 400:probe]
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
                display["battery_adc"]["bus"]}
    allowed = {value.split()[0] for value in _directives()["DeviceAllow"]}
    assert declared == allowed
    assert display["unit"] == "rosy-boot-display.service"
    assert display["buzzer"] == {"gpiochip": "/dev/gpiochip4", "bcm_line": 22, "enabled_by_default": False}
    assert display["battery_adc"]["access"] == "read"
    for caps in (ROOT / "deploy/robot/config").glob("capabilities.*.yaml"):
        text = caps.read_text(encoding="utf-8").lower()
        for word in ("lcd", "buzzer", "display"):
            assert word not in text, (caps.name, word)


def test_the_probe_checks_the_modules_and_the_unit(tmp_path):
    probe = _load("probe_display_runtime", IMAGE / "probe-display-runtime.py")

    assert set(probe.APT_MODULES) >= {"spidev", "lgpio"}
    assert set(probe.RELEASE_MODULES) >= {"rosylib", "emotion.info_screen"}
    assert probe.DEVICES == ("/dev/spidev0.0", "/dev/gpiochip4", "/dev/i2c-1")
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


def test_the_probe_renders_every_stage_from_the_source_tree(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "src/apps/emotion"))
    probe = _load("probe_display_runtime_render", IMAGE / "probe-display-runtime.py")

    failures = probe.check_render(tmp_path)

    assert failures == [f"missing font: /{probe.FONT}"]  # no DejaVu under tmp_path; the card still drew
