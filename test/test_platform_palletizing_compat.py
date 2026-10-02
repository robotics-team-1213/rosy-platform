"""The installed palletizing wheel owns the implementation behind legacy rosy_cell imports."""

from dataclasses import replace
from hashlib import sha256
import math
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
CELL_ROOT = ROOT / "src" / "site" / "cell"
if str(CELL_ROOT) not in sys.path:
    sys.path.insert(0, str(CELL_ROOT))

from rosy.processes.palletizing.cell import CellConfig, Pose, load_cell  # noqa: E402
from rosy.processes.palletizing.compiler import CompileError, Job, Step, carry_z, compile_job  # noqa: E402
from rosy.processes.palletizing import compiler as process_compiler  # noqa: E402
from rosy.processes.palletizing.plan_bundle import compile_plan_bundle  # noqa: E402
from rosy.processes.palletizing.recipe import Recipe, load_recipe  # noqa: E402
from rosy_cell.cell import CellConfig as LegacyCellConfig  # noqa: E402
from rosy_cell.cell import Pose as LegacyPose  # noqa: E402
from rosy_cell.cell import load_cell as legacy_load_cell  # noqa: E402
from rosy_cell.compiler import CompileError as LegacyCompileError  # noqa: E402
from rosy_cell.compiler import Job as LegacyJob  # noqa: E402
from rosy_cell.compiler import Step as LegacyStep  # noqa: E402
from rosy_cell.compiler import carry_z as legacy_carry_z  # noqa: E402
from rosy_cell.compiler import compile_job as legacy_compile_job  # noqa: E402
from rosy_cell.compiler import Frame as LegacyCompilerFrame  # noqa: E402
from rosy_cell.compiler import Pose as LegacyCompilerPose  # noqa: E402
from rosy_cell.compiler import Recipe as LegacyCompilerRecipe  # noqa: E402
from rosy_cell.recipe import Recipe as LegacyRecipe  # noqa: E402
from rosy_cell.recipe import load_recipe as legacy_load_recipe  # noqa: E402

FIX = CELL_ROOT / "test" / "fixtures"
TOLERANCE = {"tol_m": 1e-6}


def _inputs(recipe_edit: tuple[str, str] = ("", "")) -> tuple[Recipe, CellConfig]:
    recipe_text = (FIX / "recipe_two_layer.yaml").read_text(encoding="utf-8")
    if recipe_edit != ("", ""):
        recipe_text = recipe_text.replace(*recipe_edit, 1)
    cell_text = (FIX / "cell_demo.yaml").read_text(encoding="utf-8")
    return load_recipe(recipe_text), load_cell(cell_text)


def test_legacy_cell_exports_are_the_canonical_process_types_and_functions():
    assert LegacyCellConfig is CellConfig
    assert LegacyPose is Pose
    assert LegacyRecipe is Recipe
    assert LegacyCompileError is CompileError
    assert LegacyJob is Job
    assert LegacyStep is Step
    assert LegacyCompilerFrame is process_compiler.Frame
    assert LegacyCompilerPose is process_compiler.Pose
    assert LegacyCompilerRecipe is process_compiler.Recipe
    assert legacy_load_cell is load_cell
    assert legacy_load_recipe is load_recipe
    assert legacy_compile_job is compile_job
    assert legacy_carry_z is carry_z


def test_palletizing_process_preserves_fixture_job_and_converts_transfer_pairs():
    recipe, cell = _inputs()
    job = compile_job(recipe, cell, **TOLERANCE)

    assert len(job.steps) == 62
    assert len(job.recipe_hash) == len(job.cell_hash) == 64
    assert carry_z(recipe, cell, **TOLERANCE) == pytest.approx(0.112)
    assert job.steps[0].kind == "pick"
    assert job.steps[1].kind == "place"
    assert job.steps[1].target.x == pytest.approx(0.295)
    assert job.steps[1].target.y == pytest.approx(0.075)
    assert job.steps[1].target.z == pytest.approx(0.02)
    assert job.steps[1].target.yaw == pytest.approx(math.pi / 2)
    assert [(step.kind, step.pallet) for step in job.steps if step.kind == "pallet_done"] == [
        ("pallet_done", "A"),
        ("pallet_done", "B"),
    ]

    compiled = compile_plan_bundle(
        job,
        recipe,
        cell,
        process_artifact_digest=sha256(b"rosy-palletizing-0.1.0").hexdigest(),
        tol_m=1e-6,
    )
    assert len(compiled.bundle.steps) == 30
    assert [step.ordinal for step in compiled.bundle.steps] == list(range(30))
    assert compiled.bundle.recipe_digest == recipe.content_hash
    assert compiled.bundle.cell_digest == cell.content_hash
    assert [(marker.after_step_ordinal, marker.pallet_id) for marker in compiled.ledger_markers] == [
        (15, "A"),
        (30, "B"),
    ]
    first = compiled.bundle.steps[0].invocation
    assert (first.skill_id, first.version) == ("pallet.transfer", "1.0.0")
    assert set(first.inputs["home_pose_base"]) == {"x_m", "y_m", "z_m", "yaw_rad"}
    assert first.inputs["item"] == "box"
    assert first.inputs["source_pose_base"]["y_m"] == pytest.approx(0.2)
    assert first.inputs["destination_pose_base"]["x_m"] == pytest.approx(0.295)
    assert first.inputs["source_approach_z_base_m"] == pytest.approx(0.07)
    assert first.inputs["destination_approach_z_base_m"] == pytest.approx(0.07)


