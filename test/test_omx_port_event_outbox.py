"""port_event_outbox (D-996 2): an identity fact becomes one port event, kept until Fleet records it, resent unchanged."""
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


def test_observed_and_failed_facts_become_the_right_kinds():
    seen = po.intake_event({"identity": "observed", "object_ref": "CNTR-1"}, workcell_id="supply",
                           intake_point="intake-A", observed_at=T)
    assert seen.kind == "container.received_at_intake" and seen.identity == "observed" and seen.matches("supply")
    failed = po.intake_event({"failed": "UNREADABLE", "object_ref": "CNTR-1"}, workcell_id="supply",
                             intake_point="intake-A", observed_at=T)
    assert failed.kind == "container.handling_failed" and failed.reason == "UNREADABLE" and failed.identity is None
    assert seen.observation_ref != failed.observation_ref  # a fresh ref per observation, also after a restart


class Link:
    def __init__(self, fail=False):
        self.fail, self.sent = fail, []

    def post_port_event(self, event):
        if self.fail:
            raise OSError("unreachable")
        self.sent.append(event)


def test_an_event_stays_until_fleet_records_it_and_is_resent_unchanged(tmp_path):
    event = po.intake_event({"identity": "observed", "object_ref": "CNTR-1"}, workcell_id="supply",
                            intake_point="intake-A", observed_at=T)
    po.queue(event, tmp_path)
    po.queue(event.model_copy(update={"intake_point": "changed"}), tmp_path)  # the first stored bytes win
    assert po.send(Link(fail=True), tmp_path) is False and len(list(tmp_path.glob("*.json"))) == 1
    link = Link()
    assert po.send(link, tmp_path) is True
    assert link.sent == [event] and not list(tmp_path.glob("*.json"))
