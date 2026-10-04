"""Bounded canonical G2 route. Only explicit isolated simulation mode can admit work."""
import argparse
from datetime import datetime
from hashlib import sha256
from http.client import HTTPConnection
import importlib
import json
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import time
import uuid

from g2_common import (
    ROOT, SOURCE_PATHS, box_only_document, configure_imports, controller_readiness,
    prepare_world, verify_module_origins,
)
from g2_ports import ObserverClient, fresh_evidence, isolation_guard, write_json


class FleetClient:
    def __init__(self, run, credentials):
        self.run, self.credentials, self.sequence = run, credentials, 0

    def request(self, method, path, body=None, *, role="approver", evidence=False):
        token = self.credentials["evidence"] if evidence else self.credentials["site"][role]["token"]
        headers = {"Accept": "application/json", "Content-Type": "application/json",
                   "X-Goal-Evidence-Token" if evidence else "Authorization":
                   token if evidence else "Bearer "+token}
        connection = HTTPConnection("127.0.0.1", 8090, timeout=3)
        try:
            connection.request(method, path, None if body is None else json.dumps(body), headers)
            response = connection.getresponse()
            raw = response.read(4*1024*1024+1)
            if len(raw) > 4*1024*1024:
                raise RuntimeError("Fleet response exceeds bounded evidence size")
            value = json.loads(raw)
            self.sequence += 1
            write_json(self.run / "http" / f"{self.sequence:05d}.json",
                       {"method": method, "path": path, "status": response.status,
                        "principal": "g2-observer" if evidence else self.credentials["site"][role]["principal_id"],
                        "response": value})
            if response.status >= 300:
                raise RuntimeError(f"Fleet {method} refused with HTTP {response.status}; no automatic mutation retry")
            return value
        finally:
            connection.close()


class Children:
    def __init__(self, run):
        self.run, self.processes, self.logs = run, [], []

    def start(self, name, command, *, env=None):
        log = (self.run / (name+".log")).open("xb")
        self.logs.append(log)
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                   env=env, start_new_session=True)
        self.processes.append((name, process))
        return process

    def assert_alive(self):
        for name, process in self.processes:
            if process.poll() is not None:
                raise RuntimeError(name+" exited before run completed")

    def close(self):
        for _, process in reversed(self.processes):
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        deadline = time.monotonic()+10
        for _, process in self.processes:
            try:
                process.wait(timeout=max(0.01, deadline-time.monotonic()))
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=3)
        absent = True
        groups = []
        for name, process in self.processes:
            try:
                os.killpg(process.pid, 0)
                os.killpg(process.pid, signal.SIGKILL)
                time.sleep(0.1)
                os.killpg(process.pid, 0)
                absent = False
                groups.append(name)
            except ProcessLookupError:
                pass
        for log in self.logs:
            log.close()
        write_json(self.run / "process-cleanup.json", {"verified_absent": absent, "remaining_groups": groups})
        return absent


