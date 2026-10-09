"""D-433: the LCD situation table, the drive cadence and the face-inputs hand-over."""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path

import pytest

from core_common import face_screen as fs
from core_common import robot_state as rs

NOW = datetime(2026, 10, 3, 12, 0, 0, tzinfo=timezone.utc)


def core(**fields) -> dict:
    """A validated hand-over: an idle, awake robot unless a field says otherwise."""
    base = {"robot_mode": "IDLE", "nav_state": "IDLE", "estop": False, "face": "basic",
            "power_mode": "active", "activity_kind": None, "docking_state": "UNDOCKED",
            "battery_percent": 80.0, "battery_charging": False, "line_follow_mode": "OFF",
            "line_follow_state": "OFF", "caution": [], "drive": None, "wake": None}
    base.update(fields)
    return base


READY = {"stage": "CORE_READY", "state": rs.READY}
PEER = {"requests": [{"display_code": "K7QM", "approval_code": "ABC234"}]}
DRIVE = {"mode": "NAVIGATION", "speed": 0.12}


# --- every row of the table, alone ---------------------------------------------------

ROW_CASES = [
    # (row id, kind, inputs)
    ("shutdown", fs.SHUTDOWN, {**READY, "core": core(), "shutting_down": True}),
    ("failed", fs.STATUS, {"stage": "FAILED:rosy-core", "state": rs.FAILED}),
    ("update", fs.UPDATE, {**READY, "core": core(), "update": {"release": "2026.10.03-027"}}),
    ("stopped", fs.STOPPED, {**READY, "core": core(robot_mode="EMERGENCY", estop=True)}),
    ("ap", fs.STATUS, {**READY, "core": core(), "ap_mode": True}),
    ("booting", fs.STATUS, {"stage": "BOOTING", "state": rs.BOOTING}),
    ("booting", fs.STATUS, {"stage": "PROVISIONED", "state": rs.BOOTING}),
    ("booting", fs.STATUS, {"stage": "SETUP", "state": rs.CAUTION}),
    ("core_missing", fs.STATUS, {**READY, "core": None}),
    ("login", fs.STATUS, {**READY, "core": core(), "login": "code"}),
    ("peer_request", fs.STATUS, {**READY, "core": core(), "peer": PEER}),
    ("face", fs.FACE, {**READY, "core": core()}),
    ("wake", fs.FACE, {**READY, "core": core(wake={"reason": "PROXIMITY", "hold_s": 4.0})}),
    ("drive", fs.FACE, {**READY, "core": core(robot_mode="NAVIGATION", face="happy", drive=DRIVE),
                        "drive_since": 0.0, "now": 1.0}),
    ("standby", fs.SLEEP, {**READY, "core": core(power_mode="standby")}),
]


@pytest.mark.parametrize("row,kind,inputs", ROW_CASES)
def test_each_row_alone(row, kind, inputs):
    answer = fs.screen_for(**inputs)

    assert (answer["row"], answer["kind"]) == (row, kind)
    assert answer["kind"] in fs.KINDS


def test_status_cards_hide_the_face():
    for row, kind, inputs in ROW_CASES:
        answer = fs.screen_for(**inputs)
        if kind != fs.FACE:
            assert answer["face"] is None and answer["overlay"] is None, row


# --- priority: each status row beats every lower one ------------------------------------

#: Inputs that turn one row on, layered so every lower row is also on.
LAYERS = [
    ("shutdown", {"shutting_down": True}),
    ("failed", {"state": rs.FAILED, "stage": "FAILED:rosy-io"}),
    ("update", {"update": {"release": "r"}}),
    ("stopped", {"core": core(robot_mode="EMERGENCY", estop=True)}),
    ("ap", {"ap_mode": True}),
    ("peer_request", {"peer": PEER}),
    ("login", {"login": "code"}),
]


