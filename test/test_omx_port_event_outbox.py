"""port_event_outbox (D-996 2-3): a reading (tag id only) is kept until Fleet records it and resent unchanged."""
import sys
from datetime import datetime, timezone
from pathlib import Path

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


def test_a_reading_stays_until_fleet_records_it_and_is_resent_unchanged(tmp_path):
    item = po.reading("conveyor_end", {"state": "read", "tag": 100}, observed_at=T)
    po.queue(item, tmp_path)
    po.queue(item.model_copy(update={"tag": 101}), tmp_path)  # the first stored bytes win
    assert po.send(Link(fail=True), tmp_path) is False and len(list(tmp_path.glob("*.json"))) == 1
    link = Link()
    assert po.send(link, tmp_path) is True
    assert link.sent == [item] and not list(tmp_path.glob("*.json"))
