"""D-433 amendment (2026-10-09): lamp, status bar, expression and sound come from one record."""

from __future__ import annotations

import itertools

import pytest

from core_common import face_screen as fs
from core_common import presentation as pr
from core_common import robot_state as rs

STAGES = {rs.BOOTING: "BOOTING", rs.FAILED: "FAILED:rosy-core", rs.CAUTION: "CORE_READY",
          rs.READY_HELD: "CORE_READY", rs.READY: "CORE_READY"}


def core(**fields) -> dict:
    base = {"robot_mode": "IDLE", "nav_state": "IDLE", "estop": False, "face": "happy",
            "power_mode": "active", "activity_kind": None, "docking_state": "UNDOCKED",
            "battery_percent": 80.0, "battery_charging": False, "line_follow_mode": "OFF",
            "line_follow_state": "OFF", "caution": [], "recovery": None, "drive": None, "wake": None}
    base.update(fields)
    return base


def both(state, hand_over, **view):
    """The screen and the record for one tick, decided the way rosy-face does."""
    todo = "Charge the battery" if state == rs.CAUTION else None
    screen = fs.screen_for(stage=STAGES[state], state=state, todo=todo, core=hand_over, now=0.0)
    return screen, pr.present(state=state, core=hand_over, screen=screen, **view)


def table():
    hand_overs = [None]
    for mode, nav, estop, caution, recovery in itertools.product(
            (None, "IDLE", "MANUAL", "NAVIGATION", "DOCKING", "EMERGENCY"), (None, "NAVIGATING", "BLOCKED"),
            (False, True), ([], ["line_follow_hold"]), (None, "retrace", "return", "bridge")):
        hand_overs.append(core(robot_mode=mode, nav_state=nav, estop=estop, caution=caution, recovery=recovery))
    return itertools.product(rs.STATES, hand_overs)


def test_lamp_bar_and_expression_always_name_one_severity():
    seen = set()
    for state, hand_over in table():
        screen, record = both(state, hand_over)
        seen.add(record.lamp)
        assert record.status_level == pr.LAMP_LEVEL[record.lamp]
        if record.status_level == pr.DANGER:
            assert record.lamp in ("failed", "emergency")
        if screen["kind"] == fs.STOPPED:  # the STOPPED card and the emergency lamp are the same fact
            assert record.lamp == "emergency" and record.status_level == pr.DANGER
        if screen["row"] == "failed":
            assert record.lamp == "failed"
        if screen["kind"] == fs.FACE:
            allowed = pr.FACE_BY_LEVEL[record.status_level]
            assert allowed is None or record.expression in allowed
            if screen["strip_tone"] == "caution":  # an amber strip is never under a calm lamp
                assert record.status_level == pr.CAUTION
        else:
            assert record.expression is None
        assert record.status_text
    assert {"failed", "emergency", "recovering", "caution", "booting", "docking", "blocked", "navigating",
            "manual", "ready", "bridging"} <= seen


def test_priority_failed_then_emergency_then_recovering_then_caution():
    mid = core(robot_mode="NAVIGATION", recovery="retrace", caution=["line_follow_hold"])
    assert both(rs.READY, mid)[1].lamp == "recovering"
    assert both(rs.CAUTION, core(robot_mode="NAVIGATION"))[1].lamp == "caution"
    assert both(rs.READY, core(robot_mode="EMERGENCY", recovery="retrace"))[1].lamp == "emergency"
    assert both(rs.FAILED, core(estop=True, recovery="retrace"))[1].lamp == "failed"
    assert both(rs.READY, core(robot_mode="NAVIGATION", nav_state="BLOCKED"))[1].lamp == "blocked"


def test_a_latched_estop_is_the_emergency_pattern_even_under_a_stale_mode():
    screen, record = both(rs.READY, core(estop=True, robot_mode="NAVIGATION", recovery="retrace"))
    assert screen["kind"] == fs.STOPPED
    assert (record.lamp, record.sound, record.reversing) == ("emergency", "emergency", False)
    assert record.status_text == "E-stop latched"


def test_a_core_caution_code_lights_the_caution_lamp_with_its_strip():
    screen, record = both(rs.READY, core(caution=["dock_failed"]))
    assert record.lamp == "caution" and record.state == rs.CAUTION and record.sound == "caution"
    assert record.status_text == fs.CAUTION_TEXT["dock_failed"] == screen["strip"]


def test_recovering_says_it_on_the_bar_and_beeps_only_while_reversing():
    _screen, back = both(rs.READY, core(robot_mode="NAVIGATION", recovery="retrace"))
    assert (back.lamp, back.status_text, back.status_level, back.reversing) == (
        "recovering", "Recovering: reversing", pr.CAUTION, True)
    assert back.expression != "happy"  # a cheerful CORE face is replaced under an amber bar
    turn = both(rs.READY, core(robot_mode="NAVIGATION", recovery="return"))[1]
    assert turn.status_text == "Recovering: returning to lane" and turn.reversing is False
    bridge = both(rs.READY, core(robot_mode="NAVIGATION", recovery="bridge"))[1]
    assert bridge.lamp == "bridging" and bridge.status_level == pr.OK and "Recovering" not in bridge.status_text


