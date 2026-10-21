"""Workcell observations compose into real Fleet auth and existing preview leases."""
from datetime import datetime, timezone
from hashlib import sha256

from fastapi.testclient import TestClient
import pytest

from core_common.protocol.workcell_observations import WorkcellObservationManifest
from core_common.protocol.vision_preview import VisionLeaseSigner
from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.server.workcell_observations import WorkcellObservations
from fleet.swarm.robots import RobotEndpoint


PATH = "/api/fleet/workcell-observations"
VIEWER = {"Authorization": "Bearer viewer-secret"}
SIGNING = "preview-signing-" + "x" * 32


def service(token="arm-observation-secret"):
    manifest = WorkcellObservationManifest.model_validate({"schema": "rosy.workcell-observations/1", "workcells": [{
        "workcell_id": "example", "label": "Example", "arms": [{
            "source_id": "arm_feedback", "arm_id": "arm_a", "label": "Arm A", "board_id": "EXAMPLE-BOARD",
            "joint_topic": "/omx_commissioning/arm_a/joint_states", "joint_names": ["joint1"],
            "token_env": "EXAMPLE_ARM"}], "cameras": [{
                "source_id": "workcell_top", "label": "Top", "role": "overhead", "arm_id": None,
                "image_topic": "/top/image_raw", "device_path": "/dev/v4l/by-id/example-top",
                "token_env": "EXAMPLE_TOP"}]}]})
    return WorkcellObservations(manifest, {"arm_feedback": token}, wall=lambda: 100.0, monotonic=lambda: 10.0)


@pytest.fixture
def fleet(tmp_path):
    console = FleetConsole([RobotEndpoint("rosy_01", "http://127.0.0.1:8080", "robot-secret")],
                           [FakeRobot("rosy_01")])
    kwargs = {"console_token": "console-secret", "start_task_dispatcher": False,
              "task_service": FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"), robot_ids=("rosy_01",)),
              "site_users": {sha256(b"viewer-secret").hexdigest(): {"principal_id": "reader", "role": "viewer"}}}
    return console, kwargs


@pytest.mark.parametrize("configured,expected", [(True, 200), (False, 503)])
def test_real_fleet_viewer_guard_applies_without_a_cell_compiler(fleet, configured, expected):
    console, kwargs = fleet
    client = TestClient(create_app(console, **kwargs, lan_camera_proxy=True, cell_job_compiler=None,
                                  workcell_observations=service() if configured else None))
    assert client.get(PATH).status_code == 401
    assert client.get(PATH, headers={"X-Rosy-Lan-Camera": "1"}).status_code == 401
    assert client.get(PATH, headers={"Authorization": "Bearer arm-observation-secret"}).status_code == 401
    response = client.get(PATH, headers=VIEWER)
    assert response.status_code == expected
    if configured:
        assert response.headers["Cache-Control"] == "no-store"
        assert response.json()["workcells"][0]["arms"][0]["source_id"] == "arm_feedback"


@pytest.mark.parametrize("credential", ["console", "site-user", "robot", "discovery", "vision", "pairing", "goal"])
def test_observation_producer_cannot_reuse_an_existing_product_credential(fleet, tmp_path, credential):
    console, kwargs = fleet
    shared = {"console": "console-secret", "site-user": "viewer-secret", "robot": "robot-secret",
              "discovery": "discovery-secret", "vision": SIGNING, "pairing": "pairing-sync-secret",
              "goal": "goal-producer-secret"}[credential]
    if credential == "discovery":
        from fleet.server.discovery import DiscoveryStore
        kwargs.update(discovery=DiscoveryStore(), discovery_token=shared)
    elif credential == "vision":
        kwargs.update(vision_lease_secret=shared)
    elif credential == "pairing":
        from fleet.server.pairing import PairingService
        from fleet.server.pairing_store import PairingStore
        from pairing_fixtures import LEAF_SHA256, SITE_CA_PEM, TLS_HOST
        kwargs.update(pairing=PairingService(PairingStore(tmp_path / "fleet.sqlite3"),
            leaf_cert_sha256=LEAF_SHA256, site_ca_pem=SITE_CA_PEM, tls_host=TLS_HOST,
            site_name="Example", sources={"workcell_top": "paired"}), pairing_sync_token=shared)
    elif credential == "goal":
        from fleet.server.goal_evidence_registry import GoalEvidenceProducer, GoalEvidenceRegistry
        from fleet.server.goal_evidence_service import GoalEvidenceService
        from fleet.server.goal_evidence_store import GoalEvidenceStore
        from fleet.server.mission_service import MissionService
        from fleet.server.mission_store import MissionStore
        from fleet.server.proposal_store import ProposalStore
        db = tmp_path / "fleet.sqlite3"
        missions = MissionService(MissionStore(db))
        producer = GoalEvidenceProducer(producer_id="evaluator", token=shared, workcell_id="example",
            predicate_id="placed", object_id="example-object", destination_id="example-tray",
            evidence_source="camera_observation", max_age_s=2, grace_s=5, evaluator_revisions=("example-v1",),
            valid_until=datetime(2099, 1, 1, tzinfo=timezone.utc))
        kwargs.update(mission_service=missions, proposal_store=ProposalStore(db),
            goal_evidence_service=GoalEvidenceService(missions, GoalEvidenceRegistry((producer,)), GoalEvidenceStore(db)))
    with pytest.raises(ValueError, match="credential|token"):
        create_app(console, **kwargs, workcell_observations=service(shared))


def test_preview_only_camera_joins_existing_source_list_and_lease_without_sightings(fleet):
    console, kwargs = fleet
    client = TestClient(create_app(console, **kwargs, sightings=None, vision_lease_secret=SIGNING,
                                  vision_sources=("existing_ceiling",), workcell_observations=service()))
    response = client.get("/api/fleet/vision/sources", headers=VIEWER)
    assert response.status_code == 200
    assert response.json() == {"sources": ["existing_ceiling", "workcell_top"]}
    issued = client.post("/api/fleet/vision/lease", headers=VIEWER, json={"source_id": "workcell_top"})
    assert issued.status_code == 200
    assert issued.json()["frame_path"] == "/api/vision/sources/workcell_top/frame"
    assert VisionLeaseSigner(SIGNING).verify(issued.json()["lease"], source_id="workcell_top")["scope"] == "frame:read"


def test_preview_source_collision_is_rejected_before_union(fleet):
    console, kwargs = fleet
    with pytest.raises(ValueError, match="source|collision|duplicate"):
        create_app(console, **kwargs, vision_lease_secret=SIGNING, vision_sources=("workcell_top",),
                   workcell_observations=service())
