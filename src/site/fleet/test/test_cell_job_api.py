from hashlib import sha256
from pathlib import Path
import sys

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[4]
for relative in ("modules/execution/src", "modules/skills/api/src"):
    path = str(ROOT / relative)
    if path not in sys.path:
        sys.path.insert(0, path)

from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.mission_service import MissionService
from fleet.server.mission_store import MissionStore
from fleet.server.proposal_store import ProposalStore
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.robots import RobotEndpoint
from rosy.execution.api import PlanBundle, PlanStep
from rosy.execution.site.cell_submission import CellJobCompilation
from rosy.skills.api import SkillInvocation


RECIPE_SHA = "b" * 64
CELL_SHA = "c" * 64


class FixedCellCompiler:
    def __init__(self):
        self.calls = 0
        self.destination_x = 0.4

    def item_geometry(self, recipe):
        box = recipe["box"]
        return {"box": {"grasp_depth_m": box["grasp_depth"], "height_m": box["height"]}}

    def compile(self, recipe, cell):
        self.calls += 1
        job = {"recipe": "compiled", "steps": ["transfer-0", "transfer-1"]}
        steps = []
        for ordinal in range(2):
            inputs = {
                "item": "box", "pallet_id": "pallet-1", "layer_index": ordinal,
                "home_pose_base": {"x_m": 0.0, "y_m": 0.0, "z_m": 0.4, "yaw_rad": 0.0},
                "source_pose_base": {"x_m": 0.1, "y_m": 0.2, "z_m": 0.3, "yaw_rad": 0.0},
                "destination_pose_base": {"x_m": self.destination_x, "y_m": 0.5, "z_m": 0.3, "yaw_rad": 1.57},
                "source_approach_z_base_m": 0.5,
                "destination_approach_z_base_m": 0.5,
                "carry_z_base_m": 0.6,
            }
            steps.append(PlanStep(
                ordinal, SkillInvocation("pallet.transfer", "1.0.0", inputs),
            ))
        bundle = PlanBundle(
            process_artifact_digest="a" * 64, recipe_digest=RECIPE_SHA,
            cell_digest=CELL_SHA, steps=tuple(steps),
        )
        return CellJobCompilation(
            job=job, plan_bundle=bundle,
            ledger_markers=({"after_step_ordinal": 2, "pallet_id": "pallet-1"},),
        )


def _setup(tmp_path, **app_options):
    db = tmp_path / "fleet.sqlite3"
    task_service = FleetTaskService(FleetTaskStore(db), robot_ids=("rosy_01",))
    users = {
        sha256(token.encode()).hexdigest(): {"principal_id": principal, "role": role}
        for token, principal, role in (
            ("cell-secret", "cell-service", "service"),
            ("operator-secret", "operator-1", "operator"),
            ("viewer-secret", "viewer-1", "viewer"),
        )
    }
    compiler = FixedCellCompiler()
    app = create_app(
        FleetConsole(
            [RobotEndpoint("rosy_01", "http://127.0.0.1:8080", "robot-token")],
            [FakeRobot("rosy_01")],
        ),
        task_service=task_service, site_users=users,
        mission_service=MissionService(MissionStore(db)),
        proposal_store=ProposalStore(db), cell_job_compiler=compiler, **app_options,
    )
    return TestClient(app), task_service, compiler


def _candidate():
    return {
        "kind": "cell_job", "recipe": {"schema": "rosy_cell.recipe/1"},
        "cell": {"schema": "rosy_cell.cell/2"},
        "recipe_sha256": RECIPE_SHA, "cell_sha256": CELL_SHA,
        "job": {"recipe": "compiled", "steps": ["transfer-0", "transfer-1"]},
    }


def _post(client, path, token, body=None):
    return client.post(path, headers={"Authorization": f"Bearer {token}"}, json=body or {})