def test_an_ok_state_keeps_the_face_core_chose():
    assert both(rs.READY, core(face="fun", robot_mode="MANUAL"))[1].expression == "fun"


def test_a_fleet_question_replaces_a_line_hold_and_loses_to_recovery():
    screen, record = both(rs.READY, core(robot_mode="NAVIGATION", nav_state="BLOCKED",
                                          caution=["line_follow_hold"], signal="ask", face="happy"))
    assert screen["strip"] == "?" and screen["face"] == "happy"
    assert (record.lamp, record.expression, record.status_level) == ("ask", "happy", pr.OK)
    held = both(rs.READY, core(robot_mode="NAVIGATION", caution=["line_follow_hold"]))[1]
    assert held.lamp == "caution"
    dock_screen, dock = both(rs.READY, core(caution=["dock_failed"], signal="ask"))
    assert dock.lamp == "caution" and dock_screen["strip"] == fs.CAUTION_TEXT["dock_failed"]
    back_screen, back = both(rs.READY, core(robot_mode="NAVIGATION", recovery="retrace", signal="ask",
                                             caution=["line_follow_hold"]))
    assert back.lamp == "recovering" and back_screen["strip"] == "Recovering: reversing"
    left_screen, left = both(rs.READY, core(robot_mode="NAVIGATION", signal="left", face="happy"))
    assert left_screen["strip"] == "Left" and left.lamp == "left" and left.expression == "happy"


@pytest.mark.parametrize("hand_over, view, expected", [
    (core(battery_percent=64.0, battery_charging=True), None, (64.0, True)),
    (core(battery_percent=None, battery_charging=None), None, (None, None)),  # unknown is not 0 %
    (core(battery_percent=None), 41.0, (41.0, False)),  # the ADC reading when CORE has none
    (None, 41.0, (41.0, None)),  # CORE missing: the ADC alone
    (core(battery_percent=12.0), 41.0, (12.0, False)),  # CORE's 1 s value wins
])
def test_the_battery_is_core_first_then_the_adc_and_unknown_stays_unknown(hand_over, view, expected):
    record = both(rs.READY, hand_over, battery_percent=view)[1]
    assert (record.battery_percent, record.battery_charging) == expected


def test_a_missing_core_keeps_the_files_view_and_says_so_on_a_card():
    screen = fs.screen_for(stage="CORE_READY", state=rs.READY, core=None, now=0.0)
    record = pr.present(state=rs.READY, robot_mode="NAVIGATION", core=None, screen=screen)
    assert record.status_text == "CORE not responding" and record.expression is None
    assert record.lamp == "navigating"  # the 10 s files' mode, as before; the card says CORE is gone


def test_an_old_hand_over_without_the_newer_keys_still_presents():
    old = core()
    for key in ("recovery", "battery_charging", "nav_state", "caution"):
        old.pop(key)
    screen = fs.screen_for(stage="CORE_READY", state=rs.READY, core=old, now=0.0)
    record = pr.present(state=rs.READY, core=old, screen=screen)
    assert (record.lamp, record.status_text, record.battery_charging) == ("ready", "Waiting", None)


def test_unknown_inputs_are_never_guessed():
    record = pr.present(state="nonsense", robot_mode="WARP", nav_state="??", core=None)
    assert record.state == rs.BOOTING and record.lamp == "booting" and record.sound is None


def test_light_assist_is_the_illumination_lamp():
    screen = {"kind": fs.LIGHT, "row": "light"}
    record = pr.present(state=rs.READY, core=core(), screen=screen)
    assert record.lamp == "illumination" and record.status_text == "Light"


def test_estop_failed_and_emergency_are_never_masked():
    noisy = dict(caution=["line_follow_hold", "dock_failed"], recovery="retrace", nav_state="BLOCKED")
    for mode in (None, "IDLE", "MANUAL", "NAVIGATION", "DOCKING"):  # a stale or unknown mode under a latch
        record = both(rs.CAUTION, core(estop=True, robot_mode=mode, **noisy))[1]
        assert (record.lamp, record.status_level, record.sound, record.reversing) == (
            "emergency", pr.DANGER, "emergency", False)
    for recovery in (None, "retrace", "return", "bridge"):
        record = both(rs.READY, core(robot_mode="EMERGENCY", **{**noisy, "recovery": recovery}))[1]
        assert (record.lamp, record.sound, record.reversing) == ("emergency", "emergency", False)
        failed = both(rs.FAILED, core(estop=True, robot_mode="EMERGENCY", recovery=recovery,
                                      caution=["dock_failed"]))[1]
        assert (failed.lamp, failed.status_level, failed.sound) == ("failed", pr.DANGER, "failed")
    # the files' view alone (CORE gone) also keeps EMERGENCY and FAILED on top
    assert pr.present(state=rs.READY, robot_mode="EMERGENCY", core=None).lamp == "emergency"
    assert pr.present(state=rs.FAILED, robot_mode="NAVIGATION", core=None).lamp == "failed"
    # and CORE's unknown mode does not hide the files' EMERGENCY
    assert pr.present(state=rs.READY, robot_mode="EMERGENCY", core=core(robot_mode=None)).lamp == "emergency"
