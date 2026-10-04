"""Canonical Fleet composition for a private, network-none G2 validation run."""
import argparse
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path

from g2_common import ROOT, configure_imports
from g2_ports import ObserverClient, StagingTransport, isolation_guard


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True, type=Path)
    args = parser.parse_args()
    isolation_guard(ROOT)
    configure_imports()
    import yaml
    import uvicorn
    from fleet.server.app import create_app
    from fleet.server.console import FleetConsole
    from fleet.server.cell_compiler import PalletizingCellJobCompiler
    from fleet.server.cell_goal_evidence_registry import CellGoalProducer, CellGoalRegistry
    from fleet.server.local_action_transport import UnixLocalActionTransport
    from fleet.server.mission_store import MissionStore
    from fleet.server.mission_service import MissionService
    from fleet.server.proposal_store import ProposalStore
    from fleet.server.task_store import FleetTaskStore
    from fleet.server.task_service import FleetTaskService
    from rosy.execution.site.item_pose import ItemPoseTolerance
    from omx_adapter.pose_plan import CellPlanningProfile
    from cell_sim_tools import spawn_infeed_block
    run = args.run.resolve()
    credentials = json.loads((run / "credentials.json").read_text())
    recipe = json.loads((run / "recipe.json").read_text())
    cell = json.loads((run / "cell.json").read_text())
    compiler = PalletizingCellJobCompiler(tol_m=0.001)
    bundle = compiler.compile(recipe, cell).plan_bundle
    profile = CellPlanningProfile.load(ROOT / "deploy/robot/omx/sim/cell_profile.yaml")
    observer = ObserverClient(run / "observer.sock")
    # This callback receives grants only from the real StepJobDispatcher.
    transport = StagingTransport(UnixLocalActionTransport(run / "uds", timeout_s=2),
                                 observer=observer, stage=spawn_infeed_block,
                                 directory=run / "staging", box=recipe["box"])
    database = run / "fleet.sqlite3"
    principals = {sha256(row["token"].encode()).hexdigest():
                  {"principal_id": row["principal_id"], "role": row["role"]}
                  for row in credentials["site"].values()}
    registry = CellGoalRegistry((CellGoalProducer(
        "g2-observer", credentials["evidence"], "omx_cell_sim", "omx_cell_sim_01",
        bundle.recipe_digest, bundle.cell_digest, ("g2-measured-pose-v1",), 5,
        datetime.now(timezone.utc)+timedelta(hours=4)),))
    app = create_app(FleetConsole([], []),
                     task_service=FleetTaskService(FleetTaskStore(database), robot_ids=set()),
                     mission_service=MissionService(MissionStore(database)), proposal_store=ProposalStore(database),
                     cell_job_compiler=compiler, site_users=principals, start_task_dispatcher=False,
                     omx_instances={"omx_cell_sim": "omx_cell_sim_01"}, omx_socket_root=run / "uds",
                     enable_mission_dispatcher=True, omx_action_transport=transport, deployment_profile="simulation",
                     omx_cell_grant_revisions={"omx_cell_sim_01": {
                         "capability_revision": "cell-transfer-v1", "config_revision": profile.revision}},
                     cell_item_pose_tolerance=ItemPoseTolerance.from_mapping(yaml.safe_load(
                         (ROOT / "deploy/robot/omx/sim/item_pose_goal.yaml").read_text())),
                     cell_goal_registry=registry, cell_app_service_id="g2-cell-service")
    uvicorn.run(app, host="127.0.0.1", port=8090, access_log=False)


if __name__ == "__main__":
    main()
