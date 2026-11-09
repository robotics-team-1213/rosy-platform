"""D-721 Amendment: the person request in CORE's face hand-over and the screen table."""
from datetime import datetime, timedelta, timezone

import pytest

from core_common import face_screen as fs
from core_common import presentation as pr
from core_common import robot_state as rs

WRITTEN = datetime(2026, 11, 7, 12, 0, 0, tzinfo=timezone.utc)
ASK = {"id": "a" * 32, "kind": "unplug_charger", "remaining_s": 10.0}


def hand_over(**fields):
    base = {"schema": 1, "written_at": WRITTEN.isoformat(), "robot_id": "rosy_46", "robot_mode": "IDLE",
            "nav_state": "IDLE", "estop": False, "face": "basic", "power_mode": "active", "caution": [],
            "battery_percent": 80.0, "person_request": ASK}
    base.update(fields)
    return base


def read(now_after=0.5, **fields):
    return fs.validate_face_inputs(hand_over(**fields), WRITTEN + timedelta(seconds=now_after))


READY = {"stage": "CORE_READY", "state": rs.READY}


def test_the_ask_counts_down_from_when_core_wrote_it():
    assert read(0.5)["person_request"] == {"kind": "unplug_charger", "id": "a" * 32}
    assert read(2.9)["person_request"] is not None
    # remaining 2 s, read 2.5 s later: expired although the file is still fresh (3 s)
    assert read(2.5, person_request={**ASK, "remaining_s": 2.0})["person_request"] is None


@pytest.mark.parametrize("bad", [None, "x", {}, {**ASK, "kind": "fly"}, {**ASK, "remaining_s": 0},
                                 {**ASK, "remaining_s": -3}, {**ASK, "remaining_s": 99999}, {**ASK, "id": ""},
                                 {**ASK, "remaining_s": "10"}, {**ASK, "remaining_s": True}])
def test_a_bad_ask_is_no_ask_and_does_not_drop_the_rest_of_the_hand_over(bad):
    answer = read(person_request=bad)
    assert answer is not None and answer["person_request"] is None and answer["robot_mode"] == "IDLE"


def test_an_old_hand_over_without_the_field_is_still_read():
    data = hand_over()
    del data["person_request"]
    assert fs.validate_face_inputs(data, WRITTEN)["person_request"] is None


@pytest.mark.parametrize("kind, text", [("unplug_charger", "UNPLUG CHARGER"), ("plug_charger", "PLUG CHARGER"),
                                        ("move_robot", "MOVE ROBOT"), ("clear_area", "CLEAR AREA"),
                                        ("other", "SEE CONSOLE")])
def test_each_kind_has_short_english_text_on_the_existing_caution_strip(kind, text):
    core = read(person_request={**ASK, "kind": kind})
    screen = fs.screen_for(**READY, core=core)
    assert (screen["kind"], screen["strip"], screen["strip_tone"], screen["person"]) == (fs.FACE, text, "caution", ASK["id"])
    assert text.isascii() and len(text) <= 16
    assert pr.present(state=rs.READY, core=core, screen=screen).lamp == "caution"


def test_stop_failed_update_and_boot_cards_outrank_the_ask():
    core = read(estop=True, robot_mode="EMERGENCY")
    assert fs.screen_for(**READY, core=core)["kind"] == fs.STOPPED
    ok = read()
    assert fs.screen_for(stage="FAILED:rosy-core", state=rs.FAILED, core=ok)["person"] is None
    assert fs.screen_for(**READY, core=ok, update={"release": "x"})["kind"] == fs.UPDATE
    assert fs.screen_for(stage="BOOTING", state=rs.BOOTING, core=ok)["person"] is None
    assert fs.screen_for(**READY, core=None)["person"] is None   # a dead CORE has no ask


def test_a_recovery_or_caution_strip_keeps_its_place_above_the_ask():
    core = read(recovery="retrace")
    assert fs.screen_for(**READY, core=core)["strip"] == "Recovering: reversing"
    caution = read(caution=["dock_failed"])
    assert fs.screen_for(**READY, core=caution)["strip"] == "Docking failed: check the dock"

def test_the_amber_lamp_covers_idle_and_ready_only_never_a_driving_lamp():
    ready = read()
    assert pr.present(state=rs.READY, core=ready, screen=fs.screen_for(**READY, core=ready)).lamp == "caution"
    for mode, nav in (("NAVIGATION", "NAVIGATING"), ("MANUAL", "IDLE"), ("DOCKING", "IDLE")):
        core = read(robot_mode=mode, nav_state=nav)
        screen = fs.screen_for(**READY, core=core)
        assert screen["strip"] == "UNPLUG CHARGER"   # the words still show
        record = pr.present(state=rs.READY, robot_mode=mode, nav_state=nav, core=core, screen=screen)
        assert record.lamp != "caution" and record.status_level == pr.OK, mode
