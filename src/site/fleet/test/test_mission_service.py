from fleet.server.goal_evidence import GoalEvidenceError
from fleet.server.mission_store import MissionStore
from fleet.server.mission_service import MissionService
from fleet.server.task_store import FleetTaskStore


def test_duplicate_and_late_action_events_are_idempotent_and_preserve_one_attempt(tmp_path):
    path = tmp_path / "fleet.sqlite3"
    tasks = FleetTaskStore(path)
    generation = tasks.rearm_dispatch(expected_generation=0, actor_id="operator-1")["generation"]
    service = MissionService(MissionStore(path))
    mission = service.propose(
        mission_id="mission-1", principal_id="operator-1", request_key="request-1",
        workcell_id="omx_01", instance_id="omx_01_control", action_kind="PICK_PLACE",
        plan={"source": "block-1", "destination": "tray-1", "observation_id": "obs-44"},
        goal_predicate={"predicate_id": "block-in-tray", "condition": "object_in_destination",
                        "object_id": "block-1", "destination_id": "tray-1",
                        "evidence_source": "camera_observation"},
    )
    mission_id = mission["mission"]["mission_id"]
    admitted = service.admit(
        mission_id, actor_id="operator-1", expected_generation=generation,
        resources=[("workcell", "omx_01"), ("object", "block-1")],
    )
    service.start_step(mission_id, action_id="action-1", attempt_id="attempt-1",
                       expected_authority_epoch=admitted["authority_epoch"],
                       expected_generation=generation)
    first = service.record_action_result(
        mission_id, event_id="device-event-1", action_id="action-1",
        attempt_id="attempt-1", outcome="SUCCEEDED", result={"status": 4},
    )
    duplicate = service.record_action_result(
        mission_id, event_id="device-event-1", action_id="action-1",
        attempt_id="attempt-1", outcome="SUCCEEDED", result={"status": 4},
    )
    assert first["status"] == duplicate["status"] == "ACTION_SUCCEEDED"
    assert len(service.store.history(mission_id)) == 4

    try:
        service.record_action_result(
            mission_id, event_id="late-event", action_id="action-1",
            attempt_id="old-attempt", outcome="FAILED", result={"status": 6},
        )
    except ValueError as exc:
        assert "attempt" in str(exc)
    else:
        raise AssertionError("late event from another attempt was accepted")


def test_model_completion_text_cannot_confirm_a_mission_goal(tmp_path):
    path = tmp_path / "fleet.sqlite3"
    tasks = FleetTaskStore(path)
    generation = tasks.rearm_dispatch(expected_generation=0, actor_id="operator-1")["generation"]
    service = MissionService(MissionStore(path))
    mission = service.propose(
        mission_id="mission-1", principal_id="operator-1", request_key="request-1",
        workcell_id="omx_01", instance_id="omx_01_control", action_kind="PICK_PLACE",
        plan={"source": "block-1", "destination": "tray-1", "observation_id": "obs-44"},
        goal_predicate={"predicate_id": "block-in-tray", "condition": "object_in_destination",
                        "object_id": "block-1", "destination_id": "tray-1",
                        "evidence_source": "camera_observation"},
    )
    mission_id = mission["mission"]["mission_id"]
    admitted = service.admit(
        mission_id, actor_id="operator-1", expected_generation=generation,
        resources=[("workcell", "omx_01"), ("object", "block-1")],
    )
    service.start_step(mission_id, action_id="action-1", attempt_id="attempt-1",
                       expected_authority_epoch=admitted["authority_epoch"],
                       expected_generation=generation)
    service.record_action_result(
        mission_id, event_id="device-event-1", action_id="action-1",
        attempt_id="attempt-1", outcome="SUCCEEDED", result={"status": 4},
    )

    try:
        service.confirm_goal(
            mission_id, event_id="model-says-done", evidence={
                "predicate_id": "block-in-tray", "object_id": "block-1",
                "destination_id": "tray-1", "evidence_source": "model_summary",
                "evidence_id": "model-turn-88", "evidence_revision": "gemini-er2",
                "observed_at": 10.0, "satisfied": True,
            }, now=10.1, max_age_s=0.5,
        )
    except GoalEvidenceError as exc:
        assert "source" in str(exc)
    else:
        raise AssertionError("model summary was accepted as goal evidence")
