"""SAF-005 critical on the robot's body: the screen goes dark and the buzzer asks for a charger."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
NATIVE = REPO / "deploy/robot/pinky_pro/native"
FOUNDATION = REPO / "contracts/foundation"


def _module():
    for path in (str(FOUNDATION), str(NATIVE)):
        if path not in sys.path:
            sys.path.insert(0, path)
    spec = importlib.util.spec_from_file_location("rosy_face_urgent", NATIVE / "rosy-face.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class Lcd:
    def __init__(self):
        self.calls = []

    def img_show(self, image):
        self.calls.append("draw")

    def sleep(self):
        self.calls.append("sleep")

    def wake(self):
        self.calls.append("wake")

    def set_backlight(self, value):
        self.calls.append(("backlight", value))


class Reader:
    def __init__(self, percents):
        self.percents = list(percents)

    def read(self):
        value = self.percents.pop(0) if len(self.percents) > 1 else self.percents[0]
        return None if value is None else (value, 7.3)


class Buzzer:
    def __init__(self):
        self.sounds = []

    def announce(self, sound):
        self.sounds.append(sound)


class Clock:
    now = 100.0

    def __call__(self):
        return self.now


def _rig(tmp_path, percents):
    module = _module()
    status = tmp_path / "run/rosy-boot"
    status.mkdir(parents=True)
    (status / "boot-status.json").write_text(json.dumps({"stage": "CORE_READY"}), encoding="utf-8")
    lcd, buzzer, clock = Lcd(), Buzzer(), Clock()
    display = module.FaceDisplay(tmp_path, lcd=lcd, render=lambda view: "image", battery=Reader(percents),
                                 buzzer=buzzer, clock=clock, battery_interval=15.0)
    return display, lcd, buzzer, clock


def _run(display, clock, polls):
    for _ in range(polls):
        display.step()
        clock.now += 15.0


def _urgent_beeps(buzzer):
    return buzzer.sounds.count("battery_urgent")


def test_two_low_readings_darken_the_screen_and_beep(tmp_path):
    display, lcd, buzzer, clock = _rig(tmp_path, [9.0])

    _run(display, clock, 1)
    assert _urgent_beeps(buzzer) == 0 and "sleep" not in lcd.calls  # one reading may be a motor sag

    _run(display, clock, 1)
    assert _urgent_beeps(buzzer) == 1
    assert "sleep" in lcd.calls and ("backlight", 0) in lcd.calls
    assert display.screen["kind"] == "sleep"


def test_the_beep_repeats_every_30_s_and_nothing_is_drawn(tmp_path):
    display, lcd, buzzer, clock = _rig(tmp_path, [9.0])
    _run(display, clock, 2)
    draws = lcd.calls.count("draw")

    _run(display, clock, 4)

    assert _urgent_beeps(buzzer) == 3  # 60 s of further polling
    assert lcd.calls.count("draw") == draws


def test_one_sag_does_nothing(tmp_path):
    display, lcd, buzzer, clock = _rig(tmp_path, [9.0, 40.0, 9.0, 40.0])
    _run(display, clock, 4)
    assert _urgent_beeps(buzzer) == 0 and "sleep" not in lcd.calls


def test_recovery_needs_the_margin_and_then_restores_the_screen(tmp_path):
    display, lcd, buzzer, clock = _rig(tmp_path, [9.0, 9.0, 12.0, 12.0, 14.0])
    _run(display, clock, 4)
    assert display.screen["kind"] == "sleep"  # 12% is inside the margin

    _run(display, clock, 1)
    assert display.screen["kind"] != "sleep"
    assert "wake" in lcd.calls
    beeps = _urgent_beeps(buzzer)
    _run(display, clock, 4)
    assert _urgent_beeps(buzzer) == beeps


def test_a_lost_reading_is_not_low_and_ends_the_alarm_after_a_while(tmp_path):
    display, lcd, buzzer, clock = _rig(tmp_path, [9.0, 9.0, None])
    _run(display, clock, 3)
    assert display.screen["kind"] == "sleep"  # one lost reading changes nothing

    _run(display, clock, 3)
    assert display.screen["kind"] != "sleep"


def test_no_reading_at_all_never_alarms(tmp_path):
    display, lcd, buzzer, clock = _rig(tmp_path, [None])
    _run(display, clock, 6)
    assert _urgent_beeps(buzzer) == 0 and "sleep" not in lcd.calls


def test_an_update_stays_visible(tmp_path, monkeypatch):
    display, lcd, buzzer, clock = _rig(tmp_path, [9.0])
    monkeypatch.setattr(display, "screen_of", lambda view, now: {
        "kind": "update", "row": "update", "backlight": 100, "awake": True,
        "face": None, "strip": None, "strip_tone": None, "overlay": None})
    _run(display, clock, 2)
    assert display.screen["kind"] == "update" and "sleep" not in lcd.calls


def test_the_urgent_beep_is_a_real_pattern_unlike_the_emergency_one():
    module = _module()
    urgent, emergency = module.BUZZER_PATTERNS["battery_urgent"], module.BUZZER_PATTERNS["emergency"]
    assert urgent[0] > 0 and urgent[1] != emergency[1]


def test_a_dark_panel_still_refuses_a_bench_test_during_a_stop(tmp_path, monkeypatch):
    display, lcd, buzzer, clock = _rig(tmp_path, [9.0])
    stopped = {"kind": "stopped", "row": "stopped", "backlight": 100, "awake": True,
               "face": None, "strip": None, "strip_tone": None, "overlay": None}
    monkeypatch.setattr(display, "screen_of", lambda view, now: stopped)
    _run(display, clock, 2)
    assert display.screen["kind"] == "sleep"
    assert display._table_screen["kind"] == "stopped"