@pytest.mark.parametrize("index", range(len(LAYERS)))
def test_a_row_beats_every_row_below(index):
    inputs = {**READY, "core": core(robot_mode="NAVIGATION", drive=DRIVE), "drive_since": 0.0, "now": 1.0}
    for _row, layer in reversed(LAYERS[index:]):
        inputs.update(layer)

    assert fs.screen_for(**inputs)["row"] == LAYERS[index][0]


def test_stopped_needs_a_fresh_core_and_beats_ap_and_login():
    stopped = core(robot_mode="EMERGENCY", estop=False)
    answer = fs.screen_for(**READY, core=stopped, ap_mode=True, login="code")

    assert answer["kind"] == fs.STOPPED
    assert answer["cause"] == "Emergency stop" and answer["release"] == fs.STOP_RELEASE
    assert fs.screen_for(**READY, core=core(estop=True))["cause"] == "E-stop latched"
    # A stale hand-over is no hand-over: the last EMERGENCY does not linger.
    assert fs.screen_for(**READY, core=None)["row"] == "core_missing"


def test_ap_card_outlives_core_ready_and_core_loss():
    assert fs.screen_for(**READY, core=None, ap_mode=True)["row"] == "ap"
    assert fs.screen_for(stage="BOOTING", state=rs.BOOTING, ap_mode=True)["row"] == "ap"


def test_failed_beats_a_booting_stage_and_update():
    answer = fs.screen_for(stage="BOOTING", state=rs.FAILED, update={"release": "r"})

    assert answer["row"] == "failed"


def test_core_missing_names_core():
    assert fs.screen_for(**READY, core=None)["line"] == fs.CORE_MISSING_LINE


def test_peer_request_card_needs_a_live_core_and_carries_the_codes():
    assert fs.screen_for(**READY, core=None, peer=PEER)["row"] == "core_missing"
    assert fs.screen_for(**READY, core=core(), peer=PEER)["peer"] == PEER


def _row(**fields):
    return {"display_code": "K7QM", "approval_code": "ABC234",
            "expires_at": (NOW + timedelta(seconds=300)).isoformat(), **fields}


def _approval(tmp_path, *rows, **fields):
    path = tmp_path / "approval.json"
    path.write_text(json.dumps({"requests": list(rows) or [_row(**fields)]}), encoding="utf-8")
    return str(path)


def test_peer_approval_reader_is_strict(tmp_path):
    assert fs.read_peer_approval(_approval(tmp_path), NOW) == PEER
    assert fs.read_peer_approval(str(tmp_path / "missing.json"), NOW) is None
    for change in ({"expires_at": NOW.isoformat()}, {"expires_at": "2026-10-03T12:05:00"},
                   {"approval_code": "ABC2O4"}, {"display_code": "K7QMX"}, {"padding": "x" * 2100}):
        assert fs.read_peer_approval(_approval(tmp_path, **change), NOW) is None, change
    # Several live requests keep CORE's order; a bad or expired entry drops alone; four is malformed.
    second = _row(display_code="M2NP", approval_code="XYZ789")
    assert fs.read_peer_approval(_approval(tmp_path, second, _row(approval_code="bad"), _row()), NOW) == {
        "requests": [{"display_code": "M2NP", "approval_code": "XYZ789"}, PEER["requests"][0]]}
    assert fs.read_peer_approval(_approval(tmp_path, *[_row()] * 4), NOW) is None
    (tmp_path / "approval.json").write_text('{"display_code": "K7QM"}', encoding="utf-8")
    assert fs.read_peer_approval(str(tmp_path / "approval.json"), NOW) is None
    if hasattr(os, "getuid"):
        assert fs.read_peer_approval(_approval(tmp_path), NOW, owner_uid=os.getuid() + 1) is None


