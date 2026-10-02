"""D-411 A: the recording wire contract shared by recorder, CORE and the PC tool."""

import pytest
from pydantic import ValidationError

from core_common.protocol import recording as rec


def test_constants_name_the_d411_paths_and_topics():
    assert rec.PILOT_RECORDING_ROOT == "/var/lib/rosy/pilot-recordings"
    assert rec.MAX_DURATION_S == 600
    assert rec.TELEOP_INTENT_TOPIC == "teleop/intent"
    assert rec.SET_ACTIVE_SERVICE == "pilot_recorder/set_active"
    assert rec.STATUS_TOPIC == "pilot_recorder/status"
    assert rec.ACTIVE_TOPIC == "pilot_recorder/active"
    assert rec.FETCHED_TOPIC == "pilot_recorder/fetched"


@pytest.mark.parametrize("value, ok", [
    ("20261002T101500Z_rosy_01", True),
    ("20261002T101500Z_rosy_01_2", True),
    ("../20261002T101500Z_x", False),
    ("20261002T101500Z_", False),
    ("20261002T101500Z_a/b", False),
    ("", False),
])
def test_recording_id_shape(value, ok):
    assert rec.recording_id_ok(value) is ok


@pytest.mark.parametrize("path, ok", [
    ("bag/bag_0.mcap", True),
    ("session.json", True),
    ("/etc/passwd", False),
    ("../x", False),
    ("bag/../../x", False),
    ("bag\\x", False),
    ("bag//x", False),
    ("./x", False),
    ("", False),
])
def test_safe_member_blocks_escape(path, ok):
    assert rec.safe_member(path) is ok


def test_teleop_intent_records_raw_clipped_and_decision():
    body = rec.teleop_intent(raw_linear=0.5, raw_angular=0.0, clipped=(0.15, 0.0), source="manual",
                             mode="MANUAL", accepted=True, code="", t_mono_ns=123)
    assert body == {"schema": "rosy.teleop.intent/1", "raw_linear": 0.5, "raw_angular": 0.0,
                    "linear": 0.15, "angular": 0.0, "source": "manual", "mode": "MANUAL",
                    "accepted": True, "code": "", "t_mono_ns": 123}


def test_teleop_intent_rejection_has_no_clipped_value_and_nan_becomes_null():
    body = rec.teleop_intent(raw_linear=float("nan"), raw_angular=0.1, clipped=None, source="manual",
                             mode="IDLE", accepted=False, code="MODE_CONFLICT", t_mono_ns=5)
    assert body["raw_linear"] is None and body["linear"] is None and body["angular"] is None
    assert body["accepted"] is False and body["code"] == "MODE_CONFLICT"


def test_accepted_intent_requires_clipped_values():
    with pytest.raises(ValidationError):
        rec.TeleopIntent(raw_linear=0.1, raw_angular=0.0, linear=None, angular=None, source="manual",
                         mode="MANUAL", accepted=True, code="", t_mono_ns=1)


def test_manifest_rejects_unsafe_and_duplicate_paths():
    good = {"schema": rec.MANIFEST_SCHEMA, "id": "20261002T101500Z_rosy_01",
            "started_at": "2026-10-02T10:15:00Z", "ended_at": "2026-10-02T10:16:00Z",
            "duration_s": 60.0, "topics": ["cmd_vel"], "stop_reason": "requested",
            "files": [{"path": "bag/bag_0.mcap", "bytes": 10, "sha256": "a" * 64}]}
    assert rec.RecordingManifest.model_validate(good).id == good["id"]
    for files in ([{"path": "../x", "bytes": 1, "sha256": "a" * 64}],
                  [good["files"][0], good["files"][0]]):
        with pytest.raises(ValidationError):
            rec.RecordingManifest.model_validate({**good, "files": files})


def test_manifest_records_how_the_bag_writer_ended():
    base = {"schema": rec.MANIFEST_SCHEMA, "id": "20261002T101500Z_rosy_01",
            "started_at": "2026-10-02T10:15:00Z", "ended_at": "2026-10-02T10:16:00Z",
            "duration_s": 60.0, "topics": ["cmd_vel"], "stop_reason": "requested",
            "files": [{"path": "session.json", "bytes": 10, "sha256": "a" * 64}]}
    unknown = rec.RecordingManifest.model_validate(base)
    assert unknown.bag_returncode is None and unknown.writer_killed is False
    killed = rec.RecordingManifest.model_validate({**base, "bag_returncode": -9, "writer_killed": True})
    dumped = killed.model_dump(by_alias=True)
    assert dumped["bag_returncode"] == -9 and dumped["writer_killed"] is True
    with pytest.raises(ValidationError):
        rec.RecordingManifest.model_validate({**base, "writer_killed": "yes"})


def test_recorder_status_round_trip():
    status = rec.RecorderStatus(state="recording", id="20261002T101500Z_rosy_01", elapsed_s=3.0,
                                bytes=1024, max_duration_s=600, quota_free_bytes=10)
    dumped = status.model_dump(by_alias=True)
    assert dumped["schema"] == rec.STATUS_SCHEMA
    assert rec.RecorderStatus.model_validate(dumped) == status


def test_a_starting_recorder_names_its_session():
    # starting: the writer runs but has not opened its first file yet (no data so far).
    status = rec.RecorderStatus(state="starting", id="20261002T101500Z_rosy_01", elapsed_s=0.0,
                                bytes=0, max_duration_s=600, quota_free_bytes=10)
    assert status.state == "starting"
    assert rec.ACTIVE_STATES == ("starting", "recording", "stopping")
    assert rec.STOPPABLE_STATES == ("starting", "recording")
    with pytest.raises(ValidationError):
        rec.RecorderStatus(state="starting", id=None, elapsed_s=0.0, bytes=0, max_duration_s=600,
                           quota_free_bytes=10)


def test_recorder_status_carries_a_boot_and_a_sequence():
    status = rec.RecorderStatus(state="idle", elapsed_s=0.0, bytes=0, max_duration_s=600,
                                quota_free_bytes=10)
    assert (status.boot_id, status.seq) == ("", 0)      # unsequenced: older recorders
    dumped = rec.RecorderStatus(state="idle", elapsed_s=0.0, bytes=0, max_duration_s=600,
                                quota_free_bytes=10, boot_id="b" * 32, seq=7).model_dump(by_alias=True)
    assert dumped["boot_id"] == "b" * 32 and dumped["seq"] == 7
    with pytest.raises(ValidationError):
        rec.RecorderStatus.model_validate({**dumped, "seq": -1})
