"""port_event_outbox (D-996 2-3): a reading (tag id only) is kept until Fleet records it and resent unchanged."""
import sys
from datetime import datetime, timezone
from pathlib import Path
from threading import Event

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/robot/omx"))
sys.path.insert(0, str(ROOT / "contracts/foundation"))
pytest.importorskip("pydantic")
import port_event_outbox as po  # noqa: E402

T = datetime(2026, 11, 8, 3, 0, tzinfo=timezone.utc)


def test_a_point_result_becomes_a_reading_with_a_fresh_ref():
    a = po.reading("conveyor_end", {"state": "read", "tag": 100}, observed_at=T)
    b = po.reading("wrist", {"state": "unreadable"}, arm_mission_id="physical-1", observed_at=T)
    assert a.tag == 100 and b.tag is None and b.arm_mission_id == "physical-1"
    assert a.observation_ref != b.observation_ref  # a fresh ref per reading, also after a restart
    with pytest.raises(ValueError):
        po.reading("conveyor_end", {"state": "read", "tag": 100}, arm_mission_id="physical-1")


class Link:
    def __init__(self, fail=False):
        self.fail, self.sent = fail, []

    def post_intake_reading(self, item):
        if self.fail:
            raise OSError("unreachable")
        self.sent.append(item)


@pytest.mark.parametrize(("point", "identity"), [
    ("conveyor_end", {"tag": 100}),
    ("rfid_intake", {"epc": "432d35000000000000000000"}),
])
def test_a_reading_stays_until_fleet_records_it_and_is_resent_unchanged(tmp_path, point, identity):
    item = po.reading(point, {"state": "read", **identity}, observed_at=T)
    po.queue(item, tmp_path)
    po.queue(item.model_copy(update={"observed_at": datetime(2026, 11, 9, tzinfo=timezone.utc)}), tmp_path)
    assert po.send(Link(fail=True), tmp_path) is False and len(list(tmp_path.glob("*.json"))) == 1
    link = Link()
    assert po.send(link, tmp_path) is True
    assert link.sent == [item] and not list(tmp_path.glob("*.json"))


def test_concurrent_drain_does_not_fail_after_fleet_acknowledges(tmp_path):
    item = po.reading("rfid_intake", {"state": "read", "epc": "432D3100"}, observed_at=T)
    path = po.queue(item, tmp_path)

    class OtherDrain(Link):
        def post_intake_reading(self, reading):
            super().post_intake_reading(reading)
            path.unlink()

    link = OtherDrain()
    assert po.send(link, tmp_path)
    assert link.sent == [item]


def test_listener_queues_multiple_scans_and_retries_without_another_scan(tmp_path, monkeypatch):
    attempted, recovered, delivered = Event(), Event(), Event()
    monkeypatch.setattr(po, "RFID_RESEND_SECONDS", 0.02, raising=False)

    class RecoveringLink(Link):
        first = None

        def post_intake_reading(self, item):
            if not recovered.is_set():
                self.first = self.first or item
                attempted.set()
                raise OSError("offline")
            super().post_intake_reading(item)
            delivered.set()

    link = RecoveringLink()

    def inputs():
        yield "432D3100\n"
        assert attempted.wait(3), "listener did not attempt to send the first scan"
        assert len(list(tmp_path.glob("*.json"))) == 1
        recovered.set()
        assert delivered.wait(3), "listener did not retry while the reader was idle"
        yield "432D3200\n"

    assert po.listen_rfid(link, inputs(), tmp_path)
    assert [item.epc for item in link.sent] == ["432D3100", "432D3200"]
    assert link.sent[0] == link.first
    assert not list(tmp_path.glob("*.json"))


def test_listener_keeps_retrying_if_a_send_pass_hits_a_filesystem_error(tmp_path, monkeypatch):
    failed, delivered = Event(), Event()
    send = po.send
    monkeypatch.setattr(po, "RFID_RESEND_SECONDS", 0.02)

    class RecordingLink(Link):
        def post_intake_reading(self, item):
            super().post_intake_reading(item)
            delivered.set()

    def flaky_send(link, directory):
        if not failed.is_set():
            failed.set()
            raise PermissionError("outbox temporarily unavailable")
        return send(link, directory)

    def inputs():
        assert failed.wait(3), "worker did not begin sending"
        yield "432D3100\n"
        assert delivered.wait(3), "worker did not recover from the failed pass"

    link = RecordingLink()
    monkeypatch.setattr(po, "send", flaky_send)
    assert po.listen_rfid(link, inputs(), tmp_path)
    assert [item.epc for item in link.sent] == ["432D3100"]