def test_peer_approval_reader_passes_only_a_well_formed_ca_digest(tmp_path):
    # The LCD draws the CA digest a first-contact requester compares; anything else is dropped.
    path = tmp_path / "approval.json"
    for ca, kept in (("ab" * 32, True), ("AB" * 32, False), ("ab" * 31, False), (7, False)):
        path.write_text(json.dumps({"requests": [_row()], "tls_ca_sha256": ca}), encoding="utf-8")
        expected = dict(PEER, tls_ca_sha256=ca) if kept else PEER
        assert fs.read_peer_approval(str(path), NOW) == expected, ca
    # A digest alone shows no card.
    path.write_text(json.dumps({"requests": [], "tls_ca_sha256": "ab" * 32}), encoding="utf-8")
    assert fs.read_peer_approval(str(path), NOW) is None


def test_burned_login_goes_to_the_face():
    assert fs.screen_for(**READY, core=core(), login="burned")["kind"] == fs.FACE


# --- rows 9-11: strips ------------------------------------------------------------------


def test_caution_is_an_amber_strip_under_the_face():
    answer = fs.screen_for(stage="CORE_READY", state=rs.CAUTION, todo="Charge the battery",
                           core=core(face="bored"))

    assert answer["kind"] == fs.FACE and answer["face"] == "bored"
    assert (answer["strip"], answer["strip_tone"]) == ("Charge the battery", "caution")


def test_core_caution_codes_make_a_strip():
    answer = fs.screen_for(**READY, core=core(caution=["line_follow_hold"]))

    assert answer["strip"] == fs.CAUTION_TEXT["line_follow_hold"] and answer["strip_tone"] == "caution"


def test_caution_beats_test_and_calibration_strips():
    inputs = {"stage": "CORE_READY", "state": rs.CAUTION, "todo": "Check the camera cable",
              "core": core(activity_kind="CALIBRATING"), "test": "lamp"}

    assert fs.screen_for(**inputs)["strip"] == "Check the camera cable"


def test_test_strip_beats_calibration():
    answer = fs.screen_for(**READY, core=core(activity_kind="CALIBRATING"), test="buzzer")

    assert answer["strip"] == "Testing buzzer" and answer["face"] == "interest"


def test_calibration_strip_and_face():
    answer = fs.screen_for(**READY, core=core(activity_kind="CALIBRATING"))

    assert (answer["face"], answer["strip"]) == ("interest", fs.CALIBRATING_STRIP)


def test_caution_strip_wakes_standby():
    answer = fs.screen_for(stage="CORE_READY", state=rs.CAUTION, todo="x", core=core(power_mode="standby"))

    assert answer["kind"] == fs.FACE and answer["awake"]


# --- rows 12-17: the face and what rides over it ---------------------------------------


@pytest.mark.parametrize("mode,face", [("MANUAL", "interest"), ("NAVIGATION", "happy"),
                                       ("DOCKING", "fun"), ("IDLE", "bored")])
def test_the_face_is_cores_choice(mode, face):
    assert fs.screen_for(**READY, core=core(robot_mode=mode, face=face))["face"] == face


def test_an_unknown_face_is_the_default():
    assert fs.screen_for(**READY, core=core(face=None))["face"] == fs.DEFAULT_FACE


@pytest.mark.parametrize("mode", ["MANUAL", "NAVIGATION", "DOCKING"])
def test_drive_card_rides_operating_modes_on_the_cadence(mode):
    inputs = {**READY, "core": core(robot_mode=mode, drive=DRIVE), "drive_since": 100.0}

    shown = [fs.screen_for(**inputs, now=100.0 + t)["row"] for t in (0.0, 4.9, 5.0, 19.9, 20.0, 24.9, 25.0)]

    assert shown == ["drive", "drive", "face", "face", "drive", "drive", "face"]
    overlay = fs.screen_for(**inputs, now=100.0)["overlay"]
    assert overlay["kind"] == "drive" and overlay["payload"]["kind"] == "drive"


def test_no_drive_card_when_idle_or_without_content():
    assert fs.screen_for(**READY, core=core(drive=DRIVE), drive_since=0.0, now=1.0)["row"] == "face"
    assert fs.screen_for(**READY, core=core(robot_mode="MANUAL"), drive_since=0.0, now=1.0)["row"] == "face"