def test_cell_service_proposes_and_resolves_but_named_operator_alone_admits(tmp_path):
    client, tasks, compiler = _setup(tmp_path)
    request = {"request_key": "cell-job-1", "workcell_id": "omx_01",
               "instance_id": "omx_01_control", "candidate": _candidate()}

    refused_creator = _post(client, "/api/fleet/proposals", "operator-secret", request)
    created = _post(client, "/api/fleet/proposals", "cell-secret", request)
    proposal_id = created.json()["proposal"]["proposal_id"]
    resolved = _post(client, f"/api/fleet/proposals/{proposal_id}/resolve", "cell-secret")
    repeated = _post(client, f"/api/fleet/proposals/{proposal_id}/resolve", "cell-secret")
    viewer_admit = _post(
        client, f"/api/fleet/missions/{proposal_id}/admit", "viewer-secret",
        {"expected_generation": 0},
    )
    service_admit = _post(
        client, f"/api/fleet/missions/{proposal_id}/admit", "cell-secret",
        {"expected_generation": 0},
    )

    assert refused_creator.status_code == 403
    assert created.status_code == 200
    assert resolved.status_code == 200
    assert resolved.json()["mission"]["status"] == "PROPOSED"
    assert [step["action_kind"] for step in resolved.json()["mission"]["steps"]] == [
        "CELL_TRANSFER", "CELL_TRANSFER",
    ]
    assert repeated.status_code == 200 and repeated.json()["created"] is False
    assert viewer_admit.status_code == 403
    assert service_admit.status_code == 403
    assert compiler.calls == 1

    control = tasks.store.dispatch_control()
    generation = tasks.store.rearm_dispatch(
        expected_generation=control["generation"], actor_id="operator-1",
    )["generation"]
    compiler.destination_x = 0.45
    stale = _post(
        client, f"/api/fleet/missions/{proposal_id}/admit", "operator-secret",
        {"expected_generation": generation},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "CELL_JOB_CHANGED_SINCE_RESOLUTION"
    assert tasks.store.resource_claims(resource_kind="workcell", resource_id="omx_01") == []

    compiler.destination_x = 0.4
    admitted = _post(
        client, f"/api/fleet/missions/{proposal_id}/admit", "operator-secret",
        {"expected_generation": generation},
    )
    read = client.get(
        f"/api/fleet/cell-jobs/{proposal_id}",
        headers={"Authorization": "Bearer operator-secret"},
    )

    assert admitted.status_code == 200
    assert admitted.json()["mission"]["status"] == "READY"
    assert [step["status"] for step in admitted.json()["mission"]["steps"]] == [
        "READY", "WAITING",
    ]
    assert read.status_code == 200
    assert read.json()["job"]["events"]
    assert client.app.state.mission_service.get(proposal_id) is None

    restarted, _, restarted_compiler = _setup(tmp_path)
    restarted_read = restarted.get(
        f"/api/fleet/cell-jobs/{proposal_id}",
        headers={"Authorization": "Bearer operator-secret"},
    )
    assert restarted_read.status_code == 200
    held = restarted_read.json()["job"]
    assert held["status"] == held["steps"][0]["status"] == "HOLD"
    assert held["steps"][1]["status"] == "WAITING"
    assert held["events"][-1]["event_type"] == "CELL_JOB_STARTUP_HOLD"
    assert restarted_compiler.calls == 0


def test_cell_proposal_does_not_admit_when_service_and_operator_identity_match(tmp_path):
    client, _, _ = _setup(tmp_path)
    request = {"request_key": "cell-job-2", "workcell_id": "omx_01",
               "instance_id": "omx_01_control", "candidate": _candidate()}
    created = _post(client, "/api/fleet/proposals", "cell-secret", request).json()
    proposal_id = created["proposal"]["proposal_id"]
    _post(client, f"/api/fleet/proposals/{proposal_id}/resolve", "cell-secret")

    # Simulate a credential reconfiguration that aliases the stored proposal owner.
    with client.app.state.proposal_store._connect() as connection:
        connection.execute(
            "UPDATE fleet_proposals SET principal_id='operator-1' WHERE proposal_id=?",
            (proposal_id,),
        )
        connection.commit()
    response = _post(
        client, f"/api/fleet/missions/{proposal_id}/admit", "operator-secret",
        {"expected_generation": 0},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "CELL_JOB_APPROVER_MUST_DIFFER_FROM_PROPOSER"


def test_resolution_fixes_each_step_goal_predicate_from_the_recipe(tmp_path):
    """C4b 1b C1: the item_at_pose predicate is stored per step at resolution."""
    import yaml
    from rosy.execution.site.item_pose import ItemPoseTolerance
    document = yaml.safe_load((ROOT / "deploy/robot/omx/sim/item_pose_goal.yaml").read_text(encoding="utf-8"))
    client, _, _ = _setup(tmp_path, cell_item_pose_tolerance=ItemPoseTolerance.from_mapping(document))
    candidate = _candidate()
    candidate["recipe"] = {"schema": "rosy_cell.recipe/1", "box": {"height": 0.03, "grasp_depth": 0.025}}
    request = {"request_key": "cell-job-1", "workcell_id": "omx_01",
               "instance_id": "omx_01_control", "candidate": candidate}
    proposal_id = _post(client, "/api/fleet/proposals", "cell-secret", request).json()["proposal"]["proposal_id"]
    steps = _post(client, f"/api/fleet/proposals/{proposal_id}/resolve", "cell-secret").json()["mission"]["steps"]
    predicate = steps[0]["step"]["goal_predicate"]
    assert predicate["frame"] == "robot_base" and predicate["tolerance"]["xy_m"] == 0.005
    assert abs(predicate["target"]["z"] - (0.3 + 0.025 - 0.015)) < 1e-12
