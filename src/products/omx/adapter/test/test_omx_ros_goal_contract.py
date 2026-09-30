from uuid import UUID

import pytest

from omx_adapter.ros_goal_contract import RosGoalEvent, canonical_ros_goal_id


def test_ros_goal_uuid_is_canonicalized_from_ros_uuid_bytes_or_text():
    expected = "12345678-1234-5678-1234-567812345678"

    assert canonical_ros_goal_id(bytes.fromhex("12345678123456781234567812345678")) == expected
    assert canonical_ros_goal_id(expected.upper()) == expected


@pytest.mark.parametrize("value", [b"short", b"\0" * 16, "not-a-uuid", None])
def test_invalid_or_nil_ros_goal_identity_is_rejected(value):
    with pytest.raises(ValueError):
        canonical_ros_goal_id(value)


def test_accepted_and_feedback_events_keep_one_command_phase_and_goal_identity():
    goal_id = "12345678-1234-5678-1234-567812345678"
    accepted = RosGoalEvent(
        kind="GOAL_ACCEPTED", command_id="action-1-approach", phase_id="approach",
        goal_id=goal_id, observed_at_monotonic_s=10.0, sequence=1,
    )
    feedback = RosGoalEvent(
        kind="RUNNING_FEEDBACK", command_id="action-1-approach", phase_id="approach",
        goal_id=goal_id, observed_at_monotonic_s=10.1, sequence=2, feedback_sequence=1,
    )

    assert accepted.goal_id == feedback.goal_id == goal_id
    assert accepted.command_id == feedback.command_id
    assert accepted.phase_id == feedback.phase_id == "approach"
    assert feedback.sequence > accepted.sequence


@pytest.mark.parametrize("kind, goal_id", [
    ("GOAL_ACCEPTED", None),
    ("RUNNING_FEEDBACK", None),
    ("GOAL_REJECTED", "12345678-1234-5678-1234-567812345678"),
    ("GOAL_ACCEPTANCE_UNKNOWN", "12345678-1234-5678-1234-567812345678"),
])
def test_event_kind_requires_or_forbids_accepted_goal_identity(kind, goal_id):
    with pytest.raises(ValueError, match="goal_id"):
        RosGoalEvent(
            kind=kind, command_id="cmd-1", phase_id="approach", goal_id=goal_id,
            observed_at_monotonic_s=10.0, sequence=1,
        )


def test_cancel_ack_and_terminal_events_remain_distinct_goal_bound_facts():
    goal_id = "12345678-1234-5678-1234-567812345678"
    ack = RosGoalEvent(
        kind="CANCEL_ACK", command_id="cmd-1", phase_id="grasp", goal_id=goal_id,
        observed_at_monotonic_s=10.2, sequence=3, cancel_acknowledged=True,
    )
    terminal = RosGoalEvent(
        kind="TERMINAL_RESULT", command_id="cmd-1", phase_id="grasp", goal_id=goal_id,
        observed_at_monotonic_s=10.3, sequence=4, status=5, result_code=-1,
    )

    assert ack.cancel_acknowledged is True
    assert ack.kind != terminal.kind
    assert ack.goal_id == terminal.goal_id


def test_goal_event_rejects_noncanonical_uuid_and_nonfinite_timestamp():
    with pytest.raises(ValueError, match="canonical"):
        RosGoalEvent(
            kind="GOAL_ACCEPTED", command_id="cmd-1", phase_id="approach",
            goal_id=str(UUID("12345678-1234-abcd-1234-567812345678")).upper(),
            observed_at_monotonic_s=10.0, sequence=1,
        )
    with pytest.raises(ValueError, match="observed_at"):
        RosGoalEvent(
            kind="GOAL_REJECTED", command_id="cmd-1", phase_id="approach",
            goal_id=None, observed_at_monotonic_s=float("nan"), sequence=1,
        )
