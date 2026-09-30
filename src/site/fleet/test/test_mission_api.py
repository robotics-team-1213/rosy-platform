from hashlib import sha256
import sqlite3
from datetime import datetime, timezone
from threading import Event

import pytest
from fastapi.testclient import TestClient

from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.mission_service import MissionService
from fleet.server.mission_store import MissionStore
from fleet.server.proposal_store import ProposalStore, ProposalRejected
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.robots import RobotEndpoint


def _candidate(**updates):
    value = {
        "source": "gemini_robotics_er2",
        "model_id": "gemini-robotics-er2",
        "provider_interaction_id": "interaction-1",
        "provider_call_id": "call-1",
        "instruction": "Move the red block to the green tray",
        "source_observation": {
            "observation_id": "obs-1", "image_sha256": "a" * 64,
            "camera_id": "camera-top", "frame_id": "camera_top_optical",
            "observed_at": "2026-09-29T09:00:00+00:00",
            "calibration_revision": "cal-4", "transform_revision": "tf-9",
        },
        "target_selector": {"label": "red block", "point_yx_1000": [575, 664]},
        "destination_selector": {"label": "green tray", "point_yx_1000": [475, 305]},
    }
    value.update(updates)
    return value


def _resolution(candidate, *, workcell_id, instance_id, now):
    observation = candidate["source_observation"]
    observed = datetime.fromisoformat(observation["observed_at"]).astimezone(timezone.utc)
    elapsed = observed - datetime(1970, 1, 1, tzinfo=timezone.utc)
    capture_time_ns = ((elapsed.days * 86_400 + elapsed.seconds) * 1_000_000_000
                       + elapsed.microseconds * 1_000)

    def target(object_id):
        return {
            "object_id": object_id, "observation_id": observation["observation_id"],
            "frame_sha256": observation["image_sha256"],
            "camera_identity": observation["camera_id"],
            "optical_frame_id": observation["frame_id"],
            "calibration_revision": observation["calibration_revision"],
            "transform_revision": observation["transform_revision"],
            "capture_time_ns": capture_time_ns, "selector_kind": "point",
            "image_bbox_xyxy": [1, 1, 10, 10],
        }
    return {
        "plan": {
            "source_object_id": "block-1", "destination_object_id": "tray-1",
            "source_evidence": target("block-1"),
            "destination_evidence": target("tray-1"),
            "observation_id": observation["observation_id"],
            "image_sha256": observation["image_sha256"],
            "calibration_revision": observation["calibration_revision"],
            "transform_revision": observation["transform_revision"],
            "capability_revision": "pick-place-v1", "config_revision": "omx-config-r4",
            "observation_revision": observation["observation_id"],
            "resolved_at": now, "workcell_id": workcell_id,
            "instance_id": instance_id,
        },
        "goal_predicate": {
            "predicate_id": "block-in-tray", "condition": "object_in_destination",
            "object_id": "block-1", "destination_id": "tray-1",
            "evidence_source": "camera_observation",
        },
        "resources": [["workcell", "omx_01"], ["object", "block-1"],
                      ["object", "tray-1"]],
    }


