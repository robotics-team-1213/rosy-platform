from __future__ import annotations

from test_rosy_face import (
    json, os, sys, SimpleNamespace, pytest, ROOT, _display, FakeGPIO, _status,
    _login, FakeProcess, FakeSpawn, _lamp_tree, _state_loop, _starts, REQUEST_ID,
    _hand_over, _answer, WALL, _face_inputs, _face_loop, _screen_row, _peer_approval,
    _info_screen, _recovering,
)


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

    askable = {module.robot_state.lamp_pattern(state, mode, nav, recovery, signal)
               for state in module.robot_state.STATES
               for mode in [*module.robot_state.ROBOT_MODES, None]
               for nav in [*module.robot_state.NAV_STATES, None]
               for recovery in (None, "retrace", "return", "bridge")
               for signal in (None, *module.robot_state.DRIVE_SIGNALS)}

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


def test_a_quiet_identity_pulse_blinks_without_the_call_chirp(tmp_path):
    """D-596: Fleet's automatic requests ask for identify_<colour>_quiet; same blink, no beep."""
    module = _display()
    _lamp_tree(tmp_path)
    _status(tmp_path, "CORE_READY")
    spawn = FakeSpawn(code=0)
    display, lamp, _clock, _rendered, _lines = _state_loop(module, tmp_path, spawn=spawn)
    display.step()
    display._core = lambda: {"estop": False, "robot_mode": "IDLE", "nav_state": "IDLE", "caution": []}
    heard = []
    display._buzzer.announce = heard.append
    _hand_over(tmp_path, "identify_blue_quiet")
    assert display.handle_test() == "done"
    assert spawn.patterns == ["ready", "identify_blue", "ready"] and heard == []
    _hand_over(tmp_path, "identify_amber", request_id="1122334455667788")
    assert display.handle_test() == "done" and heard == ["call"]


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


@pytest.mark.parametrize("status, core, reason", [
    ({"robot_mode": "EMERGENCY"}, {"estop": False, "robot_mode": "EMERGENCY", "caution": []}, "STATE_DISPLAY"),
    ({"robot_mode": "IDLE"}, {"estop": False, "robot_mode": "IDLE", "caution": ["battery_low"]}, "CAUTION_ACTIVE"),
    ({"robot_mode": "NAVIGATION", "nav_state": "BLOCKED"},
     {"estop": False, "robot_mode": "NAVIGATION", "caution": []}, "STATE_DISPLAY"),
    ({"robot_mode": "IDLE"}, None, "CORE_UNAVAILABLE"),  # no fresh CORE hand-over
    ({"robot_mode": "IDLE"}, {"estop": True, "robot_mode": "IDLE", "caution": []}, "ESTOP"),
])
def test_identity_pulse_is_refused_while_a_safety_display_holds(tmp_path, status, core, reason):
    """D-596 rev 2026-10-10: the refusal names its reason, which CORE hands on to Fleet."""
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
    assert _answer(tmp_path)["reason"] == reason


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
    monkeypatch.setattr(sys.modules["rosy_face_parts"], "IDENTIFY_MAX_S", 0.05)
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


def test_a_dev_mode_robot_says_dev_on_the_face_and_the_card(tmp_path):
    module = _display()
    _status(tmp_path, "CORE_READY", runtime_mode="hardware")
    _face_inputs(tmp_path, face="basic")
    (tmp_path / "etc/rosy").mkdir(parents=True)
    (tmp_path / "etc/rosy/dev-mode").write_text("", encoding="ascii")
    display, _lcd, _clock, _rendered, _opened, _lines = _face_loop(module, tmp_path)

    display.step()
    assert display.animating[:2] == ("basic", "DEV Waiting")
    assert module.read_view(tmp_path, None)["state_line"].startswith("DEV ")


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
    monkeypatch.setattr(sys.modules["rosy_face_parts"], "IDENTIFY_MAX_S", 0.05)
    state, detail = lamp.identify("blue", lambda: False)
    assert state == "failed" and "시간 초과" in detail
    assert spawn.processes[-1].killed and lamp.pattern is None
    assert any("SIGKILL" in line for line in lines)
    assert lamp.show("ready") and spawn.patterns[-1] == "ready"  # next step() shows the state pattern


# --- D-546: the lane-recovery signals ---------------------------------------------------


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
    monkeypatch.setattr(sys.modules["rosy_face_display"], "presentation", None)
    view = {"robot_mode": "NAVIGATION", "nav_state": "IDLE"}
    assert module.FaceDisplay.lamp_pattern_for(view, "ready", {"recovery": "retrace"}) == "recovering"
    assert module.FaceDisplay.lamp_pattern_for(view, "ready", {"signal": "ask"}) == "ask"
    assert module.FaceDisplay.lamp_pattern_for(
        view, "ready", {"recovery": "retrace", "signal": "ask"}) == "recovering"
    assert module.FaceDisplay.lamp_pattern_for({"robot_mode": "IDLE"}, "ready", {"robot_mode": "EMERGENCY"}) == "emergency"
    assert module.FaceDisplay.lamp_pattern_for(view, "caution") == "caution"
    _status(tmp_path, "CORE_READY", runtime_mode="hardware")
    _face_inputs(tmp_path, robot_mode="EMERGENCY", estop=True)
    display, *_ = _face_loop(module, tmp_path)
    display.step()
    assert display.screen["kind"] == "stopped"  # the table still draws the STOPPED card
    old = module.robot_state.lamp_pattern

    def recovery_only(state, mode=None, nav=None, recovery=None):
        return "recovering" if recovery == "retrace" else "ready"

    monkeypatch.setattr(module.robot_state, "lamp_pattern", recovery_only)  # D-546, no turn signal yet
    assert module.FaceDisplay.lamp_pattern_for(
        view, "ready", {"recovery": "retrace", "signal": "ask"}) == "recovering"
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

