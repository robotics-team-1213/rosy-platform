"""D-433: CORE's face hand-over — built by the bridge, written by host.py, read by rosy-face.

One snapshot goes through ``display.face_inputs_payload`` -> ``write_face_inputs``
-> ``face_screen.read_face_inputs`` -> ``screen_for``, so the writer and the
reader cannot drift apart. No rclpy.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from types import SimpleNamespace

import pytest

from core.bridge import display
from core_api_web.api.v1 import host as host_api
from core_common import face_screen as fs
from core_common import robot_state as rs
from core_common.protocol.schemas import DockState

NOW = datetime(2026, 10, 3, 12, 0, 0, tzinfo=timezone.utc)


def _snapshot(mode="NAVIGATION", navigation="NAVIGATING", estop=False, charging=False,
              docking_state="UNDOCKED", line_mode="OFF", line_state="OFF", activity=None):
    return SimpleNamespace(
        battery=SimpleNamespace(percent=55.55, voltage=7.81),
        battery_status=SimpleNamespace(charging=charging),
        robot_id="rosy_01",
        mode=SimpleNamespace(value=mode),
        navigation=SimpleNamespace(value=navigation),
        velocity=SimpleNamespace(linear=0.123, angular=0.0),
        docking=SimpleNamespace(state=DockState(docking_state)),
        safety=SimpleNamespace(estop=estop),
        line_follow=SimpleNamespace(mode=line_mode, state=line_state),
        hitl_requested=False,
        activity=None if activity is None else SimpleNamespace(kind=activity),
    )


def _payload(snapshot=None, *, face="happy", power="ACTIVE", wake=None, at=NOW):
    return display.face_inputs_payload(snapshot or _snapshot(), face=face, power_mode=power,
                                       wake=wake, written_at=at.isoformat())


def test_the_payload_is_what_the_reader_validates():
    payload = _payload()
    read = fs.validate_face_inputs(json.loads(json.dumps(payload)), NOW)

    assert read is not None
    assert (read["robot_mode"], read["face"], read["power_mode"]) == ("NAVIGATION", "happy", "active")
    assert read["drive"]["speed"] == 0.12 and "kind" not in read["drive"]
    assert read["battery_percent"] == 55.5
    # Every key the bridge writes is one the reader knows: nothing rides unread.
    assert set(payload) - {"schema", "written_at"} == set(read) - {"written_ts"}


def test_idle_carries_no_drive_card():
    assert _payload(_snapshot(mode="IDLE", navigation="IDLE"), face="basic")["drive"] is None


@pytest.mark.parametrize("snapshot,codes", [
    (_snapshot(line_mode="CAMERA", line_state="HOLD"), ["line_follow_hold"]),
    (_snapshot(line_mode="OFF", line_state="HOLD"), []),
    (_snapshot(line_mode="CAMERA", line_state="TRACKING"), []),
    (_snapshot(mode="DOCKING", docking_state="DOCK_FAILED"), ["dock_failed"]),
])
def test_core_only_cautions(snapshot, codes):
    assert display.face_cautions(snapshot) == codes
    assert all(code in fs.CAUTION_TEXT for code in codes)


def test_due_on_change_or_every_period():
    first = _payload()
    later = _payload(at=NOW + timedelta(seconds=0.4))
    changed = _payload(face="bored", at=NOW + timedelta(seconds=0.4))

    assert display.face_inputs_due(first, None, 0.0, None, 1.0)
    assert not display.face_inputs_due(later, first, 0.4, 0.0, 1.0)  # only the time moved
    assert display.face_inputs_due(changed, first, 0.4, 0.0, 1.0)
    assert display.face_inputs_due(later, first, 1.0, 0.0, 1.0)


def _svc(tmp_path):
    (tmp_path / "run/rosy").mkdir(parents=True)
    return SimpleNamespace(config={"hardware_probe": {
        "face_inputs_path": str(tmp_path / "run/rosy/face-inputs.json")}})


def test_written_file_round_trips_through_the_strict_reader(tmp_path):
    svc = _svc(tmp_path)
    host_api.write_face_inputs(svc, _payload())
    path = tmp_path / "run/rosy/face-inputs.json"

    read = fs.read_face_inputs(str(path), NOW + timedelta(seconds=1), owner_uid=os.stat(path).st_uid)
    answer = fs.screen_for(stage="CORE_READY", state=rs.READY, core=read, drive_since=0.0, now=1.0)

    assert answer["kind"] == fs.FACE and answer["face"] == "happy" and answer["row"] == "drive"
    assert not list((tmp_path / "run/rosy").glob(".face-inputs.*"))  # no temporary left behind


@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_written_file_is_world_readable_under_cores_umask(tmp_path):
    svc = _svc(tmp_path)
    previous = os.umask(0o027)  # rosy-core.service UMask
    try:
        host_api.write_face_inputs(svc, _payload())
    finally:
        os.umask(previous)

    assert (tmp_path / "run/rosy/face-inputs.json").stat().st_mode & 0o777 == 0o644


def test_the_file_is_never_visible_with_cores_umask_mode(tmp_path, monkeypatch):
    # Review MED4: the mode is set on the temporary file, before the rename.
    svc = _svc(tmp_path)
    seen = []
    real_replace = os.replace

    def replace(source, destination):
        seen.append(os.stat(source).st_mode & 0o777)
        real_replace(source, destination)

    monkeypatch.setattr(host_api.os, "replace", replace)
    host_api.write_face_inputs(svc, _payload())

    if os.name == "posix":
        assert seen == [0o644]
    assert len(seen) == 1 and not list((tmp_path / "run/rosy").glob(".face-inputs.*"))


def test_a_stale_file_sends_the_screen_back_to_the_status_card(tmp_path):
    svc = _svc(tmp_path)
    host_api.write_face_inputs(svc, _payload())
    read = fs.read_face_inputs(str(tmp_path / "run/rosy/face-inputs.json"), NOW + timedelta(seconds=10))

    assert read is None
    assert fs.screen_for(stage="CORE_READY", state=rs.READY, core=read)["row"] == "core_missing"


def test_an_estop_reaches_the_stopped_card(tmp_path):
    payload = _payload(_snapshot(mode="EMERGENCY", estop=True), face="sad")

    answer = fs.screen_for(stage="CORE_READY", state=rs.READY, core=fs.validate_face_inputs(payload, NOW))

    assert answer["kind"] == fs.STOPPED and answer["cause"] == "E-stop latched"


def test_a_wake_card_rides_the_handover():
    wake = display.info_payload(_snapshot(mode="IDLE"), SimpleNamespace(
        last_wake_reason="proximity", presence=SimpleNamespace(value="NEAR")),
        health="OK", address="http://rosy-01:8080", hold_s=4.0)
    read = fs.validate_face_inputs(_payload(_snapshot(mode="IDLE"), face="basic", wake=wake), NOW)

    assert read["wake"]["reason"] == "proximity"
    assert fs.screen_for(stage="CORE_READY", state=rs.READY, core=read)["row"] == "wake"


def test_bridge_cadence_is_the_shared_one():
    assert display.drive_due is fs.drive_due
    assert (display.DRIVE_EVERY_S, display.DRIVE_HOLD_S) == (fs.DRIVE_EVERY_S, fs.DRIVE_HOLD_S)