def _client(tmp_path, *, resolver=_resolution, named_users=True,
            enable_mission_dispatcher=False, action_transport=None,
            goal_evidence_enabled=False, mission_model_turn_worker_factory=None,
            post_action_observation_source=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    db = tmp_path / "fleet.sqlite3"
    robot = FakeRobot("rosy_01")
    console = FleetConsole([RobotEndpoint("rosy_01", "http://127.0.0.1:8080", "robot-token")],
                           [robot])
    tasks = FleetTaskService(FleetTaskStore(db), robot_ids=("rosy_01",))
    credentials = {"operator-secret": {"principal_id": "operator-1", "role": "operator"},
                   "viewer-secret": {"principal_id": "viewer-1", "role": "viewer"}}
    site_users = ({sha256(token.encode()).hexdigest(): value
                   for token, value in credentials.items()} if named_users else None)
    mission_service = MissionService(MissionStore(db))
    mission_model_turn_worker = None
    if mission_model_turn_worker_factory is not None:
        from fleet.server.mission_model_turn_store import MissionModelTurnStore

        mission_model_turn_worker = mission_model_turn_worker_factory(
            MissionModelTurnStore(db),
        )
    goal_evidence_service = None
    if goal_evidence_enabled:
        import yaml
        from fleet.server.goal_evidence_registry import load_goal_evidence_registry
        from fleet.server.goal_evidence_service import GoalEvidenceService
        from fleet.server.goal_evidence_store import GoalEvidenceStore

        config = tmp_path / "goal-evidence.yaml"
        config.write_text(yaml.safe_dump({"producers": [{
            "producer_id": "top-camera-evaluator", "token_env": "GOAL_TOKEN",
            "workcell_id": "omx_01", "predicate_id": "block-in-tray",
            "object_id": "block-1", "destination_id": "tray-1",
            "evidence_source": "camera_observation", "max_age_s": 5,
            "grace_s": 10, "evaluator_revisions": ["placement-v1"],
            "valid_until": "2026-10-01T00:00:00+00:00",
        }]}), encoding="utf-8")
        registry = load_goal_evidence_registry(config, environ={"GOAL_TOKEN": "source-secret"})
        goal_evidence_service = GoalEvidenceService(
            mission_service, registry, GoalEvidenceStore(db),
        )
    app = create_app(
        console, task_service=tasks, site_users=site_users,
        mission_service=mission_service,
        proposal_store=ProposalStore(db), candidate_resolver=resolver,
        goal_evidence_service=goal_evidence_service,
        mission_model_turn_worker=mission_model_turn_worker,
        post_action_observation_source=post_action_observation_source,
        enable_mission_dispatcher=enable_mission_dispatcher,
        omx_instances=({"omx_01": "omx_01_control"}
                       if enable_mission_dispatcher else None),
        omx_action_transport=action_transport,
    )
    return TestClient(app), tasks, credentials


def test_goal_evidence_endpoint_uses_separate_producer_token(tmp_path):
    client, _, _ = _client(tmp_path, goal_evidence_enabled=True)
    path = "/api/fleet/goal-evidence"

    missing = client.post(path, json={"mission_id": "mission-1", "evidence": {}})
    rejected = client.post(path, headers={"X-Goal-Evidence-Token": "wrong"},
                           json={"mission_id": "mission-1", "evidence": {}})
    disabled = _client(tmp_path / "without-registry")[0].post(
        path, headers={"X-Goal-Evidence-Token": "source-secret"},
        json={"mission_id": "mission-1", "evidence": {}},
    )

    assert missing.status_code == 401
    assert rejected.status_code == 401
    assert disabled.status_code == 404


def _create(client, token="operator-secret", candidate=None, request_key="req-1"):
    return client.post("/api/fleet/proposals", headers={"Authorization": f"Bearer {token}"},
                       json={"request_key": request_key, "workcell_id": "omx_01",
                             "instance_id": "omx_01_control",
                             "candidate": candidate or _candidate()})


def _resolve(client, proposal_id, token="operator-secret"):
    return client.post(f"/api/fleet/proposals/{proposal_id}/resolve",
                       headers={"Authorization": f"Bearer {token}"})


def test_operator_mission_api_persists_candidate_and_get_does_not_call_provider(tmp_path):
    calls = []

    def resolver(candidate, *, workcell_id, instance_id, now):
        calls.append(candidate["provider_call_id"])
        return _resolution(candidate, workcell_id=workcell_id, instance_id=instance_id, now=now)

    client, _, _ = _client(tmp_path, resolver=resolver)
    assert client.app.state.mission_dispatcher is None
    assert client.app.state.mission_model_turn_store.path == client.app.state.mission_service.store.path
    assert client.app.state.mission_model_turn_scheduler is not None
    assert client.app.state.mission_model_turn_worker is None
    created = _create(client)
    duplicate = _create(client)
    proposal_id = created.json()["proposal"]["proposal_id"]
    readback = client.get(f"/api/fleet/proposals/{proposal_id}",
                          headers={"Authorization": "Bearer operator-secret"})

    assert created.status_code == duplicate.status_code == readback.status_code == 200
    assert duplicate.json()["created"] is False
    assert calls == []
    assert readback.json()["proposal"]["candidate"]["provider_call_id"] == "call-1"
    assert readback.json()["proposal"]["source_mission_id"] is None
    assert readback.json()["proposal"]["supersedes_mission_id"] is None
    assert "image_bytes" not in readback.text and "api_key" not in readback.text
    resolved = _resolve(client, proposal_id)
    resolved_duplicate = _resolve(client, proposal_id)
    assert resolved.status_code == resolved_duplicate.status_code == 200, resolved.text
    assert resolved_duplicate.json()["created"] is False
    assert calls == ["call-1"]
    mission_id = resolved.json()["mission"]["mission_id"]
    mission_readback = client.get(f"/api/fleet/missions/{mission_id}",
                                  headers={"Authorization": "Bearer operator-secret"})
    assert mission_readback.status_code == 200
    assert mission_readback.json()["mission"]["supersedes_mission_id"] is None


def test_app_consumes_feedback_outbox_only_when_worker_is_injected(tmp_path):
    ready = Event()

    class Worker:
        def __init__(self, store):
            self.store = store

        async def consume_next(self, *, worker_id):
            assert worker_id == "fleet-feedback"
            ready.set()
            return None

    client, _, _ = _client(
        tmp_path, mission_model_turn_worker_factory=Worker,
    )

    with client:
        assert client.app.state.mission_model_turn_worker is not None
        assert ready.wait(timeout=2)


def test_app_rejects_feedback_worker_on_a_different_database(tmp_path):
    from fleet.server.mission_model_turn_store import MissionModelTurnStore

    class Worker:
        def __init__(self, store):
            self.store = store

        async def consume_next(self, *, worker_id):
            return None

    def wrong_database(_store):
        return Worker(MissionModelTurnStore(tmp_path / "other.sqlite3"))

    with pytest.raises(ValueError, match="shared SQLite outbox"):
        _client(tmp_path, mission_model_turn_worker_factory=wrong_database)


def test_app_wires_configured_vision_reader_into_injected_worker(tmp_path):
    closed = Event()

    class Dispatcher:
        post_action_observation_source = None

    class Source:
        async def aclose(self):
            closed.set()

    class Worker:
        def __init__(self, store):
            self.store = store
            self.dispatcher = Dispatcher()

        async def consume_next(self, *, worker_id):
            return None

    source = Source()
    client, _, _ = _client(
        tmp_path, mission_model_turn_worker_factory=Worker,
        post_action_observation_source=source,
    )

    with client:
        assert client.app.state.post_action_observation_source is source
        assert client.app.state.mission_model_turn_worker.dispatcher.post_action_observation_source is source
    assert closed.is_set()


def test_app_rejects_vision_reader_without_feedback_worker(tmp_path):
    with pytest.raises(ValueError, match="requires an injected Mission model-turn worker"):
        _client(tmp_path, post_action_observation_source=object())


def test_resolution_storage_failure_rolls_back_mission_and_remains_retryable(tmp_path, monkeypatch):
    client, _, _ = _client(tmp_path)
    proposal_id = _create(client).json()["proposal"]["proposal_id"]
    original = MissionStore.create_proposal

    def fail_after_mission_insert(self, **kwargs):
        original(self, **kwargs)
        raise sqlite3.OperationalError("injected failure before proposal finalize")

    monkeypatch.setattr(MissionStore, "create_proposal", fail_after_mission_insert)
    failing_client = TestClient(client.app, raise_server_exceptions=False)
    failed = _resolve(failing_client, proposal_id)
    assert failed.status_code == 500
    proposal = client.app.state.proposal_store.get(proposal_id, principal_id="operator-1")
    assert proposal["state"] == "PROPOSED"
    assert client.app.state.mission_service.get(proposal_id) is None

    monkeypatch.setattr(MissionStore, "create_proposal", original)
    retried = _resolve(client, proposal_id)
    assert retried.status_code == 200, retried.text
    assert retried.json()["mission"]["mission_id"] == proposal_id


def test_mission_admission_rechecks_evidence_then_claims_resources_without_dispatch(tmp_path):
    calls = []

    def resolver(candidate, *, workcell_id, instance_id, now):
        calls.append(now)
        return _resolution(candidate, workcell_id=workcell_id, instance_id=instance_id, now=now)

    client, tasks, _ = _client(tmp_path, resolver=resolver)
    proposal_id = _create(client).json()["proposal"]["proposal_id"]
    mission = _resolve(client, proposal_id).json()["mission"]
    control = tasks.store.dispatch_control()
    generation = tasks.store.rearm_dispatch(
        expected_generation=control["generation"], actor_id="operator-1")["generation"]
    response = client.post(
        f"/api/fleet/missions/{mission['mission_id']}/admit",
        headers={"Authorization": "Bearer operator-secret"},
        json={"expected_generation": generation},
    )

    assert response.status_code == 200
    assert response.json()["mission"]["status"] == "READY"
    assert len(calls) == 2
    assert tasks.store.resource_claims(resource_kind="object", resource_id="block-1")
    assert client.app.state.mission_dispatcher is None


def test_dispatcher_requires_explicit_enablement_and_action_transport_is_injected(tmp_path):
    class Transport:
        pass

    client, _, _ = _client(
        tmp_path, enable_mission_dispatcher=True, action_transport=Transport(),
    )

    assert client.app.state.mission_dispatcher is not None


def test_viewer_and_unnamed_development_principal_cannot_admit_mission(tmp_path):
    client, tasks, _ = _client(tmp_path)
    proposal_id = _create(client).json()["proposal"]["proposal_id"]
    mission = _resolve(client, proposal_id).json()["mission"]
    hidden = client.get(f"/api/fleet/missions/{mission['mission_id']}",
                        headers={"Authorization": "Bearer viewer-secret"})
    assert hidden.status_code == 404
    control = tasks.store.dispatch_control()
    generation = tasks.store.rearm_dispatch(
        expected_generation=control["generation"], actor_id="operator-1")["generation"]
    payload = {"expected_generation": generation}

    viewer = client.post(f"/api/fleet/missions/{mission['mission_id']}/admit",
                         headers={"Authorization": "Bearer viewer-secret"}, json=payload)
    assert viewer.status_code == 403

    unconfigured, _, _ = _client(tmp_path / "development", named_users=False)
    proposal_id = _create(unconfigured).json()["proposal"]["proposal_id"]
    mission = _resolve(unconfigured, proposal_id).json()["mission"]
    response = unconfigured.post(f"/api/fleet/missions/{mission['mission_id']}/admit",
                                 json=payload)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "OPERATOR_IDENTITY_REQUIRED"


def test_stale_or_changed_candidate_and_conflicting_shared_claim_fail_closed(tmp_path):
    client, tasks, _ = _client(tmp_path)
    proposal_id = _create(client).json()["proposal"]["proposal_id"]
    mission = _resolve(client, proposal_id).json()["mission"]
    control = tasks.store.dispatch_control()
    generation = tasks.store.rearm_dispatch(
        expected_generation=control["generation"], actor_id="operator-1")["generation"]
    assert tasks.store.reserve_resources(
        owner_kind="direct_action", owner_id="nav-1", generation=generation,
        resources=[("object", "block-1")],
    )
    conflict = client.post(
        f"/api/fleet/missions/{mission['mission_id']}/admit",
        headers={"Authorization": "Bearer operator-secret"},
        json={"expected_generation": generation},
    )
    assert conflict.status_code == 409

    def stale_resolver(candidate, *, workcell_id, instance_id, now):
        raise ProposalRejected("OBSERVATION_STALE")

    stale, _, _ = _client(tmp_path / "stale", resolver=stale_resolver)
    proposal_id = _create(stale).json()["proposal"]["proposal_id"]
    response = _resolve(stale, proposal_id)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "OBSERVATION_STALE"


def test_changed_calibration_or_capability_revision_blocks_admission(tmp_path):
    calls = 0

    def resolver(candidate, *, workcell_id, instance_id, now):
        nonlocal calls
        calls += 1
        resolved = _resolution(candidate, workcell_id=workcell_id,
                               instance_id=instance_id, now=now)
        if calls > 1:
            resolved["plan"]["transform_revision"] = "tf-revised"
        return resolved

    client, tasks, _ = _client(tmp_path, resolver=resolver)
    proposal_id = _create(client).json()["proposal"]["proposal_id"]
    mission = _resolve(client, proposal_id).json()["mission"]
    control = tasks.store.dispatch_control()
    generation = tasks.store.rearm_dispatch(
        expected_generation=control["generation"], actor_id="operator-1")["generation"]
    response = client.post(
        f"/api/fleet/missions/{mission['mission_id']}/admit",
        headers={"Authorization": "Bearer operator-secret"},
        json={"expected_generation": generation},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "EVIDENCE_OR_CAPABILITY_CHANGED"
    assert tasks.store.resource_claims(resource_kind="object", resource_id="block-1") == []


def test_resolver_output_cannot_persist_raw_images_or_miss_shared_workcell_claim(tmp_path):
    def resolver(candidate, *, workcell_id, instance_id, now):
        result = _resolution(candidate, workcell_id=workcell_id,
                             instance_id=instance_id, now=now)
        result["plan"]["image_bytes"] = "frame"
        return result

    client, _, _ = _client(tmp_path, resolver=resolver)
    proposal_id = _create(client).json()["proposal"]["proposal_id"]
    response = _resolve(client, proposal_id)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "RESOLUTION_CONTAINS_FORBIDDEN_DATA"
    assert client.app.state.mission_service.get(proposal_id) is None


def test_resolved_targets_must_match_the_model_source_frame_and_fleet_generation(tmp_path):
    def mismatched_resolver(candidate, *, workcell_id, instance_id, now):
        result = _resolution(candidate, workcell_id=workcell_id,
                             instance_id=instance_id, now=now)
        result["plan"]["source_evidence"]["observation_id"] = "other-frame"
        return result

    client, _, _ = _client(tmp_path, resolver=mismatched_resolver)
    proposal_id = _create(client).json()["proposal"]["proposal_id"]
    response = _resolve(client, proposal_id)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "OBSERVATION_PROVENANCE_MISMATCH"
    assert client.app.state.mission_service.get(proposal_id) is None

    client, tasks, _ = _client(tmp_path / "generation")
    proposal_id = _create(client).json()["proposal"]["proposal_id"]
    mission = _resolve(client, proposal_id).json()["mission"]
    control = tasks.store.dispatch_control()
    generation = tasks.store.rearm_dispatch(
        expected_generation=control["generation"], actor_id="operator-1")["generation"]
    tasks.store.trip_stop_latch(actor_id="operator-1")
    refused = client.post(
        f"/api/fleet/missions/{mission['mission_id']}/admit",
        headers={"Authorization": "Bearer operator-secret"},
        json={"expected_generation": generation},
    )

    assert refused.status_code == 409
    assert tasks.store.resource_claims(resource_kind="object", resource_id="block-1") == []


def test_model_cannot_supply_authenticated_principal_or_observation_image_bytes(tmp_path):
    client, _, _ = _client(tmp_path)
    forged = _create(client, candidate={**_candidate(), "principal_id": "admin"})
    image = _create(client, candidate={**_candidate(), "image_bytes": "base64-frame"},
                    request_key="req-2")

    assert forged.status_code == 422
    assert image.status_code == 422


def test_mission_api_openapi_exposes_separate_proposal_resolve_and_admit_operations(tmp_path):
    client, _, _ = _client(tmp_path)
    spec = client.app.openapi()

    assert set(spec["paths"]["/api/fleet/proposals"]) == {"post"}
    assert set(spec["paths"]["/api/fleet/proposals/{proposal_id}"]) == {"get"}
    assert set(spec["paths"]["/api/fleet/proposals/{proposal_id}/resolve"]) == {"post"}
    assert set(spec["paths"]["/api/fleet/missions/{mission_id}"]) == {"get"}
    assert set(spec["paths"]["/api/fleet/missions/{mission_id}/admit"]) == {"post"}
    candidate_schema = spec["components"]["schemas"]["MissionCandidateRequest"]
    assert candidate_schema["additionalProperties"] is False
    assert set(candidate_schema["properties"]) == {
        "request_key", "workcell_id", "instance_id", "candidate",
    }


def test_mutation_audit_failure_blocks_candidate_storage(tmp_path, monkeypatch):
    client, tasks, _ = _client(tmp_path)

    def fail_audit(**_kwargs):
        raise sqlite3.OperationalError("audit unavailable")

    monkeypatch.setattr(tasks.store, "begin_api_audit", fail_audit)
    response = _create(client)

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "AUDIT_STORAGE_UNAVAILABLE"
    assert client.app.state.proposal_store.by_request(
        principal_id="operator-1", request_key="req-1") is None
