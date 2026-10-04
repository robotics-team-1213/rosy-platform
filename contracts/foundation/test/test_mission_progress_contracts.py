from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from core_common.protocol.schemas import (
    ER2ToolResult,
    MissionFeedbackContext,
    MissionFeedbackTurnScope,
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
        "stop": _axis(
            "DISPATCH_BLOCKED", source="fleet_dispatch_control",
            physical_state="UNKNOWN",
        ),
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


def _feedback_context(**overrides):
    value = {
        "mission_id": "mission-1", "workcell_id": "cell-1",
        "action_id": "action-1", "attempt_id": "attempt-1",
        "dispatch_generation": 7, "stop_generation": 7, "authority_epoch": 2,
        "snapshot_event_id": 12, "snapshot_at": "2026-09-30T12:00:00Z",
        "policy_revision": "er2-feedback-v1", "outcome_policy": "STATUS_ONLY",
        "task_summary": "Place the red block in the green tray.",
        "mission_source": "fleet_missions", "step_source": "fleet_missions",
        "action_source": "fleet_mission_events", "action_freshness": "FRESH",
        "action_observed_at": "2026-09-30T12:00:00Z",
        "goal_evidence_source": "none", "goal_evidence_freshness": "UNKNOWN",
        "goal_evidence_observed_at": None,
        "stop_source": "fleet_dispatch_control", "stop_freshness": "CURRENT",
        "stop_observed_at": "2026-09-30T12:00:00Z",
        "mission_state": "ACTION_SUCCEEDED", "step_state": "AWAITING_GOAL_EVIDENCE",
        "action_state": "ACTION_SUCCEEDED", "action_reason": None,
        "goal_evidence_state": "PENDING", "goal_evidence_reason": "EVIDENCE_PENDING",
        "stop_state": "DISPATCH_ENABLED", "stop_reason": None,
    }
    value.update(overrides)
    return value


def test_er2_feedback_context_is_explicitly_scoped_bounded_and_non_authoritative():
    from core_common.protocol.schemas import ER2_FEEDBACK_CONTEXT_MAX_BYTES

    context = MissionFeedbackContext.model_validate(_feedback_context())
    encoded = context.model_dump_json().encode("utf-8")

    assert len(encoded) <= ER2_FEEDBACK_CONTEXT_MAX_BYTES
    assert context.outcome_policy == "STATUS_ONLY"
    assert context.dispatch_generation == 7
    assert "principal_id" not in context.model_dump()
    assert "physical_action" not in context.model_dump()
    with pytest.raises(ValidationError):
        MissionFeedbackContext.model_validate(_feedback_context(
            outcome_policy="STATUS_AND_REPLAN", stop_state="STOPPED",
        ))
    with pytest.raises(ValidationError):
        MissionFeedbackContext.model_validate(_feedback_context(
            outcome_policy="STATUS_AND_REPLAN", stop_generation=6,
        ))
    with pytest.raises(ValidationError):
        MissionFeedbackContext.model_validate(_feedback_context(invented_authority=True))
    with pytest.raises(ValidationError):
        MissionFeedbackContext.model_validate(_feedback_context(
            task_summary="x" * (ER2_FEEDBACK_CONTEXT_MAX_BYTES + 1),
        ))


def test_er2_feedback_context_accepts_exact_utf8_byte_limit_and_rejects_one_over():
    import json
    from core_common.protocol.schemas import ER2_FEEDBACK_CONTEXT_MAX_BYTES

    context = MissionFeedbackContext.model_validate(_feedback_context())
    fields = context.model_dump(mode="json")
    base_size = len(json.dumps(
        fields, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8"))
    summary = fields["task_summary"]
    exact_fields = {**fields, "task_summary": summary + "x" * (
        ER2_FEEDBACK_CONTEXT_MAX_BYTES - base_size
    )}
    exact = MissionFeedbackContext.model_validate(exact_fields)

    assert len(json.dumps(
        exact.model_dump(mode="json"), sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")) == ER2_FEEDBACK_CONTEXT_MAX_BYTES
    with pytest.raises(ValidationError, match="8 KiB"):
        MissionFeedbackContext.model_validate({
            **exact_fields, "task_summary": exact_fields["task_summary"] + "x",
        })


def test_er2_trusted_turn_scope_requires_complete_identity_and_policy():
    scope = MissionFeedbackTurnScope.model_validate({
        "principal_id": "operator-1", "workcell_id": "cell-1",
        "mission_id": "mission-1", "action_id": "action-1",
        "attempt_id": "attempt-1", "dispatch_generation": 7,
        "event_watermark": 12, "model_policy_revision": "er2-feedback-v1",
        "outcome_policy": "STATUS_ONLY",
    })
    assert scope.dispatch_generation == 7
    with pytest.raises(ValidationError):
        MissionFeedbackTurnScope.model_validate({
            **scope.model_dump(), "dispatch_generation": True,
        })
    with pytest.raises(ValidationError):
        MissionFeedbackTurnScope.model_validate({
            **scope.model_dump(), "model_policy_revision": " ",
        })


def test_er2_tool_result_has_fixed_vocabulary_and_utf8_byte_limit():
    from core_common.protocol.schemas import ER2_TOOL_RESULT_MAX_BYTES

    result = ER2ToolResult.model_validate({
        "tool_name": "get_mission_status", "status": "accepted",
        "reason_code": "STATUS_CURRENT", "event_id": 12,
        "proposal_id": None, "payload": {"state": "ACTION_SUCCEEDED"},
    })
    assert len(result.model_dump_json().encode("utf-8")) <= ER2_TOOL_RESULT_MAX_BYTES
    with pytest.raises(ValidationError):
        ER2ToolResult.model_validate({
            **result.model_dump(), "status": "completed",
        })
    with pytest.raises(ValidationError):
        ER2ToolResult.model_validate({
            **result.model_dump(), "payload": {"reason": "한" * ER2_TOOL_RESULT_MAX_BYTES},
        })


def test_er2_tool_result_accepts_exact_utf8_byte_limit_and_rejects_one_over():
    import json
    from core_common.protocol.schemas import ER2_TOOL_RESULT_MAX_BYTES

    fields = {
        "tool_name": "get_mission_status", "status": "accepted",
        "reason_code": "STATUS_CURRENT", "event_id": 12,
        "proposal_id": None, "payload": {"pad": ""},
    }
    empty_size = len(json.dumps(
        fields, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8"))
    fields["payload"]["pad"] = "x" * (ER2_TOOL_RESULT_MAX_BYTES - empty_size)
    exact = ER2ToolResult.model_validate(fields)

    assert len(json.dumps(
        exact.model_dump(mode="json"), sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")) == ER2_TOOL_RESULT_MAX_BYTES
    fields["payload"]["pad"] += "x"
    with pytest.raises(ValidationError, match="4 KiB"):
        ER2ToolResult.model_validate(fields)
