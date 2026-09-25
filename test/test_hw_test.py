"""D-247 decision 6: the root buzzer/lamp test (rosy-hw-test) on CORE's request.

The program runs over a temporary root; the buzzer (RPi.GPIO), the lamp helper
and systemctl are methods of `System` that a fake replaces, so the tests can
assert what was not driven as well as what was.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "deploy/robot/native"
POSIX = pytest.mark.skipif(os.name != "posix", reason="symlinks and FIFOs")


def _load():
    spec = importlib.util.spec_from_file_location("rosy_hw_test", NATIVE / "rosy-hw-test.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


hw = _load()


class FakeSystem(hw.System):
    def __init__(self, root: Path, *, display="active", beep_error=None, lamp=(0, "")) -> None:
        super().__init__(root)
        self.display = display
        self.beep_error = beep_error
        self.lamp = lamp
        self.beeps: list[int] = []
        self.lamps: list[Path] = []

    def unit_state(self, unit):
        assert unit == "rosy-boot-display.service"
        return self.display

    def beep(self, pin):
        self.beeps.append(pin)
        if self.beep_error:
            raise self.beep_error

    def lamp_selftest(self, helper):
        self.lamps.append(helper)
        if isinstance(self.lamp, BaseException):
            raise self.lamp
        return self.lamp


def _root(tmp_path: Path, *, env: str | None = None, lamp_node=True, channel: str | None = "3",
          helper=True) -> Path:
    root = tmp_path / "root"
    (root / "run/rosy").mkdir(parents=True)
    (root / "run/rosy-boot").mkdir(parents=True)
    if env is not None:
        (root / "etc/rosy").mkdir(parents=True)
        (root / "etc/rosy/boot-display.env").write_text(env, encoding="utf-8")
    if lamp_node:
        (root / "dev").mkdir()
        (root / "dev/ws281x_pwm").write_bytes(b"")
    if channel is not None:
        parameters = root / "sys/module/rp1_ws281x_pwm/parameters"
        parameters.mkdir(parents=True)
        (parameters / "pwm_channel").write_text(channel + "\n", encoding="ascii")
    if helper:
        path = root / hw.LAMP_HELPER
        path.parent.mkdir(parents=True)
        path.write_bytes(b"\x7fELF")
    return root


def _request(root: Path, action="buzzer", request_id="00112233445566778899aabb", *, age_s=1.0, **override):
    at = (datetime.now(timezone.utc) - timedelta(seconds=age_s)).isoformat(timespec="seconds")
    document = {"action": action, "request_id": request_id, "requested_at": at, "by": "admin-1", **override}
    (root / hw.REQUEST).write_text(json.dumps(document), encoding="utf-8")


def _run(root: Path, system: FakeSystem) -> dict | None:
    assert hw.main(["--root", str(root)], system=system, group=lambda _name: None) == 0
    path = root / hw.RESULT
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


# --- the request ------------------------------------------------------------------


@pytest.mark.parametrize("mutate", [
    lambda doc: doc.update(action="motor"),
    lambda doc: doc.update(action="cmd_vel"),
    lambda doc: doc.update(request_id="../../etc"),
    lambda doc: doc.update(request_id=7),
    lambda doc: doc.update(extra=True),
    lambda doc: doc.pop("by"),
    lambda doc: doc.update(by="x" * 129),
    lambda doc: doc.update(requested_at="2026-09-26T05:00:00"),  # no zone
    lambda doc: doc.update(requested_at="yesterday"),
    lambda doc: doc.update(requested_at=(datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()),
])
def test_anything_but_a_fresh_exact_request_is_ignored(tmp_path, mutate):
    root = _root(tmp_path)
    document = {"action": "buzzer", "request_id": "00112233445566778899aabb", "by": "admin-1",
                "requested_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    mutate(document)
    (root / hw.REQUEST).write_text(json.dumps(document), encoding="utf-8")
    system = FakeSystem(root)

    assert _run(root, system) is None
    assert system.beeps == [] and system.lamps == []


def test_no_request_or_an_oversized_one_drives_nothing(tmp_path):
    root = _root(tmp_path)
    system = FakeSystem(root)
    assert _run(root, system) is None
    (root / hw.REQUEST).write_text(" " * (hw.MAX_REQUEST_BYTES + 1), encoding="utf-8")
    assert _run(root, system) is None
    assert system.beeps == [] and system.lamps == []


@POSIX
def test_a_symlinked_or_fifo_request_is_never_followed(tmp_path):
    root = _root(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.write_text(json.dumps({"action": "buzzer"}), encoding="utf-8")
    (root / hw.REQUEST).symlink_to(elsewhere)
    assert hw.read_request(root / hw.REQUEST) is None
    (root / hw.REQUEST).unlink()
    os.mkfifo(root / hw.REQUEST)
    assert hw.read_request(root / hw.REQUEST) is None


def test_the_same_request_runs_once(tmp_path):
    root = _root(tmp_path)
    _request(root)
    system = FakeSystem(root, display="inactive")
    _run(root, system)
    _run(root, system)
    assert system.beeps == [4]


# --- buzzer ---------------------------------------------------------------------


def test_the_buzzer_beeps_on_the_configured_pin(tmp_path):
    root = _root(tmp_path, env="ROSY_BUZZER_ENABLED=false\nROSY_BUZZER_PIN=17\n")
    _request(root)
    system = FakeSystem(root)
    result = _run(root, system)

    assert system.beeps == [17]
    assert result["state"] == "done" and result["action"] == "buzzer"
    assert result["request_id"] == "00112233445566778899aabb"
    assert result["detail"] == "BCM 17 · 2 kHz · duty 10 % · 3×150 ms"
    assert set(result) == {"schema", "request_id", "action", "state", "detail", "started_at", "finished_at"}


def test_the_buzzer_defaults_to_the_pro_pin(tmp_path):
    root = _root(tmp_path)
    _request(root)
    system = FakeSystem(root)
    _run(root, system)
    assert system.beeps == [4] == [hw.BUZZER_DEFAULT_LINE]


@pytest.mark.parametrize("display", ["active", "activating", None])
def test_the_buzzer_is_left_to_the_boot_display_when_it_owns_the_line(tmp_path, display):
    root = _root(tmp_path, env="ROSY_BUZZER_ENABLED=true\nROSY_BUZZER_PIN=4\n")
    _request(root)
    system = FakeSystem(root, display=display)
    result = _run(root, system)

    assert system.beeps == []
    assert result["state"] == "busy"
    assert "부팅 표시" in result["detail"] and "ROSY_BUZZER_ENABLED=true" in result["detail"]


@pytest.mark.parametrize("display", ["inactive", "failed"])
def test_an_enabled_buzzer_is_free_when_the_boot_display_is_down(tmp_path, display):
    root = _root(tmp_path, env="ROSY_BUZZER_ENABLED=true\n")
    _request(root)
    system = FakeSystem(root, display=display)
    assert _run(root, system)["state"] == "done"
    assert system.beeps == [4]


@pytest.mark.parametrize("pin", ["18", "19", "12", "2", "x", ""])
def test_a_pin_outside_the_display_allow_list_is_never_driven(tmp_path, pin):
    root = _root(tmp_path, env=f"ROSY_BUZZER_PIN={pin}\n")
    _request(root)
    system = FakeSystem(root)
    result = _run(root, system)
    assert system.beeps == [] and result["state"] == "unavailable"


def test_the_allow_list_is_the_boot_displays():
    spec = importlib.util.spec_from_file_location("boot_display_for_hw_test", NATIVE / "rosy-boot-display.py")
    display = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(display)
    assert hw.BUZZER_LINES == display.BUZZER_LINES
    assert hw.BUZZER_DEFAULT_LINE == display.BUZZER_DEFAULT_LINE == 4
    assert hw.BUZZER_FREQUENCY_HZ == display.BUZZER_FREQUENCY_HZ
    assert hw.BUZZER_DUTY == display.BUZZER_DUTY


def test_a_gpio_failure_is_reported_not_raised(tmp_path):
    root = _root(tmp_path)
    _request(root)
    assert _run(root, FakeSystem(root, beep_error=RuntimeError("busy")))["state"] == "failed"
    _request(root, request_id="ffeeddccbbaa99887766")
    assert _run(root, FakeSystem(root, beep_error=ImportError("RPi")))["state"] == "unavailable"


def test_the_real_beep_drives_three_short_quiet_tones(monkeypatch):
    events = []

    class FakePwm:
        def __init__(self, pin, frequency):
            events.append(("pwm", pin, frequency))

        def start(self, duty):
            events.append(("start", duty))

        def stop(self):
            events.append(("stop",))

    fake = type(sys)("RPi.GPIO")
    fake.BCM, fake.OUT, fake.LOW = "BCM", "OUT", 0
    fake.setwarnings = lambda flag: None
    fake.setmode = lambda mode: events.append(("mode", mode))
    fake.setup = lambda pin, mode, initial=None: events.append(("setup", pin, mode, initial))
    fake.PWM = FakePwm
    fake.cleanup = lambda pin=None: events.append(("cleanup", pin))
    package = type(sys)("RPi")
    package.GPIO = fake
    monkeypatch.setitem(sys.modules, "RPi", package)
    monkeypatch.setitem(sys.modules, "RPi.GPIO", fake)
    monkeypatch.setattr(hw.time, "sleep", lambda seconds: events.append(("sleep", seconds)))

    hw.System(Path("/")).beep(4)

    assert events[:3] == [("mode", "BCM"), ("setup", 4, "OUT", 0), ("pwm", 4, 2000)]
    assert [event for event in events if event[0] == "start"] == [("start", 10)] * 3
    assert [event for event in events if event[0] == "sleep"] == [("sleep", 0.15)] * 5
    assert events[-1] == ("cleanup", 4)


# --- lamp -----------------------------------------------------------------------


def test_the_lamp_runs_the_release_helper(tmp_path):
    root = _root(tmp_path)
    _request(root, "lamp")
    system = FakeSystem(root)
    result = _run(root, system)

    assert system.lamps == [root / hw.LAMP_HELPER] and system.beeps == []
    assert result["state"] == "done" and result["detail"].startswith("빨강→초록→파랑")


@pytest.mark.parametrize(("kwargs", "text"), [
    ({"lamp_node": False}, "/dev/ws281x_pwm 없음"),
    ({"channel": "2"}, "pwm_channel=2"),
    ({"channel": None}, "pwm_channel=?"),
    ({"helper": False}, "lamp_selftest 없음"),
])
def test_the_lamp_is_not_driven_without_its_driver_on_gpio19(tmp_path, kwargs, text):
    root = _root(tmp_path, **kwargs)
    _request(root, "lamp")
    system = FakeSystem(root)
    result = _run(root, system)
    assert system.lamps == [] and result["state"] == "unavailable" and text in result["detail"]


@pytest.mark.parametrize(("lamp", "text"), [
    ((2, "lamp_selftest: ws2811_init: Hardware revision is not supported"), "종료 2"),
    (subprocess.TimeoutExpired("lamp_selftest", 10), "끝나지 않음"),
    (OSError(8, "Exec format error"), "실행 실패"),
])
def test_a_failed_helper_is_reported(tmp_path, lamp, text):
    root = _root(tmp_path)
    _request(root, "lamp")
    result = _run(root, FakeSystem(root, lamp=lamp))
    assert result["state"] == "failed" and text in result["detail"]
    assert len(result["detail"]) <= 200


# --- the result file and the boundaries ---------------------------------------------


@pytest.mark.skipif(os.name != "posix", reason="POSIX modes")
def test_the_result_is_root_rosy_core_0640(tmp_path):
    root = _root(tmp_path)
    _request(root)
    groups = []
    hw.main(["--root", str(root)], system=FakeSystem(root), group=lambda name: groups.append(name) or None)
    assert groups == ["rosy-core"]
    assert stat.S_IMODE((root / hw.RESULT).stat().st_mode) == 0o640


def test_the_test_never_reaches_a_motor_cmd_vel_or_the_adc():
    source = (NATIVE / "rosy-hw-test.py").read_text(encoding="utf-8")
    code = source.split('"""', 2)[2]  # the program, not its docstring
    for forbidden in ("cmd_vel", "rosy-motor", "ttyAMA", "i2c", "dynamixel", "rclpy", "0x08"):
        assert forbidden not in code, forbidden


def test_the_wrapper_path_and_help_run_without_root(tmp_path):
    completed = subprocess.run([sys.executable, "-I", "-B", str(NATIVE / "rosy-hw-test.py"), "--help"],
                               capture_output=True, text=True, check=False)
    assert completed.returncode == 0 and "rosy-hw-test" in completed.stdout
