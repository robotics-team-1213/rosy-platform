from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from core_common.protocol.schemas import MissionFeedbackContext, MissionFeedbackTurnScope
from fleet.ai.candidate import ImageObservation, ImageTransform, PickPlaceProposalCandidate
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
        arguments={"based_on_event_id": scope.event_watermark,
                   "rationale": "request review"},
    )
    malformed_replan = dispatcher.dispatch(
        scope=scope, call_id="call-replan-malformed", tool_name="propose_replan",
        arguments={"based_on_event_id": scope.event_watermark},
    )
    stale_replan = dispatcher.dispatch(
        scope=scope, call_id="call-replan-stale", tool_name="propose_replan",
        arguments={"based_on_event_id": 0, "rationale": "request review"},
    )

    assert unknown.status == "rejected"
    assert unknown.reason_code == "TOOL_NOT_ALLOWED"
    assert unknown.tool_name == "unsupported"
    assert disallowed_replan.reason_code == "REPLAN_NOT_ALLOWED"
    assert malformed_replan.reason_code == "INVALID_TOOL_ARGUMENTS"
    assert stale_replan.reason_code == "EVENT_WATERMARK_STALE"
    assert client.app.state.mission_service.get(mission_id)["status"] == "RUNNING"


def test_async_replan_tool_uses_trusted_post_action_frame_and_fenced_candidate_writer():
    class MissionService:
        def get(self, _mission_id):
            return {
                "principal_id": "operator-1", "workcell_id": "omx_01",
                "action_id": "action-1", "attempt_id": "attempt-1",
                "dispatch_generation": 4, "status": "HOLD",
                "reason": "GOAL_NOT_SATISFIED",
                "plan": {"instruction": "Move the red block to the green tray"},
            }

    context = MissionFeedbackContext.model_validate({
        "mission_id": "mission-1", "workcell_id": "omx_01",
        "action_id": "action-1", "attempt_id": "attempt-1",
        "dispatch_generation": 4, "stop_generation": 4, "authority_epoch": 2,
        "snapshot_event_id": 19, "snapshot_at": "2026-09-30T12:00:00Z",
        "policy_revision": "policy-v1", "outcome_policy": "STATUS_AND_REPLAN",
        "task_summary": "Move the red block to the green tray",
        "mission_source": "fleet_missions", "step_source": "fleet_missions",
        "action_source": "fleet_mission_events", "action_freshness": "FRESH",
        "action_observed_at": "2026-09-30T12:00:00Z",
        "goal_evidence_source": "trusted-test", "goal_evidence_freshness": "FRESH",
        "goal_evidence_observed_at": "2026-09-30T12:00:01Z",
        "stop_source": "fleet_dispatch_control", "stop_freshness": "CURRENT",
        "stop_observed_at": "2026-09-30T12:00:00Z",
        "mission_state": "HOLD", "step_state": "HOLD", "action_state": "SUCCEEDED",
        "action_reason": None, "goal_evidence_state": "UNSATISFIED",
        "goal_evidence_reason": "GOAL_NOT_SATISFIED",
        "stop_state": "DISPATCH_ENABLED", "stop_reason": None,
    })

    class ProgressService:
        def snapshot(self, _mission_id):
            return {"progress": {"snapshot_event_id": 19}}

        def model_context(self, _mission_id, *, principal_id, workcell_id):
            assert (principal_id, workcell_id) == ("operator-1", "omx_01")
            return context.model_dump(mode="json")

    observed_at = datetime.now(timezone.utc).isoformat()
    image = ImageObservation(
        observation_id="obs-post-action", camera_id="camera-top", frame_id="frame-8",
        observed_at=observed_at, image_bytes=b"frame-bytes",
        image_transform=ImageTransform.identity(source_width=640, source_height=480),
        calibration_revision="cal-4", transform_revision="tf-9",
    )
    observation_scope = {
        "mission_id": "mission-1", "workcell_id": "omx_01",
        "action_id": "action-1", "attempt_id": "attempt-1",
        "dispatch_generation": 4, "based_on_event_id": 19,
        "observation_id": image.observation_id, "observed_at": image.observed_at,
        "image_sha256": image.sha256,
    }

    class ObservationSource:
        async def capture_after(self, **request):
            assert request["based_on_event_id"] == 19
            assert request["after_action_at"] == context.action_observed_at
            return {"observation": image, "scope": observation_scope}

    class CandidateAdapter:
        async def propose_pick_place(self, *, request_id, instruction, observation):
            assert observation is image
            return PickPlaceProposalCandidate.from_function_call(
                request_id=request_id, interaction_id="interaction-1",
                call_id="candidate-call-1", name="propose_pick_place",
                arguments={
                    "target": {"label": "red block", "point_yx_1000": [575, 664]},
                    "destination": {"label": "green tray", "point_yx_1000": [475, 305]},
                }, instruction=instruction, observation=observation,
                model_id="gemini-robotics-er2",
            )

    class ProposalStore:
        saved = None

        def create_feedback_candidate_fenced(self, **request):
            self.saved = request
            return {"proposal": {"proposal_id": "proposal-1"}, "created": True}

    class EgressPolicy:
        approved_data_classes = frozenset({
            "mission_progress", "mission_instruction", "camera_observation",
        })

        def validate_for(self, *, scope, task_class):
            assert scope.workcell_id == "omx_01"
            assert task_class == "PICK_PLACE"

    async def run():
        proposals = ProposalStore()
        base = {
            "mission_service": MissionService(), "progress_service": ProgressService(),
            "proposal_store": proposals,
            "authorization_check": lambda trusted: trusted.principal_id == "operator-1",
        }
        dispatcher = MissionFeedbackToolDispatcher(
            **base, post_action_observation_source=ObservationSource(),
        )
        scope = MissionFeedbackTurnScope.model_validate({
            "principal_id": "operator-1", "workcell_id": "omx_01",
            "mission_id": "mission-1", "action_id": "action-1",
            "attempt_id": "attempt-1", "dispatch_generation": 4,
            "event_watermark": 19, "model_policy_revision": "policy-v1",
            "outcome_policy": "STATUS_AND_REPLAN",
        })
        unconfigured = MissionFeedbackToolDispatcher(**base)
        unavailable = await unconfigured.dispatch_replan(
            scope=scope, turn_id="turn-1", call_id="tool-call-1",
            arguments={"based_on_event_id": 19, "rationale": "The goal remains unsatisfied."},
            candidate_adapter=CandidateAdapter(), egress_policy=EgressPolicy(),
        )
        assert unavailable.status == "unavailable"
        assert unavailable.reason_code == "REPLAN_OBSERVATION_UNAVAILABLE"
        assert proposals.saved is None
        result = await dispatcher.dispatch_replan(
            scope=scope, turn_id="turn-1", call_id="tool-call-1",
            arguments={"based_on_event_id": 19, "rationale": "The goal remains unsatisfied."},
            candidate_adapter=CandidateAdapter(), egress_policy=EgressPolicy(),
        )
        assert result.status == "accepted"
        assert result.reason_code == "CANDIDATE_RECORDED"
        assert result.proposal_id == "proposal-1"
        assert result.payload == {"successor_of_mission_id": "mission-1", "executable": False}
        assert proposals.saved["turn_id"] == "turn-1"
        assert proposals.saved["candidate"]["source_observation"]["image_sha256"] == image.sha256

    asyncio.run(run())


