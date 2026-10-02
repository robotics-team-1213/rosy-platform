"""D-411 A: CORE's recording guard — owner, link loss, seat change, stale recorder."""

import json

import pytest

from core_common.domain.pilot_recording import LINK_GRACE_S, PilotRecordingGuard, RecordingRefused

RID = "20261002T101500Z_rosy_01"


def status(state="recording", rid=RID, reason=""):
    return {"schema": "rosy.pilot.recording.status/1", "state": state,
            "id": rid if state in ("recording", "stopping") else None, "elapsed_s": 1.0,
            "bytes": 10, "max_duration_s": 600, "quota_free_bytes": 100, "last_stop_reason": reason}


class Events:
    def __init__(self):
        self.published = []

    def publish(self, type_, severity="info", source="", data=None):
        self.published.append((type_, data))


@pytest.fixture
def rig():
    t = [0.0]
    events = Events()
    guard = PilotRecordingGuard(events=events, clock=lambda: t[0])
    calls = []

    def request(on, wait):
        calls.append((on, wait))
        return True, json.dumps({"code": "", "status": status("recording" if on else "stopping")})

    guard.request_active = request
    guard.on_status(status("idle"))
    return guard, calls, events, t


def test_start_records_the_owner_and_announces(rig):
    guard, calls, events, _ = rig
    body = guard.start("tok-a")
    assert body["state"] == "recording" and calls == [(True, True)]
    assert guard.owner() == "tok-a" and guard.active()
    assert events.published[-1] == ("recording.started", {"id": RID, "owner": "tok-a"})


def test_second_start_is_busy(rig):
    guard, *_ = rig
    guard.start("tok-a")
    with pytest.raises(RecordingRefused) as refused:
        guard.start("tok-b")
    assert (refused.value.code, refused.value.status) == ("RECORDING_BUSY", 409)


def test_start_while_the_manifest_is_still_hashing_is_busy(rig):
    guard, calls, *_ = rig
    guard.on_status(status("stopping"))
    with pytest.raises(RecordingRefused) as refused:
        guard.start("tok-a")
    assert refused.value.code == "RECORDING_BUSY" and calls == []


def test_stale_or_unwired_recorder_is_unavailable(rig):
    guard, _, _, t = rig
    t[0] = 10.0
    with pytest.raises(RecordingRefused) as refused:
        guard.start("tok-a")
    assert refused.value.code == "RECORDER_UNAVAILABLE" and refused.value.status == 503
    unwired = PilotRecordingGuard(clock=lambda: 0.0)
    unwired.on_status(status("idle"))
    with pytest.raises(RecordingRefused) as refused:
        unwired.start("tok-a")
    assert refused.value.code == "RECORDER_UNAVAILABLE"


def test_recorder_refusal_maps_quota(rig):
    guard, *_ = rig
    guard.request_active = lambda on, wait: (False, '{"code": "RECORDING_QUOTA_FULL", "status": {}}')
    with pytest.raises(RecordingRefused) as refused:
        guard.start("tok-a")
    assert (refused.value.code, refused.value.status) == ("RECORDING_QUOTA_FULL", 507)


def test_recorder_refusal_maps_disk_full(rig):
    guard, *_ = rig
    guard.request_active = lambda on, wait: (False, '{"code": "RECORDING_DISK_FULL", "status": {}}')
    with pytest.raises(RecordingRefused) as refused:
        guard.start("tok-a")
    assert (refused.value.code, refused.value.status) == ("RECORDING_DISK_FULL", 507)


def test_unanswered_request_is_unavailable(rig):
    guard, *_ = rig
    guard.request_active = lambda on, wait: (False, "")
    with pytest.raises(RecordingRefused) as refused:
        guard.start("tok-a")
    assert (refused.value.code, refused.value.status) == ("RECORDER_UNAVAILABLE", 503)
    assert guard.owner() is None


def test_only_owner_or_admin_stops(rig):
    guard, calls, events, _ = rig
    guard.start("tok-a")
    with pytest.raises(RecordingRefused) as refused:
        guard.stop("tok-b", is_admin=False)
    assert refused.value.status == 403
    guard.stop("tok-b", is_admin=True)
    assert calls[-1] == (False, True)
    assert events.published[-1] == ("recording.stopped", {"id": RID, "by": "tok-b", "reason": "operator"})


def test_stop_without_a_recording_is_not_active(rig):
    guard, *_ = rig
    with pytest.raises(RecordingRefused) as refused:
        guard.stop("tok-a", is_admin=True)
    assert (refused.value.code, refused.value.status) == ("RECORDING_NOT_ACTIVE", 409)


def test_link_loss_beyond_grace_stops_without_waiting(rig):
    guard, calls, events, t = rig
    guard.link_opened("tok-a")
    guard.start("tok-a")
    guard.link_closed("tok-a")
    guard.on_status(status())
    assert calls[-1] == (True, True)            # inside the grace: nothing yet
    t[0] += LINK_GRACE_S + 0.1
    guard.on_status(status())
    assert calls[-1] == (False, False)
    assert events.published[-1][1]["reason"] == "link_lost"


def test_reconnect_inside_grace_keeps_recording(rig):
    guard, calls, _, t = rig
    guard.link_opened("tok-a")
    guard.start("tok-a")
    guard.link_closed("tok-a")
    t[0] += 1.0
    guard.on_status(status())
    guard.link_opened("tok-a")
    t[0] += LINK_GRACE_S
    guard.on_status(status())
    assert calls == [(True, True)]


def test_another_drivers_teleop_is_a_seat_change(rig):
    guard, calls, events, _ = rig
    guard.link_opened("tok-a")
    guard.start("tok-a")
    guard.on_teleop("tok-a")
    assert calls == [(True, True)]
    guard.on_teleop("tok-b")
    assert calls[-1] == (False, False)
    assert events.published[-1][1]["reason"] == "seat_changed"


def test_recorder_side_end_clears_the_owner_once(rig):
    guard, _, events, _ = rig
    guard.start("tok-a")
    guard.on_status(status("idle", reason="max_duration"))
    assert guard.owner() is None and not guard.active()
    stopped = [e for e in events.published if e[0] == "recording.stopped"]
    assert stopped == [("recording.stopped", {"id": RID, "by": None, "reason": "max_duration"})]


def test_operator_stop_is_announced_once_through_the_hashing(rig):
    guard, _, events, _ = rig
    guard.start("tok-a")
    guard.stop("tok-a", is_admin=False)
    guard.on_status(status("stopping"))
    assert guard.active()                       # still hashing: no download, no new start
    guard.on_status(status("idle", reason="requested"))
    assert [e[0] for e in events.published].count("recording.stopped") == 1


def test_malformed_status_is_rejected(rig):
    guard, *_ = rig
    with pytest.raises(ValueError):
        guard.on_status({"state": "recording"})


def test_fetched_notice_uses_the_bridge(rig):
    guard, *_ = rig
    sent = []
    guard.publish_fetched = sent.append
    guard.fetched(RID)
    assert sent == [RID]


def test_fetched_without_a_bridge_is_inert():
    PilotRecordingGuard().fetched(RID)