def preflight(run, *, sdk):
    configure_imports()
    import yaml
    from fleet.server.cell_compiler import PalletizingCellJobCompiler
    from omx_adapter.pose_plan import CellPlanningProfile
    original = yaml.safe_load((ROOT / "operations/processes/cell/examples/omx_sim/recipe.yaml").read_text())
    cell = yaml.safe_load((ROOT / "operations/processes/cell/examples/omx_sim/cell.yaml").read_text())
    recipe = box_only_document(original)
    compilation = PalletizingCellJobCompiler(tol_m=0.001).compile(recipe, cell)
    if len(compilation.plan_bundle.steps) != 16 or tuple(compilation.ledger_markers) != (
            {"after_step_ordinal": 8, "pallet_id": "A"}, {"after_step_ordinal": 16, "pallet_id": "B"}):
        raise RuntimeError("reviewed box-only16 compiler shape changed")
    profile = CellPlanningProfile.load(ROOT / "deploy/robot/omx/sim/cell_profile.yaml")
    if sdk:
        for module in ("rclpy", "control_msgs.msg", "controller_manager_msgs.srv", "gz.transport13",
                       "gz.msgs10.pose_v_pb2", "rosy_agent.omx_cell_owner", "fleet.server.app"):
            importlib.import_module(module)
    origins = verify_module_origins({
        "core_common.protocol.schemas": "contracts/foundation",
        "fleet.server.app": "operations/fleet",
        "rosy.processes.palletizing.compiler": "operations/processes/palletizing/src",
        "rosy.execution.site.item_pose": "operations/execution/src",
        "rosy.integrations.robots.omx.transfer_provider": "integrations/robots/omx/src",
        "omx_adapter.pose_plan": "middleware/apps/device/omx/adapter",
        "rosy_agent.omx_cell_owner": "middleware/apps/device/omx/agent/src",
    })
    for name, document in (("original-recipe", original), ("recipe", recipe), ("cell", cell)):
        write_json(run / (name+".json"), document)
    write_json(run / "preflight.json", {
        "source_paths": list(SOURCE_PATHS), "sdk_imports_verified": sdk,
        "recipe_sha256": compilation.plan_bundle.recipe_digest,
        "cell_sha256": compilation.plan_bundle.cell_digest, "profile_revision": profile.revision,
        "transfer_count": 16, "pallet_markers": list(compilation.ledger_markers),
        "scenario": "box-only16", "sim_aid": True, "sim_gripper_sensor": True,
        "manual_slip_sheet_checkpoint": "NOT_RUN", "original_sheet_contract": "NOT_RUN",
        "source_import_closure": "VERIFIED", "installed_wheel_artifact_closure": "NOT_RUN",
        "source_module_origins": origins,
        "source_sha256": {str(path.relative_to(ROOT)): sha256(path.read_bytes()).hexdigest()
                          for prefix in SOURCE_PATHS for path in sorted((ROOT / prefix).rglob("*.py"))
                          if "__pycache__" not in path.parts and "test" not in path.parts},
        "full_g2": False, "runtime": "NOT_RUN"})
    return recipe, cell, profile


def goal_submission(job, step, initial, final):
    terminal_at = datetime.fromisoformat(step["result"]["observed_at"].replace("Z", "+00:00")).timestamp()
    if min(final["observed_at"], final["gripper_observed_at"]) <= terminal_at:
        raise RuntimeError("final independent measurements must follow terminal success")
    return {"mission_id": job["mission_id"], "evidence": {
        "producer_id": "g2-observer", "evidence_id": uuid.uuid4().hex,
        "evidence_source": "sim_model_pose", "evaluator_revision": "g2-measured-pose-v1",
        "job_id": job["job_id"], "step_id": step["step_id"], "step_index": step["step_index"],
        "action_id": step["action_id"], "attempt_id": step["attempt_id"],
        "request_digest": step["request_digest"], "recipe_sha256": job["recipe_digest"],
        "cell_sha256": job["cell_digest"], "model_id": final["model_id"],
        "observation_id": final["observation_id"], "observation_digest": final["observation_digest"],
        "evidence_revision": "g2-independent-gazebo-pose-v1", "observed_at": final["observed_at"],
        "model_pose_base": final["model_pose_base"],
        "initial_observation_id": initial["observation_id"],
        "initial_observation_digest": initial["observation_digest"],
        "initial_observed_at": initial["observed_at"], "initial_model_pose_base": initial["model_pose_base"],
        "gripper_state": "OPEN", "gripper_evidence_id": final["observation_id"]+"-gripper",
        "gripper_evidence_revision": "g2-independent-gripper-joint-v1",
        "gripper_observed_at": final["gripper_observed_at"]}}


