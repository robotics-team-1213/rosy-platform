from __future__ import annotations

from core_common.protocol.schemas import MissionFeedbackTurnScope
from fleet.ai.tool_dispatch import MissionFeedbackToolDispatcher
from test_mission_api import _client, _create, _resolve


def _running_mission(tmp_path):
    client, tasks, _ = _client(tmp_path)
    proposal_id = _create(client).json()["proposal"]["proposal_id"]
    mission_id = _resolve(client, proposal_id).json()["mission"]["mission_id"]
    control = tasks.store.dispatch_control()
    generation = tasks.store.rearm_dispatch(
        expected_generation=control["generation"], actor_id="operator-1",
    )["generation"]
    admitted = client.post(
        f"/api/fleet/missions/{mission_id}/admit",
        headers={"Authorization": "Bearer operator-secret"},
        json={"expected_generation": generation},
    )
    assert admitted.status_code == 200, admitted.text
    mission = admitted.json()["mission"]
    client.app.state.mission_service.start_step(
        mission_id, action_id="action-tool-test", attempt_id="attempt-tool-test",
        expected_authority_epoch=mission["authority_epoch"],
        expected_generation=generation,
    )
    return client, mission_id


def _scope(client, mission_id, *, principal_id="operator-1", workcell_id="omx_01"):
    mission = client.app.state.mission_service.get(mission_id)
    snapshot = client.app.state.mission_progress.snapshot(mission_id)
    return MissionFeedbackTurnScope.model_validate({
        "principal_id": principal_id, "workcell_id": workcell_id,
        "mission_id": mission_id, "action_id": mission["action_id"],
        "attempt_id": mission["attempt_id"],
        "dispatch_generation": mission["dispatch_generation"],
        "event_watermark": snapshot["progress"]["snapshot_event_id"],
        "model_policy_revision": "er2-feedback-test-v1",
        "outcome_policy": "STATUS_ONLY",
    })


def _dispatcher(client):
    return MissionFeedbackToolDispatcher(
        mission_service=client.app.state.mission_service,
        progress_service=client.app.state.mission_progress,
        proposal_store=client.app.state.proposal_store,
        authorization_check=lambda scope: scope.principal_id == "operator-1",
    )


def test_get_mission_status_reads_only_the_durable_turn_mission(tmp_path):
    client, mission_id = _running_mission(tmp_path)
    result = _dispatcher(client).dispatch(
        scope=_scope(client, mission_id), call_id="call-status-1",
        tool_name="get_mission_status", arguments={},
    )

    assert result.status == "accepted"
    assert result.reason_code == "STATUS_CURRENT"
    assert result.payload["mission_id"] == mission_id
    assert result.payload["action_state"] == "RUNNING"
    assert "principal_id" not in result.payload
    assert "history" not in result.payload
    assert client.app.state.mission_service.get(mission_id)["status"] == "RUNNING"


def test_tool_dispatch_denies_cross_principal_workcell_and_model_selected_ids(tmp_path):
    client, mission_id = _running_mission(tmp_path)
    dispatcher = _dispatcher(client)

    wrong_principal = dispatcher.dispatch(
        scope=_scope(client, mission_id, principal_id="other-user"),
        call_id="call-wrong-owner", tool_name="get_mission_status", arguments={},
    )
    wrong_workcell = dispatcher.dispatch(
        scope=_scope(client, mission_id, workcell_id="other-cell"),
        call_id="call-wrong-cell", tool_name="get_mission_status", arguments={},
    )
    model_selected_id = dispatcher.dispatch(
        scope=_scope(client, mission_id), call_id="call-injected-id",
        tool_name="get_mission_status", arguments={"mission_id": "other-mission"},
    )

    assert wrong_principal.reason_code == "PRINCIPAL_NOT_AUTHORIZED"
    assert wrong_workcell.reason_code == "TURN_SCOPE_FORBIDDEN"
    assert model_selected_id.reason_code == "INVALID_TOOL_ARGUMENTS"
    assert client.app.state.mission_service.get(mission_id)["status"] == "RUNNING"


def test_tool_dispatch_rejects_unknown_tools_and_replan_without_fresh_authority(tmp_path):
    client, mission_id = _running_mission(tmp_path)
    dispatcher = _dispatcher(client)
    scope = _scope(client, mission_id)

    unknown = dispatcher.dispatch(
        scope=scope, call_id="call-unknown", tool_name="submit_action", arguments={},
    )
    disallowed_replan = dispatcher.dispatch(
        scope=scope, call_id="call-replan-denied", tool_name="propose_replan",
        arguments={"observation_id": "obs-1",
                   "based_on_event_id": scope.event_watermark,
                   "rationale": "request review"},
    )
    malformed_replan = dispatcher.dispatch(
        scope=scope, call_id="call-replan-malformed", tool_name="propose_replan",
        arguments={"observation_id": "obs-1", "based_on_event_id": scope.event_watermark},
    )
    stale_replan = dispatcher.dispatch(
        scope=scope, call_id="call-replan-stale", tool_name="propose_replan",
        arguments={"observation_id": "obs-1", "based_on_event_id": 0,
                   "rationale": "request review"},
    )

    assert unknown.status == "rejected"
    assert unknown.reason_code == "TOOL_NOT_ALLOWED"
    assert unknown.tool_name == "unsupported"
    assert disallowed_replan.reason_code == "REPLAN_NOT_ALLOWED"
    assert malformed_replan.reason_code == "INVALID_TOOL_ARGUMENTS"
    assert stale_replan.reason_code == "EVENT_WATERMARK_STALE"
    assert client.app.state.mission_service.get(mission_id)["status"] == "RUNNING"