def test_wake_card_beats_the_drive_card_and_standby():
    inputs = {**READY, "core": core(robot_mode="MANUAL", drive=DRIVE, power_mode="standby",
                                    wake={"reason": "BATTERY"}), "drive_since": 0.0, "now": 1.0}

    answer = fs.screen_for(**inputs)

    assert answer["row"] == "wake" and answer["awake"] and answer["backlight"] == 100


def test_charging_at_rest_is_a_strip():
    answer = fs.screen_for(**READY, core=core(battery_charging=True, battery_percent=63.4))

    assert answer["strip"] == "Charging 63%" and answer["strip_tone"] == "info"


@pytest.mark.parametrize("mode,nav,line", [
    ("IDLE", "IDLE", "Waiting"),
    ("MANUAL", "IDLE", "Manual"),
    ("NAVIGATION", "NAVIGATING", "Going"),
    ("NAVIGATION", "BLOCKED", "Route blocked"),
    ("NAVIGATION", "FAILED", "Navigation failed"),
    ("DOCKING", "IDLE", "Docking"),
])
def test_the_situation_line_names_the_mode_under_the_face(mode, nav, line):
    answer = fs.screen_for(**READY, core=core(robot_mode=mode, nav_state=nav, face="happy"))

    assert answer["kind"] == fs.FACE
    assert answer["strip"] == line and answer["strip_tone"] == "info"
    assert answer["face"] == "happy"


def test_a_fleet_call_names_the_robot_and_wakes_a_sleeping_panel():
    answer = fs.screen_for(**READY, core=core(power_mode="standby", robot_id="rosy_26"),
                           test="identify_blue")

    assert answer["kind"] == fs.FACE and answer["awake"] and answer["backlight"] == 100
    assert answer["strip"] == "CALL rosy_26" and answer["face"] == "basic"


def test_a_fleet_call_without_a_readable_id_still_says_call():
    answer = fs.screen_for(**READY, core=core(robot_id="Rosy 26"), test="identify_amber")

    assert answer["strip"] == "CALL" and answer["face"] == "basic"


def test_caution_and_calibration_keep_their_strip_during_a_call():
    caution = fs.screen_for(**READY, core=core(caution=["dock_failed"], robot_id="rosy_26"),
                            test="identify_blue")
    calibrating = fs.screen_for(**READY, core=core(activity_kind="CALIBRATING", robot_id="rosy_26"),
                                test="identify_blue")

    assert caution["strip"] == fs.CAUTION_TEXT["dock_failed"]
    assert calibrating["strip"] == fs.CALIBRATING_STRIP


def test_the_lcd_robot_id_pattern_matches_identity():
    from core_common.identity import ROBOT_ID_PATTERN

    assert fs._ROBOT_ID.pattern == ROBOT_ID_PATTERN.pattern


def test_idle_power_dims_the_face():
    assert fs.screen_for(**READY, core=core(power_mode="idle"))["backlight"] == fs.BACKLIGHT["idle"]


# --- the drive cadence (moved from core.bridge.display) ------------------------------------


def test_drive_due_matches_d394():
    assert not fs.drive_due("IDLE", 100.0, None)
    assert not fs.drive_due(None, 100.0, None)
    assert fs.drive_due("NAVIGATION", 100.0, None)
    assert not fs.drive_due("MANUAL", 110.0, 100.0)
    assert fs.drive_due("EMERGENCY", 120.0, 100.0)


def test_drive_window_never_before_since():
    assert not fs.drive_card_visible("MANUAL", 10.0, 9.0)
    assert not fs.drive_card_visible("MANUAL", None, 9.0)
    assert not fs.drive_card_visible("BOGUS", 0.0, 1.0)


# --- the hand-over ---------------------------------------------------------------------


