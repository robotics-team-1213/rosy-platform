from __future__ import annotations

import sqlite3

import pytest

from fleet.ai.model_tool_contract import ModelToolCall, ModelToolResult
from fleet.server.proposal_store import ProposalConflict, ProposalRejected, ProposalStore
from test_er2_candidate_fence import _candidate, _setup


def _call(turn_id: str, *, arguments=None) -> ModelToolCall:
    return ModelToolCall(
        provider_call_id="provider-call-1", tool_name="propose_replan",
        arguments=(arguments or {"based_on_event_id": 3, "rationale": "still unsatisfied"}),
        turn_id=turn_id, ordinal=0,
    )


def test_tool_call_journal_returns_stored_result_for_identical_replay(tmp_path):
    db_path, _tasks, _missions, _turns, proposals, turn, _observation = _setup(tmp_path)
    call = _call(turn["turn_id"])
    first = proposals.begin_model_tool_call(call)
    assert first["state"] == "IN_PROGRESS"
    assert first["created"] is True

    result = ModelToolResult.for_call(
        call, outcome="accepted", reason_code="CANDIDATE_RECORDED", event_id=3,
        proposal_id="proposal-1", payload={"executable": False},
    )
    proposals.complete_model_tool_call(call, result=result)

    reopened = ProposalStore(db_path)
    replay = reopened.begin_model_tool_call(_call(turn["turn_id"]))
    assert replay["created"] is False
    assert replay["state"] == "COMPLETED"
    assert replay["result"] == result.to_mapping()


def test_tool_call_id_reuse_with_changed_arguments_is_a_conflict(tmp_path):
    _db, _tasks, _missions, _turns, proposals, turn, _observation = _setup(tmp_path)
    first = _call(turn["turn_id"])
    proposals.begin_model_tool_call(first)

    with pytest.raises(ProposalConflict, match="provider call id reused"):
        proposals.begin_model_tool_call(_call(
            turn["turn_id"], arguments={
                "based_on_event_id": 3, "rationale": "different request",
            },
        ))


def test_restart_converts_interrupted_tool_call_to_unknown_without_replay(tmp_path):
    db_path, _tasks, _missions, _turns, proposals, turn, _observation = _setup(tmp_path)
    call = _call(turn["turn_id"])
    proposals.begin_model_tool_call(call)

    reopened = ProposalStore(db_path)
    replay = reopened.begin_model_tool_call(_call(turn["turn_id"]))
    assert replay["created"] is False
    assert replay["state"] == "UNKNOWN"
    assert replay["result"] is None


def test_candidate_effect_and_accepted_result_commit_atomically(tmp_path):
    _db, _tasks, _missions, _turns, proposals, turn, observation = _setup(tmp_path)
    call = _call(turn["turn_id"])
    proposals.begin_model_tool_call(call)

    saved = proposals.create_feedback_candidate_fenced(
        turn_id=turn["turn_id"], candidate=_candidate(
            observed_at=observation["observed_at"],
        ), observation=observation, tool_call=call,
    )
    replay = proposals.begin_model_tool_call(_call(turn["turn_id"]))

    assert saved["created"] is True
    assert replay["state"] == "COMPLETED"
    assert replay["result"]["outcome"] == "accepted"
    assert replay["result"]["proposal_id"] == saved["proposal"]["proposal_id"]
    assert replay["result"]["payload"]["executable"] is False


def test_unknown_call_result_cannot_be_replaced_by_late_candidate_result(tmp_path):
    db_path, _tasks, _missions, _turns, proposals, turn, _observation = _setup(tmp_path)
    call = _call(turn["turn_id"])
    proposals.begin_model_tool_call(call)
    reopened = ProposalStore(db_path)
    unknown = reopened.begin_model_tool_call(_call(turn["turn_id"]))
    assert unknown["state"] == "UNKNOWN"

    with pytest.raises(ProposalConflict, match="unknown tool call outcome"):
        reopened.complete_model_tool_call(
            call, result=ModelToolResult.for_call(
                call, outcome="accepted", reason_code="CANDIDATE_RECORDED",
                payload={"executable": False},
            ),
        )


def test_result_persistence_failure_rolls_back_candidate_and_leaves_no_retry(tmp_path):
    db_path, _tasks, _missions, _turns, proposals, turn, observation = _setup(tmp_path)
    call = _call(turn["turn_id"])
    proposals.begin_model_tool_call(call)
    with sqlite3.connect(db_path) as db:
        db.execute("""
            CREATE TRIGGER fail_tool_result BEFORE UPDATE OF state
            ON fleet_model_tool_call_results WHEN NEW.state='COMPLETED'
            BEGIN SELECT RAISE(ABORT, 'injected result persistence failure'); END
        """)

    with pytest.raises(sqlite3.IntegrityError, match="injected result persistence failure"):
        proposals.create_feedback_candidate_fenced(
            turn_id=turn["turn_id"], candidate=_candidate(
                observed_at=observation["observed_at"],
            ), observation=observation, tool_call=call,
        )

    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM fleet_proposals").fetchone()[0] == 0
        assert db.execute(
            "SELECT state FROM fleet_model_tool_call_results WHERE turn_id=?",
            (turn["turn_id"],),
        ).fetchone()[0] == "IN_PROGRESS"
    proposals.mark_model_tool_call_unknown(call)
    assert ProposalStore(db_path).begin_model_tool_call(_call(turn["turn_id"]))["state"] == "UNKNOWN"


def test_late_candidate_result_after_stop_is_rejected_and_journaled(tmp_path):
    db_path, tasks, _missions, _turns, proposals, turn, observation = _setup(tmp_path)
    call = _call(turn["turn_id"])
    proposals.begin_model_tool_call(call)
    tasks.trip_stop_latch(actor_id="operator-1", reason="STOP_BEFORE_RESULT")

    with pytest.raises(ProposalRejected, match="STOP_FENCE_CLOSED"):
        proposals.create_feedback_candidate_fenced(
            turn_id=turn["turn_id"], candidate=_candidate(
                observed_at=observation["observed_at"],
            ), observation=observation, tool_call=call,
        )
    proposals.complete_model_tool_call(
        call, result=ModelToolResult.for_call(
            call, outcome="rejected", reason_code="STOP_FENCE_CLOSED", payload={},
        ),
    )

    replay = ProposalStore(db_path).begin_model_tool_call(_call(turn["turn_id"]))
    assert replay["state"] == "COMPLETED"
    assert replay["result"]["outcome"] == "rejected"
    assert replay["result"]["reason_code"] == "STOP_FENCE_CLOSED"
    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM fleet_proposals").fetchone()[0] == 0