def verify_previous(job, observer, run, ordinal):
    from rosy.execution.site.item_pose import ItemPoseEvidence, item_pose_predicate, verify_item_at_pose
    records = []
    for step in job["steps"]:
        if step["status"] != "GOAL_CONFIRMED":
            continue
        observation = observer("cell_"+step["action_id"], require_open=True)
        pose = observation["model_pose_base"]
        item_id = f"{job['mission_id']}:{step['step_index']}"
        evidence = ItemPoseEvidence.from_mapping({
            "predicate_id": item_id+":item_at_pose", "item_id": item_id,
            "evidence_source": "sim_model_pose", "evidence_id": observation["observation_id"],
            "producer_id": "g2-observer", "model_name": observation["model_id"], "frame": "robot_base",
            "pose": {key: pose[key+suffix] for key, suffix in
                     (("x", "_m"), ("y", "_m"), ("z", "_m"), ("roll", "_rad"),
                      ("pitch", "_rad"), ("yaw", "_rad"))},
            "observed_at": observation["observed_at"], "action_id": step["action_id"],
            "attempt_id": step["attempt_id"], "gripper_state": "OPEN",
            "gripper_evidence_id": observation["observation_id"]+"-gripper"})
        verdict = verify_item_at_pose(item_pose_predicate(job["mission_id"], step["step_index"],
                                      step["step"]["goal_predicate"]), evidence,
                                      now=time.time(), max_age_s=5)
        records.append({"observation": observation, "satisfied": verdict.satisfied,
                        "reasons": list(verdict.reasons), "errors": dict(verdict.errors)})
    write_json(run / "placements" / f"prior-{ordinal:02d}.json", {"observations": records})
    if any(row["satisfied"] is not True for row in records):
        raise RuntimeError("an earlier measured placement was disturbed")