def handover(**fields) -> dict:
    data = {"schema": 1, "written_at": NOW.isoformat(), "robot_mode": "NAVIGATION", "nav_state": "BLOCKED",
            "estop": False, "face": "bored", "power_mode": "active", "activity_kind": None,
            "docking_state": "UNDOCKED", "battery_percent": 55.5, "battery_charging": False,
            "line_follow_mode": "OFF", "line_follow_state": "OFF", "caution": [],
            "drive": {"mode": "NAVIGATION", "speed": 0.1, "battery_percent": 55.5}, "wake": None}
    data.update(fields)
    return data


def test_a_good_handover_validates():
    result = fs.validate_face_inputs(handover(), NOW + timedelta(seconds=1))

    assert result["robot_mode"] == "NAVIGATION" and result["face"] == "bored"
    assert result["drive"]["speed"] == 0.1


@pytest.mark.parametrize("file_age,quality_age,fresh", [(0, 0, True), (1, 1, True), (1.1, 1, False), (-1, 0, False), (0, True, False)])
@pytest.mark.parametrize("reason", ["low_light", "overexposed"])
def test_camera_quality_includes_handover_age(file_age, quality_age, fresh, reason):
    result = fs.validate_face_inputs(handover(camera_quality={"valid": False, "reason": reason},
                                              camera_quality_age_s=quality_age), NOW + timedelta(seconds=file_age))
    assert (result["camera_quality"] is not None) is fresh


def test_opt_in_light_assist_can_illuminate_idle_standby_but_preserves_priority():
    inputs = {**READY, "core": core(power_mode="standby"), "light_assist": True}
    answer = fs.screen_for(**inputs)
    assert answer["kind"] == fs.LIGHT and answer["backlight"] == 100 and answer["awake"]
    for fields in ({"estop": True}, {"battery_charging": True}, {"battery_percent": 10},
                   {"activity_kind": "CALIBRATING"}, {"robot_mode": "NAVIGATION"}, {"caution": ["line_follow_hold"]}):
        assert fs.screen_for(**{**inputs, "core": core(power_mode="standby", **fields)})["kind"] != fs.LIGHT
    assert fs.screen_for(**inputs, update={"release": "new"})["kind"] == fs.UPDATE
    assert fs.screen_for(**inputs, test="lamp")["kind"] != fs.LIGHT
    assert fs.screen_for(**{**inputs, "core": core(robot_mode="MANUAL")})["kind"] == fs.LIGHT


@pytest.mark.parametrize("age,fresh", [(0.0, True), (3.0, True), (3.01, False), (60.0, False),
                                       (-5.0, True), (-5.01, False)])
def test_freshness_boundary(age, fresh):
    result = fs.validate_face_inputs(handover(), NOW + timedelta(seconds=age))

    assert (result is not None) is fresh


@pytest.mark.parametrize("fields", [{"schema": 2}, {"schema": True}, {"schema": "1"},
                                    {"written_at": "2026-10-03T12:00:00"}, {"written_at": "yesterday"}])
def test_envelope_faults_drop_the_file(fields):
    assert fs.validate_face_inputs(handover(**fields), NOW) is None


def test_not_an_object_is_none():
    assert fs.validate_face_inputs(["schema", 1], NOW) is None


@pytest.mark.parametrize("field,value,expected", [
    ("robot_mode", "FLYING", None), ("face", "evil", None), ("face", "x" * 100, None),
    ("power_mode", "turbo", None), ("estop", "yes", None), ("battery_percent", 101, None),
    ("battery_percent", float("nan"), None), ("docking_state", "SOMEWHERE", None),
    ("caution", ["line_follow_hold", "made_up", "line_follow_hold"], ["line_follow_hold"]),
    ("caution", "line_follow_hold", []),
    ("drive", {"speed": [1, 2]}, None), ("drive", {"speed": float("inf")}, None),
    ("wake", {"k" * 100: 1}, None), ("wake", {str(n): n for n in range(40)}, None),
])
def test_a_bad_field_is_only_that_field(field, value, expected):
    result = fs.validate_face_inputs(handover(**{field: value}), NOW)

    assert result is not None and result[field] == expected
    assert result["robot_mode"] == ("NAVIGATION" if field != "robot_mode" else None)