def test_palletizing_process_keeps_depalletize_order_and_ledger_markers():
    recipe, cell = _inputs(("mode: palletize", "mode: depalletize"))
    compiled = compile_plan_bundle(
        compile_job(recipe, cell, **TOLERANCE),
        recipe,
        cell,
        process_artifact_digest=sha256(b"rosy-palletizing-0.1.0").hexdigest(),
        tol_m=1e-6,
    )

    assert compiled.bundle.steps[0].invocation.inputs["pallet_id"] == "B"
    assert [(marker.after_step_ordinal, marker.pallet_id) for marker in compiled.ledger_markers] == [
        (15, "B"),
        (30, "A"),
    ]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda job: replace(job, steps=job.steps[:1] + job.steps[2:]),
        lambda job: replace(job, steps=(replace(job.steps[0], item="slip_sheet"),) + job.steps[1:]),
        lambda job: replace(job, steps=job.steps[:-1]),
    ],
)
def test_process_plan_rejects_broken_transfer_pairs_and_pallet_markers(mutate):
    recipe, cell = _inputs()
    job = mutate(compile_job(recipe, cell, **TOLERANCE))

    with pytest.raises(ValueError):
        recipe, cell = _inputs()
        compile_plan_bundle(
            job,
            recipe,
            cell,
            process_artifact_digest=sha256(b"rosy-palletizing-0.1.0").hexdigest(),
            tol_m=1e-6,
        )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda job: replace(job, recipe_hash="0" * 64),
        lambda job: replace(job, cell_hash="1" * 64),
        lambda job: replace(job, carry_z=job.carry_z + 0.01),
        lambda job: replace(job, steps=(job.steps[0], replace(job.steps[1], target=replace(job.steps[1].target, x=0.3)))
                                      + job.steps[2:]),
    ],
)
def test_process_plan_rejects_tampered_step_carry_height_or_source_digest(mutate):
    recipe, cell = _inputs()
    job = mutate(compile_job(recipe, cell, **TOLERANCE))

    with pytest.raises(ValueError, match="current recipe/cell compilation"):
        compile_plan_bundle(
            job,
            recipe,
            cell,
            process_artifact_digest=sha256(b"rosy-palletizing-0.1.0").hexdigest(),
            tol_m=1e-6,
        )


def test_palletizing_process_has_no_ros_runtime_import():
    # 이 시험은 루트 test/ 묶음과 한 프로세스를 쓴다 — CI(ROS 컨테이너)에서는 앞선
    # 어느 시험이 이미 rclpy 를 적재했을 수 있다(2026-10-02 실행 36972584689 적색).
    # 계약은 '팔레타이징이 rclpy 를 끌어들이지 않는다'이므로, 이 import 로 새로
    # 생긴 모듈만 검사한다.
    before = set(sys.modules)
    import rosy.processes.palletizing  # noqa: PLC0415

    assert rosy.processes.palletizing.__name__ == "rosy.processes.palletizing"
    assert not ({"rclpy", "rclpy.node"} & set(sys.modules) - before)


# C3b (merged onto D-413): grasp_depth, the tool fingertip overhang and the carry_z hang
# rule live in the palletizing module; the legacy facade only re-exports them.
DEPTH = ("height: 0.02, mass_kg: 0.01}", "height: 0.02, mass_kg: 0.01, grasp_depth: 0.008}")


def test_process_module_owns_grasp_depth_and_fingertip_overhang():
    recipe, cell = _inputs(DEPTH)
    assert recipe.box.grasp_depth == 0.008
    assert cell.fingertip_overhang_m == 0.0025
    flat_recipe, _ = _inputs()
    deep, flat = compile_job(recipe, cell, **TOLERANCE), compile_job(flat_recipe, cell, **TOLERANCE)
    box_pairs = [(a, b) for a, b in zip(flat.steps, deep.steps) if a.item == "box"]
    assert box_pairs and all(b.target.z == pytest.approx(a.target.z - 0.008) for a, b in box_pairs)
    # hang = max(0.02 - 0.008, sheet 0.002, overhang 0.0025) = 0.012
    assert carry_z(recipe, cell, **TOLERANCE) == pytest.approx(0.042 + 0.012 + 0.05)
    assert legacy_carry_z(recipe, cell, **TOLERANCE) == carry_z(recipe, cell, **TOLERANCE)


def test_process_module_refuses_fingertips_below_the_box():
    recipe, cell = _inputs(("height: 0.02, mass_kg: 0.01}", "height: 0.02, mass_kg: 0.01, grasp_depth: 0.018}"))
    with pytest.raises(CompileError, match="fingertip"):
        compile_job(recipe, cell, **TOLERANCE)


def test_plan_bundle_recompiles_jobs_with_grasp_depth():
    recipe, cell = _inputs(DEPTH)
    job = compile_job(recipe, cell, **TOLERANCE)
    compiled = compile_plan_bundle(job, recipe, cell,
                                   process_artifact_digest=sha256(b"rosy-palletizing-0.1.0").hexdigest(),
                                   tol_m=1e-6)
    first = compiled.bundle.steps[0].invocation
    assert first.inputs["carry_z_base_m"] == pytest.approx(job.carry_z)
    assert first.inputs["source_pose_base"]["z_m"] == pytest.approx(job.steps[0].target.z)
    with pytest.raises(ValueError, match="must match the current recipe/cell compilation"):
        compile_plan_bundle(compile_job(*_inputs(), **TOLERANCE), recipe, cell,
                            process_artifact_digest=sha256(b"x").hexdigest(), tol_m=1e-6)