def execute(run, recipe, cell, profile, children):
    credentials = {"site": {name: {"principal_id": principal, "role": role,
                                   "token": secrets.token_urlsafe(32)} for name, principal, role in (
        ("service", "g2-cell-service", "service"), ("proposer", "g2-sim-proposer", "operator"),
        ("approver", "g2-sim-approver", "operator"), ("viewer", "g2-fence-viewer", "viewer"))},
        "evidence": secrets.token_urlsafe(32)}
    write_json(run / "credentials.json", credentials)
    world = run / "workcell.sdf"
    write_json(run / "world-derivation.json", prepare_world(
        ROOT / "integrations/simulation/gazebo/worlds/omx_cell_workcell_sim_aid.sdf", world))
    env = dict(os.environ, OMX_CELL_WORLD=str(world.with_suffix("")), OMX_CELL_DOMAIN_ID="137",
               OMX_CELL_LOG_DIR=str(run), ROS_DOMAIN_ID="137")
    os.environ["ROS_DOMAIN_ID"] = "137"
    children.start("gazebo-launch", ["bash", str(ROOT / "deploy/robot/omx/run_cell_sim.sh")], env=env)
    write_json(run / "controller-readiness.json", controller_readiness())
    children.start("observer", [sys.executable, str(Path(__file__).with_name("g2_observer.py")),
                                "--socket", str(run / "observer.sock"),
                                "--open-position", str(profile.gripper_open)], env=env)
    deadline = time.monotonic()+90
    while not (run / "observer.sock").exists():
        children.assert_alive()
        if time.monotonic() > deadline:
            raise RuntimeError("observer readiness timed out")
        time.sleep(0.2)
    # Initial dispatch stays closed throughout process startup.
    children.start("owner", [sys.executable, str(Path(__file__).with_name("g2_owner.py")),
                             "--run", str(run)], env=env)
    children.start("fleet", [sys.executable, str(Path(__file__).with_name("g2_fleet.py")),
                             "--run", str(run)], env=env)
    # Includes the owner's bounded, durable Pilot-seat startup homing and measured settling.
    deadline = time.monotonic()+300
    client = FleetClient(run, credentials)
    while True:
        children.assert_alive()
        if time.monotonic() > deadline:
            raise RuntimeError("Fleet/UDS readiness timed out")
        if (run / "uds/omx_cell_sim_01/control.sock").exists():
            try:
                control = client.request("GET", "/api/fleet/dispatch-control")
                break
            except (ConnectionError, OSError):
                pass
        time.sleep(0.2)
    if control["dispatch_enabled"] is not False:
        raise RuntimeError("Fleet must start with dispatch closed")
    refs = {}
    for kind, document in (("recipe", recipe), ("cell", cell)):
        saved = client.request("POST", f"/api/fleet/cell-app/documents/{kind}/g2-{kind}",
                               {"document": document, "expected_digest": None}, role="proposer")
        refs[kind+"_id"], refs[kind+"_digest"] = saved["id"], saved["digest"]
    preview = client.request("POST", "/api/fleet/cell-app/compile", refs, role="proposer")
    if preview["summary"]["transfer_count"] != 16:
        raise RuntimeError("Cell app preview differs from reviewed scenario")
    proposal = client.request("POST", "/api/fleet/cell-app/proposals", {
        **refs, "request_key": "g2-"+uuid.uuid4().hex,
        "workcell_id": "omx_cell_sim", "instance_id": "omx_cell_sim_01"}, role="proposer")
    mission_id = proposal["proposal"]["proposal_id"]
    client.request("POST", "/api/fleet/dispatch/rearm", {"expected_generation": control["generation"]})
    control = client.request("GET", "/api/fleet/dispatch-control")
    client.request("POST", f"/api/fleet/missions/{mission_id}/admit",
                   {"expected_generation": control["generation"]})
    observer, sent = ObserverClient(run / "observer.sock"), set()
    deadline = time.monotonic()+7200
    while time.monotonic() < deadline:
        children.assert_alive()
        job = client.request("GET", f"/api/fleet/cell-jobs/{mission_id}")["job"]
        if job["status"] == "HOLD":
            raise RuntimeError("canonical Cell Job entered HOLD: "+str(job.get("reason")))
        if job["status"] == "GOAL_CONFIRMED":
            verify_previous(job, observer, run, 16)
            if len(sent) != 16 or len({step["action_id"] for step in job["steps"]}) != 16:
                raise RuntimeError("completion requires 16 distinct accepted attempts")
            claims = client.request("GET", "/api/fleet/resource-claims")["claims"]
            if any(row.get("owner_id") == mission_id and row.get("state") != "RELEASED" for row in claims):
                raise RuntimeError("completed job still holds resources")
            write_json(run / "happy-result.json", {"job": job, "claims": claims,
                       "happy_path": "PASS", "full_g2": False, "fault_matrix": "NOT_RUN",
                                                   "manual_slip_sheet_checkpoint": "NOT_RUN", "sim_aid": True,
                                                   "sim_gripper_sensor": True})
            return
        step = job["steps"][job["current_step_index"]]
        if step["status"] == "ACTION_SUCCEEDED" and step["action_id"] not in sent:
            staged = json.loads((run / "staging" / (step["action_id"]+".json")).read_text())
            final = observer("cell_"+step["action_id"], require_open=True)
            verify_previous(job, observer, run, step["step_index"])
            # Earlier-block verification may take time: refresh this placement last.
            final = observer("cell_"+step["action_id"], require_open=True)
            submission = goal_submission(job, step, staged["initial"], final)
            write_json(run / "placements" / (step["action_id"]+".json"), submission)
            client.request("POST", "/api/fleet/cell-goal-evidence", submission, evidence=True)
            sent.add(step["action_id"])
        time.sleep(0.3)
    raise RuntimeError("bounded two-hour G2 run exceeded; retain receipts and HOLD")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("host-preflight", "preflight", "run"), required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--approve-isolated-simulation", action="store_true")
    args = parser.parse_args()
    if args.mode == "run" and not args.approve_isolated_simulation:
        parser.error("run requires explicit --approve-isolated-simulation")
    if args.mode != "host-preflight":
        isolation_guard(ROOT)
    run = fresh_evidence(args.evidence)
    children = Children(run)
    outcome, error = "HOLD", None
    try:
        recipe, cell, profile = preflight(run, sdk=args.mode != "host-preflight")
        if args.mode == "run":
            execute(run, recipe, cell, profile, children)
        outcome = "PREFLIGHT_PASS" if args.mode != "run" else "HAPPY_PATH_PASS"
    except Exception as exc:
        error = type(exc).__name__+": "+str(exc)
    finally:
        cleanup = children.close()
        write_json(run / "result.json", {"result": outcome if cleanup else "CLEANUP_HOLD",
                                         "error": error, "cleanup_verified": cleanup, "full_g2": False,
                                         "fault_matrix": "NOT_RUN", "sim_aid": True, "sim_gripper_sensor": True})
    if outcome == "HOLD" or not cleanup:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