def test_read_face_inputs_reads_a_regular_file(tmp_path):
    path = tmp_path / "face-inputs.json"
    path.write_text(json.dumps(handover()), encoding="utf-8")

    assert fs.read_face_inputs(str(path), NOW)["face"] == "bored"
    assert fs.read_face_inputs(str(path), NOW, owner_uid=os.stat(path).st_uid) is not None


def test_read_face_inputs_refuses_a_stranger(tmp_path):
    path = tmp_path / "face-inputs.json"
    path.write_text(json.dumps(handover()), encoding="utf-8")

    assert fs.read_face_inputs(str(path), NOW, owner_uid=os.stat(path).st_uid + 1) is None


def test_read_face_inputs_refuses_big_missing_and_garbage(tmp_path):
    big = tmp_path / "big.json"
    big.write_text(json.dumps(handover(pad="x" * fs.MAX_FACE_INPUTS_BYTES)), encoding="utf-8")
    garbage = tmp_path / "garbage.json"
    garbage.write_bytes(b"\xff{")

    assert fs.read_face_inputs(str(big), NOW) is None
    assert fs.read_face_inputs(str(garbage), NOW) is None
    assert fs.read_face_inputs(str(tmp_path / "missing.json"), NOW) is None


@pytest.mark.skipif(not hasattr(os, "symlink") or os.name == "nt", reason="POSIX symlinks")
def test_read_face_inputs_refuses_a_symlink(tmp_path):
    target = tmp_path / "real.json"
    target.write_text(json.dumps(handover()), encoding="utf-8")
    link = tmp_path / "face-inputs.json"
    link.symlink_to(target)

    assert fs.read_face_inputs(str(link), NOW) is None


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX FIFOs")
def test_read_face_inputs_refuses_a_fifo(tmp_path):
    fifo = tmp_path / "face-inputs.json"
    os.mkfifo(fifo)

    assert fs.read_face_inputs(str(fifo), NOW) is None


def test_module_is_standard_library_only():
    tree = ast.parse(Path(fs.__file__).read_text(encoding="utf-8"))
    imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import)
                for alias in node.names}
    imported |= {node.module.split(".")[0] for node in ast.walk(tree)
                 if isinstance(node, ast.ImportFrom) and node.module}

    assert imported <= {"__future__", "datetime", "json", "math", "os", "re", "stat", "typing", "core_common"}


# --- D-546: lane recovery ---------------------------------------------------------------


@pytest.mark.parametrize("phase,text", [("retrace", "Recovering: reversing"),
                                        ("return", "Recovering: returning to lane")])
def test_a_moving_recovery_names_its_phase_and_beats_other_strips(phase, text):
    answer = fs.screen_for(**READY, core=core(recovery=phase, caution=["line_follow_hold"]), test="lamp")

    assert (answer["strip"], answer["strip_tone"]) == (text, "caution") and text.isascii()


def test_the_bridge_has_no_lcd_line_and_an_estop_still_stops_the_screen():
    assert fs.screen_for(**READY, core=core(recovery="bridge"))["strip"] == "Waiting"
    assert fs.screen_for(**READY, core=core(recovery="retrace", estop=True))["kind"] == fs.STOPPED


@pytest.mark.parametrize("value,expected", [("retrace", "retrace"), ("bridge", "bridge"), ("spin", None),
                                            (3, None), (None, None)])
def test_recovery_is_a_known_phase_or_nothing(value, expected):
    assert fs.validate_face_inputs(handover(recovery=value), NOW)["recovery"] == expected


def test_an_old_hand_over_without_recovery_reads_as_none():
    assert fs.validate_face_inputs(handover(), NOW)["recovery"] is None
