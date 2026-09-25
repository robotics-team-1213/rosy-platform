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
import time

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
    """``display`` is rosy-boot-display's ActiveState; ``answer`` its reply to a hand-over (None: real)."""

    def __init__(self, root: Path, *, display="inactive", beep_error=None, lamp=(0, ""), trusted=True,
                 answer=("done", "BCM 4 · 2 kHz · duty 10 % · 3×150 ms (부팅 표시가 울림)")) -> None:
        super().__init__(root)
        self.display = display
        self.answer = answer
        self.group = 962  # rosy-display, as on the image
        self.handoffs: list[tuple[str, str]] = []
        self.trusted = trusted
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

    def helper_trusted(self, helper):
        return self.trusted

    def display_group(self):
        return self.group

    def handoff(self, action, request_id):
        self.handoffs.append((action, request_id))
        if self.answer is None:
            return super().handoff(action, request_id)
        return self.answer

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


@pytest.mark.parametrize("env", [None, "ROSY_BUZZER_ENABLED=true\nROSY_BUZZER_PIN=4\n"])
@pytest.mark.parametrize("display", ["active"])
def test_the_buzzer_test_is_handed_to_the_boot_display_when_it_owns_the_line(tmp_path, display, env):
    # D-260 2: the display's buzzer is on by default; it plays the test, nothing beeps here.
    root = _root(tmp_path, env=env)
    _request(root)
    system = FakeSystem(root, display=display)
    result = _run(root, system)

    assert system.beeps == []
    assert system.handoffs == [("buzzer", "00112233445566778899aabb")]
    assert result["state"] == "done" and result["request_id"] == "00112233445566778899aabb"
    assert result["detail"].endswith("(부팅 표시가 울림)")


def test_a_display_without_the_buzzer_leaves_the_line_to_this_test(tmp_path):
    root = _root(tmp_path)
    _request(root)
    system = FakeSystem(root, display="active", answer=("unavailable", "부팅 표시의 부저가 꺼져 있음"))
    result = _run(root, system)

    assert system.handoffs and system.beeps == [4] and result["state"] == "done"


def test_a_display_that_does_not_answer_is_a_failure_and_nothing_is_driven(tmp_path):
    root = _root(tmp_path)
    _request(root)
    system = FakeSystem(root, display="active", answer=None)
    now = {"t": 0.0}
    system.clock = lambda: now["t"]
    system.sleep = lambda seconds: now.update(t=now["t"] + seconds)
    result = _run(root, system)

    assert result["state"] == "failed" and "답하지 않음" in result["detail"]
    assert system.beeps == [] and now["t"] >= hw.HANDOFF_WAIT_S
    assert not (root / hw.HANDOFF_REQUEST).exists()  # the hand-over is withdrawn


def test_the_hand_over_speaks_the_boot_display_s_protocol(tmp_path):
    """Both programs, one request: rosy-hw-test writes, the display plays and answers, D-247's result."""
    display = _display_module()
    root = _root(tmp_path)
    _request(root)
    system = FakeSystem(root, display="active", answer=None)
    events: list[tuple] = []

    class Pwm:
        def start(self, duty):
            events.append(("start", duty))

        def stop(self):
            events.append(("stop",))

    class Gpio:
        BCM, OUT = "BCM", "OUT"

        def setwarnings(self, flag):
            pass

        def setmode(self, mode):
            pass

        def setup(self, pin, mode):
            events.append(("setup", pin))

        def PWM(self, pin, frequency):  # noqa: N802 - RPi.GPIO API
            events.append(("pwm", pin, frequency))
            return Pwm()

    buzzer = display.Buzzer(Gpio(), 4, True, lambda _seconds: None)

    def display_poll(_seconds):
        request = display.read_test_request(root / display.TEST_REQUEST, time.time())
        assert request is not None, "the display must accept rosy-hw-test's hand-over"
        state, detail = buzzer.test()
        display.write_test_result(root / display.TEST_RESULT, json.dumps(
            {"schema": 1, "request_id": request["request_id"], "action": request["action"],
             "state": state, "detail": detail}, ensure_ascii=False) + "\n")

    system.sleep = display_poll
    result = _run(root, system)

    assert (hw.HANDOFF_REQUEST, hw.HANDOFF_RESULT) == (display.TEST_REQUEST, display.TEST_RESULT)
    assert result["state"] == "done" and result["action"] == "buzzer"
    assert result["request_id"] == "00112233445566778899aabb"
    assert [event for event in events if event[0] == "start"] == [("start", 10)] * 3
    assert ("pwm", 4, 2000) in events and system.beeps == []


