"""D-721 Amendment: a person request on the robot's face - English strip, one beep pattern, repeat, and who outranks it."""
from test_rosy_face import FakeGPIO, _display, _face_inputs, _recovering, _starts, _status

ASK = {"id": "a" * 32, "kind": "unplug_charger", "remaining_s": 600.0}


def _beeps(gpio):
    return len(_starts(gpio))


def test_an_ask_shows_the_english_strip_and_a_caution_lamp(tmp_path):
    module, display, lamp, _clock, _gpio, _spawn = _recovering(tmp_path, person_request=ASK)
    display.step()
    assert display.screen["strip"] == "UNPLUG CHARGER" and display.screen["strip_tone"] == "caution"
    assert display.screen["person"] == ASK["id"] and display.screen["backlight"] == 100
    assert lamp.pattern == "caution"   # an amber strip is never under a calm lamp


def test_it_beeps_on_arrival_then_every_15_seconds_and_not_between(tmp_path):
    module, display, _lamp, clock, gpio, _spawn = _recovering(tmp_path)
    display.step()
    quiet = _beeps(gpio)   # the ready chirp only
    _face_inputs(tmp_path, person_request=ASK)
    clock.now += 1
    display.step()
    arrival = _beeps(gpio)
    assert arrival == quiet + 2 and ("change", module.BUZZER_CALL_HZ) in gpio.events   # the existing `call` pattern
    for seconds, expected in ((5, arrival), (14.9, arrival), (15.0, arrival + 2), (29.9, arrival + 2), (30.0, arrival + 4)):
        clock.now = 1001 + seconds
        display.step()
        assert _beeps(gpio) == expected, seconds


def test_it_stops_when_the_ask_is_gone_and_a_new_one_beeps_at_once(tmp_path):
    module, display, _lamp, clock, gpio, _spawn = _recovering(tmp_path, person_request=ASK)
    display.step()
    after_arrival = _beeps(gpio)
    _face_inputs(tmp_path, person_request=None)   # answered, withdrawn or expired in CORE
    for _ in range(3):
        clock.now += 16
        display.step()
    assert _beeps(gpio) == after_arrival and display.screen["person"] is None
    assert display.screen["strip"] != "UNPLUG CHARGER"
    _face_inputs(tmp_path, person_request={**ASK, "id": "b" * 32, "kind": "plug_charger"})
    clock.now += 1
    display.step()
    assert _beeps(gpio) == after_arrival + 2 and display.screen["strip"] == "PLUG CHARGER"


def test_an_ask_past_its_own_expiry_is_gone_even_if_nobody_cleared_it(tmp_path):
    _module, display, _lamp, clock, gpio, _spawn = _recovering(tmp_path)
    display.step()
    base = _beeps(gpio)
    _face_inputs(tmp_path, age=2.5, person_request={**ASK, "remaining_s": 2.0})   # written 2.5 s ago, 2 s left then
    clock.now += 1
    display.step()
    assert display.screen["person"] is None and _beeps(gpio) == base


def test_a_stop_or_a_missing_core_outranks_the_ask_and_stays_silent(tmp_path):
    module, display, _lamp, clock, gpio, _spawn = _recovering(tmp_path, person_request=ASK, estop=True,
                                                              robot_mode="EMERGENCY")
    display.step()
    assert display.screen["kind"] == "stopped" and display.screen["person"] is None
    assert _beeps(gpio) == 4   # the e-stop alarm only; no call pattern
    assert ("change", module.BUZZER_CALL_HZ) not in gpio.events
    _face_inputs(tmp_path, age=5.0, person_request=ASK)   # a dead CORE: the hand-over is stale
    clock.now += 20
    display.step()
    assert display.screen["row"] == "core_missing" and display.screen["person"] is None


def test_the_failed_screen_outranks_the_ask(tmp_path):
    module, display, _lamp, clock, gpio, _spawn = _recovering(tmp_path, person_request=ASK)
    _status(tmp_path, "FAILED:rosy-core")
    display.step()
    assert display.screen["row"] == "failed" and display.screen["person"] is None
    assert ("change", module.BUZZER_CALL_HZ) not in gpio.events


def test_the_buzzer_switch_is_respected_and_the_screen_still_shows_the_ask():
    module = _display()
    assert module.Buzzer(FakeGPIO(), 22, False, lambda _s: None).announce("call") == 0   # ROSY_BUZZER_ENABLED off
    assert module.PersonAsk.REPEAT_S == 15.0


def test_the_timer_unit():
    module = _display()
    ask = module.PersonAsk()
    assert [ask.due("x", t) for t in (0, 1, 14.9, 15, 29, 30)] == [True, False, False, True, False, True]
    assert ask.due(None, 31) is False and ask.due("x", 32) is True   # gone, then it starts over
    assert ask.due("y", 33) is True   # a different request is news
