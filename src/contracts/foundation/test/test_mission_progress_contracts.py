from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from core_common.protocol.schemas import (
    MissionProgressAxis,
    MissionProgressEvent,
    MissionProgressEventPage,
    MissionProgressSnapshot,
)


def _axis(state="UNKNOWN", **overrides):
    value = {
        "state": state, "source": "none", "last_event_id": None,
        "observed_at": None, "revision": None,
        "freshness": "UNKNOWN", "reason": None,
    }
    value.update(overrides)
    return value


def test_mission_progress_snapshot_names_each_independent_truth_axis():
    snapshot = MissionProgressSnapshot.model_validate({
        "snapshot_event_id": 0, "snapshot_at": datetime.now(timezone.utc),
        "mission": _axis("PROPOSED", source="fleet_missions"),
        "step": _axis("NOT_ADMITTED", source="fleet_missions"),
        "action": _axis(), "goal_evidence": _axis(),
        "stop": _axis("DISPATCH_BLOCKED", source="fleet_dispatch_control",
                       physical_state="UNKNOWN"),
    })

    assert snapshot.stop.physical_state == "UNKNOWN"
    assert snapshot.action.state == "UNKNOWN"
    assert not hasattr(snapshot, "percent_complete")


def test_progress_contract_rejects_unbounded_axis_and_future_cursor_fields():
    with pytest.raises(ValidationError):
        MissionProgressAxis.model_validate(_axis(state="x" * 65))
    with pytest.raises(ValidationError):
        MissionProgressEventPage.model_validate({
            "snapshot_event_id": 1, "cursor_floor": 0,
            "next_after_event_id": 1, "has_more": False,
            "events": [], "invented": True,
        })


def test_mission_event_page_is_ordered_and_event_identity_is_typed():
    event = MissionProgressEvent.model_validate({
        "event_id": 8, "event_source": "fleet_mission",
        "source_event_id": "submit:attempt-1", "mission_id": "mission-1",
        "step_id": "step-1", "action_id": "action-1", "attempt_id": "attempt-1",
        "state": "RUNNING", "event_type": "STEP_SUBMITTED",
        "actor_id": "operator-1", "detail": {},
        "created_at": datetime.now(timezone.utc),
    })
    page = MissionProgressEventPage.model_validate({
        "snapshot_event_id": 8, "cursor_floor": 0,
        "next_after_event_id": 8, "has_more": False,
        "events": [event.model_dump()],
    })

    assert page.events[0].event_id == 8
    with pytest.raises(ValidationError):
        MissionProgressEvent.model_validate({
            **event.model_dump(), "event_id": True,
        })
    with pytest.raises(ValidationError):
        MissionProgressEvent.model_validate({
            **event.model_dump(), "detail": {"payload": "x" * 17_000},
        })
    unicode_event = MissionProgressEvent.model_validate({
        **event.model_dump(), "detail": {"message": "한" * 5_000},
    })
    assert len(unicode_event.detail["message"].encode("utf-8")) == 15_000