@pytest.mark.parametrize("content", [
    None, "not json", json.dumps({"schema": 1, "request_id": "other", "state": "done", "detail": "x"}),
    json.dumps({"schema": 1, "request_id": "00112233445566778899aabb", "state": "busy", "detail": "x"}),
    json.dumps({"schema": 2, "request_id": "00112233445566778899aabb", "state": "done", "detail": "x"}),
    json.dumps({"schema": 1, "request_id": "00112233445566778899aabb", "state": "done", "detail": 5}),
    json.dumps({"schema": 1, "request_id": "00112233445566778899aabb", "state": "done", "detail": "x" * 2000}),
])
def test_only_the_display_s_answer_to_this_request_is_taken(tmp_path, content):
    path = tmp_path / "display-test.json"
    if content is not None:
        path.write_text(content, encoding="utf-8")

    assert hw.read_handoff_result(path, "00112233445566778899aabb") is None


def test_a_long_display_detail_is_cut_to_the_result_limit(tmp_path):
    path = tmp_path / "display-test.json"
    path.write_text(json.dumps({"schema": 1, "request_id": "00112233445566778899aabb", "state": "done",
                                "detail": "x" * 300}), encoding="utf-8")

    assert hw.read_handoff_result(path, "00112233445566778899aabb") == ("done", "x" * 200)


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


def _display_module():
    spec = importlib.util.spec_from_file_location("boot_display_for_hw_test", NATIVE / "rosy-boot-display.py")
    display = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(display)
    return display


def test_the_allow_list_is_the_boot_displays():
    display = _display_module()
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


@pytest.mark.parametrize("display", ["active"])
def test_the_lamp_test_is_handed_to_the_boot_display_while_it_shows_the_state(tmp_path, display):
    root = _root(tmp_path)
    _request(root, "lamp")
    system = FakeSystem(root, display=display,
                        answer=("done", "빨강→초록→파랑 1 s씩 · 8 LED · GPIO19 · 꺼짐 (부팅 표시가 켬)"))
    result = _run(root, system)

    assert system.handoffs == [("lamp", "00112233445566778899aabb")] and system.lamps == []
    assert result["state"] == "done" and result["detail"].endswith("(부팅 표시가 켬)")


@pytest.mark.parametrize("env,answer", [("ROSY_LAMP_ENABLED=false\n", None),
                                        (None, ("unavailable", "부팅 표시가 램프를 쓸 수 없음"))])
def test_the_lamp_is_driven_here_when_the_display_does_not_hold_it(tmp_path, env, answer):
    root = _root(tmp_path, env=env)
    _request(root, "lamp")
    system = FakeSystem(root, display="active", answer=answer or ("done", "never"))
    result = _run(root, system)

    assert system.lamps == [root / hw.LAMP_HELPER] and result["detail"].startswith("빨강→초록→파랑")
    assert (system.handoffs == []) == (answer is None)


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


def test_an_untrusted_helper_is_never_run(tmp_path):
    root = _root(tmp_path)
    _request(root, "lamp")
    system = FakeSystem(root, trusted=False)
    result = _run(root, system)
    assert system.lamps == [] and result["state"] == "unavailable"
    assert "root 소유가 아니거나" in result["detail"] and len(result["detail"]) <= 200


@pytest.mark.parametrize(("uid", "mode", "trusted"), [
    (0, stat.S_IFREG | 0o755, True),
    (0, stat.S_IFREG | 0o700, True),
    (1000, stat.S_IFREG | 0o755, False),   # not root-owned
    (0, stat.S_IFREG | 0o775, False),      # group-writable
    (0, stat.S_IFREG | 0o757, False),      # other-writable
    (0, stat.S_IFDIR | 0o755, False),      # not a regular file
])
def test_the_helper_must_be_root_owned_and_not_group_or_other_writable(tmp_path, monkeypatch, uid, mode,
                                                                        trusted):
    helper = tmp_path / "lamp_selftest"
    monkeypatch.setattr(hw.os, "stat", lambda path: os.stat_result((mode, 0, 0, 1, uid, 0, 4, 0, 0, 0)))
    assert hw.System(tmp_path).helper_trusted(helper) is trusted


