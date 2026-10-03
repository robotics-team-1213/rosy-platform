"""App composition binds the real palletizing compiler to Fleet's narrow port."""
from copy import deepcopy
from pathlib import Path
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
for relative in ("contracts/skill/src", "apps/gateway/src", "operations/processes/palletizing/src", "operations/execution/src", "modules/skills/api/src"):
    sys.path.insert(0, str(ROOT / relative))

from rosy_gateway.cell_compiler import PalletizingCellCompiler
from rosy.execution.site.cell_submission import compile_cell_submission


def documents():
    root = ROOT / "src/site/cell/examples/omx_sim"
    return tuple(yaml.safe_load((root / name).read_text(encoding="utf-8")) for name in ("recipe.yaml", "cell.yaml"))


def test_real_demo_compiler_preserves_two_layers_sheet_and_both_pallet_markers():
    recipe, cell = documents()
    before = deepcopy((recipe, cell))
    compiler = PalletizingCellCompiler(process_artifact_digest="a" * 64, tol_m=1e-6)
    compiled = compiler.compile(recipe, cell)
    bundle = compiled.plan_bundle
    candidate = dict(kind="cell_job", recipe=recipe, cell=cell, recipe_sha256=bundle.recipe_digest,
                     cell_sha256=bundle.cell_digest, job=compiled.job)
    accepted = compile_cell_submission(candidate, compiler=compiler, workcell_id="omx_01", instance_id="omx_01_control")
    assert (recipe, cell) == before
    assert len(bundle.steps) == 18
    assert sum(step.invocation.inputs["item"] == "slip_sheet" for step in bundle.steps) == 2
    assert {step.invocation.inputs["layer_index"] for step in bundle.steps} == {0, 1}
    assert accepted.ledger_markers == ((9, "A"), (18, "B"))
    assert accepted.resources == (("workcell", "omx_01"), ("pallet", "A"), ("pallet", "B"))
    assert accepted.as_store_document()["job"] == compiled.job
    candidate["job"] = deepcopy(compiled.job)
    candidate["job"]["carry_z"] += .01
    with pytest.raises(ValueError, match="recompiled Job"):
        compile_cell_submission(candidate, compiler=compiler, workcell_id="omx_01", instance_id="omx_01_control")


@pytest.mark.parametrize("digest,tolerance", [("invalid", 1e-6), ("a" * 64, 0), ("a" * 64, True), ("a" * 64, float("nan"))])
def test_compiler_rejects_unpinned_artifact_or_invalid_tolerance(digest, tolerance):
    with pytest.raises(ValueError):
        PalletizingCellCompiler(process_artifact_digest=digest, tol_m=tolerance)


