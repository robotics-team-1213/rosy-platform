"""The Gazebo diagnostic uses current process imports and a validated Cell grant."""

from datetime import datetime, timezone
from pathlib import Path
import runpy
import subprocess
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "deploy/robot/omx/probe_cell_transfer.py"


def test_probe_bootstraps_extracted_process_in_isolated_python():
    code = (
        "import os, runpy, sys; "
        f"sys.path.append({str(Path(yaml.__file__).resolve().parents[1])!r}); "
        f"os.environ['ROSY_SIM_REPO'] = {str(ROOT)!r}; "
        f"runpy.run_path({str(PROBE)!r}, run_name='cell_probe_contract'); "
        "from rosy.processes.palletizing.compiler import compile_job; "
        "from rosy_cell.compiler import compile_job as legacy; "
        "assert legacy is compile_job"
    )
    result = subprocess.run([sys.executable, "-I", "-B", "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_probe_grant_is_validated_cell_payload_without_rgbd_placeholders(monkeypatch, tmp_path):
    monkeypatch.setenv("ROSY_SIM_REPO", str(ROOT))
    namespace = runpy.run_path(str(PROBE), run_name="cell_probe_contract")
    from core_common.protocol.schemas import FleetCellTransferGrant
    from omx_adapter.action_api import action_grant_digest
    from omx_adapter.action_store import ActionStore
    from rosy_cell.cell import load_cell
    from rosy_cell.compiler import compile_job
    from rosy_cell.recipe import load_recipe

    example = ROOT / "operations/processes/cell/examples/omx_sim"
    cell = load_cell((example / "cell.yaml").read_text(encoding="utf-8"))
    recipe = load_recipe((example / "recipe.yaml").read_text(encoding="utf-8"))
    job = compile_job(recipe, cell, tol_m=.001)
    grant = namespace["build_probe_grant"](
        job, cell, transfer_index=1, profile_revision="a" * 64,
        now=datetime(2026, 10, 3, tzinfo=timezone.utc), action_id="probe-action-1",
    )
    assert isinstance(grant, FleetCellTransferGrant)
    assert FleetCellTransferGrant.model_validate(grant.model_dump()) == grant
    assert grant.request_digest == action_grant_digest(grant)
    payload = grant.cell_transfer
    assert payload.job_id == "c3b-omx-sim" and payload.step_index == 1
    assert payload.recipe_sha256 == job.recipe_hash and payload.cell_sha256 == job.cell_hash
    assert payload.frame == "robot_base" and payload.pallet == "A" and payload.item == "box"
    assert payload.pick.model_dump() == vars(job.steps[2].target)
    assert payload.place.model_dump() == vars(job.steps[3].target)
    assert "source_evidence" not in grant.model_dump()
    assert "observation_revision" not in grant.model_dump()
    store = ActionStore(tmp_path / "owner.sqlite3")
    namespace["create_probe_action"](store, grant)
    record = store.get_action(grant.action_id)
    assert record["action_id"] == grant.action_id and record["observation_id"] == ""
    for index in (-1, True, 18):
        with pytest.raises(ValueError):
            namespace["build_probe_grant"](
                job, cell, transfer_index=index, profile_revision="a" * 64,
                now=datetime(2026, 10, 3, tzinfo=timezone.utc), action_id="probe-action-2",
            )


def test_probe_rejects_tilted_or_lowered_earlier_block_even_at_same_xy(monkeypatch):
    monkeypatch.setenv("ROSY_SIM_REPO", str(ROOT))
    namespace = runpy.run_path(str(PROBE), run_name="cell_probe_contract")
    evaluate = namespace["evaluate_placement"]
    target = dict(x=.15, y=.02, z=.025, yaw=0.)
    upright = dict(x=.15, y=.02, z=.025, roll=0., pitch=0., yaw=0.)
    # Target is 15 mm below the 40 mm item top; model origin is its 25 mm centre.
    error, ok = evaluate(upright, target, height_m=.03, grasp_depth_m=.015)
    assert ok and error["top_z_m"] == pytest.approx(0.)
    for override in ({"pitch": .2}, {"yaw": .2}, {"z": .02}, {"x": .16}):
        _, ok = evaluate({**upright, **override}, target, height_m=.03, grasp_depth_m=.015)
        assert not ok, override
    _, ok = evaluate({**upright, "yaw": 3.141592653589793}, target, height_m=.03, grasp_depth_m=.015)
    assert ok  # Rectangular boxes retain the existing modulo-pi yaw convention.