def test_a_missing_helper_is_not_trusted(tmp_path):
    assert hw.System(tmp_path).helper_trusted(tmp_path / "absent") is False


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


# --- review M2 / L4: hand over only to a display that can take it ------------------


@pytest.mark.parametrize("action", ["buzzer", "lamp"])
@pytest.mark.parametrize("display", ["activating", "auto-restart", "deactivating", "reloading", None])
def test_a_display_that_is_not_active_gets_no_hand_over(tmp_path, display, action):
    root = _root(tmp_path)
    _request(root, action)
    system = FakeSystem(root, display=display)
    result = _run(root, system)

    assert system.handoffs == [] and result["state"] == "done"
    assert (system.beeps, system.lamps) == (([4], []) if action == "buzzer" else ([], [root / hw.LAMP_HELPER]))


def test_without_the_display_group_the_test_is_driven_here_and_said_once(tmp_path, capsys):
    root = _root(tmp_path)
    _request(root)
    system = FakeSystem(root, display="active")
    system.group = None
    result = _run(root, system)

    assert system.handoffs == [] and system.beeps == [4] and result["state"] == "done"
    assert capsys.readouterr().err.count("no rosy-display group") == 1


# --- review L1: one reading of the switches ------------------------------------------


@pytest.mark.parametrize("text,expected", [
    ("", (True, True)), ("ROSY_BUZZER_ENABLED=true\n", (True, True)), ('ROSY_BUZZER_ENABLED="false"\n', (False, True)),
    ("ROSY_BUZZER_ENABLED='true'\n", (True, True)), ("ROSY_BUZZER_ENABLED= false \n", (False, True)),
    ("ROSY_BUZZER_ENABLED=yes\n", (False, False)), ("ROSY_BUZZER_ENABLED=TRUE\n", (False, False)),
    ("ROSY_BUZZER_ENABLED=\n", (False, False)), ("# ROSY_BUZZER_ENABLED=false\n", (True, True)),
])
def test_the_switch_is_exact_after_quotes_and_anything_else_is_off(text, expected):
    import rosy_display_env as switch

    assert switch.flag(switch.parse_env(text), switch.BUZZER_KEY) == expected
    assert hw.buzzer_settings(text)[0] is expected[0]


@pytest.mark.parametrize("value", ["true", '"true"', "false", "'false'", "yes", "1", ""])
def test_display_hw_test_and_probe_read_the_switch_the_same_way(tmp_path, value):
    display = _display_module()
    probe_spec = importlib.util.spec_from_file_location("probe_for_switch", NATIVE / "rosy-hw-probe.py")
    probe = importlib.util.module_from_spec(probe_spec)
    sys.modules[probe_spec.name] = probe  # its dataclasses look the module up
    probe_spec.loader.exec_module(probe)
    import rosy_display_env as switch

    environ = {"ROSY_BUZZER_ENABLED": switch.unquote(value)}  # systemd strips the quotes itself
    shown = display.buzzer_settings(environ, display.Log(lambda _line: None))[0]
    tested = hw.buzzer_settings(f"ROSY_BUZZER_ENABLED={value}\n")[0]
    root = tmp_path / "root"
    (root / "etc/rosy").mkdir(parents=True)
    (root / "etc/rosy/boot-display.env").write_text(f"ROSY_BUZZER_ENABLED={value}\n", encoding="utf-8")

    class Io:
        def path(self, relative):
            return root / relative

    probed = "켜짐" in probe.Probe(Io()).buzzer().evidence
    assert shown == tested == probed
    lamp_shown = display.lamp_enabled({"ROSY_LAMP_ENABLED": switch.unquote(value)},
                                      display.Log(lambda _line: None))
    assert lamp_shown == hw.lamp_owned(f"ROSY_LAMP_ENABLED={value}\n")