def test_actual_demo_compilation_stops_at_unsupported_thin_sheet_without_motion(tmp_path):
    from test_platform_cell_runtime_replay import (LocalTransport, CellJobStore, FleetTaskStore,
        MissionStore, CellJobDispatcher, CellGoalProducer, CellGoalRegistry,
        CellGoalEvidenceService, GoalEvidenceStore, _evidence)
    from datetime import datetime, timezone

    recipe, cell = documents()
    compiler = PalletizingCellCompiler(process_artifact_digest="a" * 64, tol_m=1e-6)
    compiled = compiler.compile(recipe, cell)
    bundle = compiled.plan_bundle
    candidate = dict(kind="cell_job", recipe=recipe, cell=cell, recipe_sha256=bundle.recipe_digest,
                     cell_sha256=bundle.cell_digest, job=compiled.job)
    accepted = compile_cell_submission(candidate, compiler=compiler, workcell_id="omx_01", instance_id="omx_01_control")
    path = tmp_path / "fleet.sqlite3"
    tasks, jobs = FleetTaskStore(path), CellJobStore(path)
    MissionStore(path)
    from test_platform_cell_runtime_replay import _goal_tolerance
    from hashlib import sha256
    from fastapi.testclient import TestClient
    from fleet.server.app import create_app
    from fleet.server.console import FleetConsole
    from fleet.server.mission_service import MissionService
    from fleet.server.proposal_store import ProposalStore
    from fleet.server.task_service import FleetTaskService
    users = {sha256(token.encode()).hexdigest(): {"principal_id": principal, "role": role}
             for token, principal, role in (("cell-secret", "cell-service", "service"),
                                            ("operator-secret", "operator-1", "operator"))}
    app = create_app(FleetConsole([], []), task_service=FleetTaskService(tasks, robot_ids=()),
        mission_service=MissionService(MissionStore(path)), proposal_store=ProposalStore(path),
        cell_job_compiler=compiler, site_users=users, start_task_dispatcher=False,
        deployment_profile="simulation", cell_item_pose_tolerance=_goal_tolerance())
    client = TestClient(app)
    control = tasks.rearm_dispatch(expected_generation=tasks.dispatch_control()["generation"], actor_id="operator-1")
    def post(route, token, body=None):
        return client.post(route, headers={"Authorization": "Bearer " + token}, json=body or {})
    proposed = post("/api/fleet/proposals", "cell-secret", dict(request_key="compiled-1",
        workcell_id="omx_01", instance_id="omx_01_control", candidate=candidate))
    assert proposed.status_code == 200, proposed.text
    mission_id = proposed.json()["proposal"]["proposal_id"]
    resolved = post(f"/api/fleet/proposals/{mission_id}/resolve", "cell-secret")
    assert resolved.status_code == 200, resolved.text
    assert len(resolved.json()["mission"]["steps"]) == 18
    assert post(f"/api/fleet/missions/{mission_id}/admit", "cell-secret",
                {"expected_generation": control["generation"]}).status_code == 403
    admitted = post(f"/api/fleet/missions/{mission_id}/admit", "operator-secret",
                    {"expected_generation": control["generation"]})
    assert admitted.status_code == 200, admitted.text
    counters = {"submits": [], "gets": [], "commands": []}
    items = {(bundle.recipe_digest, "box"): dict(grasp_width_m=recipe["box"]["width"],
             grasp_depth_m=recipe["box"]["grasp_depth"], height_m=recipe["box"]["height"]),
             (bundle.recipe_digest, "slip_sheet"): dict(grasp_width_m=.03, grasp_depth_m=0.,
             height_m=recipe["slip_sheet"]["thickness"])}
    transport = LocalTransport(tmp_path / "omx.sqlite3", tasks, counters, rearm=True,
                               accepted_cell=bundle.cell_digest, accepted_items=items)
    dispatcher = CellJobDispatcher(jobs, tasks, transport, {"omx_01": "omx_01_control"},
                                   grant_revisions={"omx_01_control": {"capability_revision": "cell-transfer-v1",
                                   "config_revision": "cell-config-v1"}}, deployment_profile="simulation")
    registry = CellGoalRegistry((CellGoalProducer(producer_id="gazebo-pose", token="pose-secret",
        workcell_id="omx_01", instance_id="omx_01_control", recipe_sha256=bundle.recipe_digest,
        cell_sha256=bundle.cell_digest, evaluator_revisions=("placement-v1",), max_age_s=5,
        valid_until=datetime(2030, 1, 1, tzinfo=timezone.utc)),))
    goals = CellGoalEvidenceService(jobs, registry, GoalEvidenceStore(path))
    for ordinal, step in enumerate(bundle.steps):
        result = dispatcher.dispatch_next()
        if ordinal == 4:
            assert result["state"] == "HOLD"
            grant = counters["submits"][-1]
            assert grant.cell_transfer.item == "slip_sheet"
            assert transport.store.get_action(grant.action_id)["reason"] == "PHASE_RUNNER_START_UNKNOWN"
            assert len(counters["commands"]) == 16
            assert transport.store.action_phases(grant.action_id) == []
            assert len(transport.planning_errors) == 1
            assert "GRASP_DEPTH_BELOW_FINGERTIPS" in str(transport.planning_errors[0])
            assert jobs.get(mission_id)["steps"][ordinal + 1]["status"] == "WAITING"
            for kind, identity in accepted.resources:
                assert tasks.resource_claims(resource_kind=kind, resource_id=identity)
            return
        assert result["state"] == "ACTION_SUCCEEDED", {"ordinal": ordinal, "result": result}
        grant = counters["submits"][-1]
        assert grant.cell_transfer.step_index == ordinal
        assert grant.cell_transfer.item == step.invocation.inputs["item"]
        assert grant.cell_transfer.pallet == step.invocation.inputs["pallet_id"]
        before = len(counters["commands"])
        dispatcher.dispatch_next()
        assert len(counters["commands"]) == before == 4 * (ordinal + 1)
        assert tasks.resource_claims(resource_kind="workcell", resource_id="omx_01")
        terminal = datetime.fromisoformat(transport.get(grant)["observed_at"]).timestamp()
        evidence = _evidence(grant, terminal)
        evidence["recipe_sha256"] = bundle.recipe_digest
        evidence["cell_sha256"] = bundle.cell_digest
        for field, pose in (("model_pose_base", grant.cell_transfer.place),
                            ("initial_model_pose_base", grant.cell_transfer.pick)):
            evidence[field] = dict(x_m=pose.x, y_m=pose.y, z_m=pose.z, roll_rad=0., pitch_rad=0., yaw_rad=pose.yaw)
        goals.now = lambda: terminal + .02
        assert goals.submit(token="pose-secret", mission_id=mission_id, raw_evidence=evidence)["state"] == (
            "GOAL_CONFIRMED" if ordinal == 17 else "READY")
    pytest.fail("the original thin sheet unexpectedly bypassed the fingertip guard")