def test_async_replan_rechecks_scope_after_capture_before_image_egress():
    mission = {
        "principal_id": "operator-1", "workcell_id": "omx_01",
        "action_id": "action-1", "attempt_id": "attempt-1",
        "dispatch_generation": 4, "status": "HOLD",
        "reason": "GOAL_NOT_SATISFIED",
        "plan": {"instruction": "Move the red block to the green tray"},
    }
    context = MissionFeedbackContext.model_validate({
        "mission_id": "mission-1", "workcell_id": "omx_01",
        "action_id": "action-1", "attempt_id": "attempt-1",
        "dispatch_generation": 4, "stop_generation": 4, "authority_epoch": 2,
        "snapshot_event_id": 19, "snapshot_at": "2026-09-30T12:00:00Z",
        "policy_revision": "policy-v1", "outcome_policy": "STATUS_AND_REPLAN",
        "task_summary": "Move the red block to the green tray",
        "mission_source": "fleet_missions", "step_source": "fleet_missions",
        "action_source": "fleet_mission_events", "action_freshness": "FRESH",
        "action_observed_at": "2026-09-30T12:00:00Z",
        "goal_evidence_source": "trusted-test", "goal_evidence_freshness": "FRESH",
        "goal_evidence_observed_at": "2026-09-30T12:00:01Z",
        "stop_source": "fleet_dispatch_control", "stop_freshness": "CURRENT",
        "stop_observed_at": "2026-09-30T12:00:00Z",
        "mission_state": "HOLD", "step_state": "HOLD", "action_state": "SUCCEEDED",
        "action_reason": None, "goal_evidence_state": "UNSATISFIED",
        "goal_evidence_reason": "GOAL_NOT_SATISFIED",
        "stop_state": "DISPATCH_ENABLED", "stop_reason": None,
    })

    class MissionService:
        def get(self, _mission_id):
            return mission

    class ProgressService:
        def snapshot(self, _mission_id):
            return {"progress": {"snapshot_event_id": 19}}

        def model_context(self, _mission_id, **_scope):
            return context.model_dump(mode="json")

    observation = ImageObservation(
        observation_id="obs-after-stop", camera_id="camera-top", frame_id="frame-8",
        observed_at="2026-09-30T12:00:02Z", image_bytes=b"frame-bytes",
        image_transform=ImageTransform.identity(source_width=640, source_height=480),
        calibration_revision="cal-4", transform_revision="tf-9",
    )

    class ObservationSource:
        async def capture_after(self, **_request):
            mission["status"] = "RUNNING"
            mission["reason"] = "STOP_GENERATION_CHANGED"
            return {"observation": observation, "scope": {
                "mission_id": "mission-1", "workcell_id": "omx_01",
                "action_id": "action-1", "attempt_id": "attempt-1",
                "dispatch_generation": 4, "based_on_event_id": 19,
                "observation_id": observation.observation_id,
                "observed_at": observation.observed_at,
                "image_sha256": observation.sha256,
            }}

    class CandidateAdapter:
        calls = 0

        async def propose_pick_place(self, **_request):
            self.calls += 1
            raise AssertionError("stale observation must not leave Fleet")

    class ProposalStore:
        def create_feedback_candidate_fenced(self, **_request):
            raise AssertionError("stale observation must not create a candidate")

    class ApprovedEgress:
        approved_data_classes = frozenset({
            "mission_progress", "mission_instruction", "camera_observation",
        })

        def validate_for(self, *, scope, task_class):
            assert scope.workcell_id == "omx_01"
            assert task_class == "PICK_PLACE"

    async def run():
        candidate_adapter = CandidateAdapter()
        services = {
            "mission_service": MissionService(),
            "progress_service": ProgressService(),
            "proposal_store": ProposalStore(),
            "authorization_check": lambda trusted: trusted.principal_id == "operator-1",
        }
        scope = MissionFeedbackTurnScope.model_validate({
            "principal_id": "operator-1", "workcell_id": "omx_01",
            "mission_id": "mission-1", "action_id": "action-1",
            "attempt_id": "attempt-1", "dispatch_generation": 4,
            "event_watermark": 19, "model_policy_revision": "policy-v1",
            "outcome_policy": "STATUS_AND_REPLAN",
        })

        class DeniedEgress:
            approved_data_classes = frozenset({
                "mission_progress", "mission_instruction", "camera_observation",
            })

            def validate_for(self, **_scope):
                raise ValueError("workcell egress was revoked")

        class NoCaptureSource:
            async def capture_after(self, **_request):
                raise AssertionError("denied image egress must not capture or send a frame")

        denied_dispatcher = MissionFeedbackToolDispatcher(
            **services, post_action_observation_source=NoCaptureSource(),
        )
        denied = await denied_dispatcher.dispatch_replan(
            scope=scope, turn_id="turn-1", call_id="call-denied",
            arguments={"based_on_event_id": 19, "rationale": "Check placement."},
            candidate_adapter=candidate_adapter, egress_policy=DeniedEgress(),
        )
        assert denied.status == "rejected"
        assert denied.reason_code == "REPLAN_EGRESS_NOT_APPROVED"

        dispatcher = MissionFeedbackToolDispatcher(
            **services, post_action_observation_source=ObservationSource(),
        )
        result = await dispatcher.dispatch_replan(
            scope=scope, turn_id="turn-1", call_id="call-1",
            arguments={"based_on_event_id": 19, "rationale": "Check placement."},
            candidate_adapter=candidate_adapter, egress_policy=ApprovedEgress(),
        )
        return result, candidate_adapter.calls

    result, adapter_calls = asyncio.run(run())

    assert result.status == "rejected"
    assert result.reason_code == "REPLAN_NOT_ELIGIBLE"
    assert adapter_calls == 0
