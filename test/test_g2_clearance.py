"""The reviewed SIM fixture must exclude the measured nominal finger interference."""
import copy
import json
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT/'deploy/robot/omx'))
from g2_common import box_only_document, configure_imports
configure_imports()
from fleet.server.cell_compiler import PalletizingCellJobCompiler
from omx_adapter.pose_plan import CellPlanningProfile

MESHES = ROOT/'learning/envs/isaac/assets/open_manipulator_description/meshes/omx_f'


def fixture(original=False):
    example = ROOT/'operations/processes/cell/examples/omx_sim'
    recipe = yaml.safe_load((example/'recipe.yaml').read_text())
    cell = yaml.safe_load((example/'cell.yaml').read_text())
    return (recipe if original else box_only_document(recipe)), cell


def profile():
    return CellPlanningProfile.load(ROOT/'deploy/robot/omx/sim/cell_profile.yaml')


def test_reviewed_canonical_and_box_only_layouts_exclude_nominal_finger_interference():
    from g2_clearance import check_clearance
    for original in (False, True):
        recipe, cell = fixture(original)
        compiled = PalletizingCellJobCompiler(tol_m=.001).compile(recipe, cell)
        report = check_clearance(compiled.job, profile(), MESHES, box=recipe['box'])
        assert report['scope'] == 'NOMINAL_DESCENT_FINGER_ENVELOPE_ONLY'
        assert report['box_count'] == 16 and report['ordered_pairs'] == 120
        assert report['minimum_separation_beyond_inflation_m'] > .004
        assert report['inflation_m'] >= .002
        assert 'full_open_retreat' in report['uncovered'] and 'whole_arm' in report['uncovered']
        assert len(compiled.plan_bundle.steps) == (18 if original else 16)


def test_old_15mm_layout_has_deterministic_nominal_finger_interference():
    from g2_clearance import check_clearance
    recipe, cell = fixture()
    recipe['gap'] = .015
    for pallet in recipe['pallets']:
        pallet.update(length=.10, width=.08)
    for name, y in (('pallet_a', .01), ('pallet_b', -.09)):
        cell['frames'][name] = dict(origin=[.13, y, .01], x_point=[.23, y, .01], plane_point=[.13, y+.08, .01])
    job = PalletizingCellJobCompiler(tol_m=.001).compile(recipe, cell).job
    with pytest.raises(ValueError, match='NOMINAL_FINGER_INTERFERENCE'):
        check_clearance(job, profile(), MESHES, box=recipe['box'])


def test_mesh_drift_and_unreviewed_yaw_cannot_claim_known_geometry(tmp_path):
    from g2_clearance import check_clearance
    recipe, cell = fixture()
    job = PalletizingCellJobCompiler(tol_m=.001).compile(recipe, cell).job
    (tmp_path/'follower_07_gripper_motorized.stl').write_bytes(b'unreviewed')
    with pytest.raises(ValueError, match='UNSUPPORTED'):
        check_clearance(job, profile(), tmp_path, box=recipe['box'])
    changed = copy.deepcopy(job)
    next(step for step in changed['steps'] if step['kind']=='place')['target']['yaw'] = .3
    with pytest.raises(ValueError, match='UNSUPPORTED'):
        check_clearance(changed, profile(), MESHES, box=recipe['box'])
    with pytest.raises(ValueError, match='UNSUPPORTED'):
        check_clearance(job, profile(), MESHES, box={**recipe['box'], 'width': .04})


def test_all_64_box_only_phases_pass_original_profile_without_extending_duration():
    from omx_adapter.kinematics import ARM_JOINTS, OmxKinematics, TopDownPose
    from omx_adapter.manipulation_plan import ExecutionStateSnapshot
    from omx_adapter.pose_plan import AnalyticCellTransferPlanner, CellTransferRequest, validate_cell_transfer_plan
    recipe, cell = fixture()
    compiled = PalletizingCellJobCompiler(tol_m=.001).compile(recipe, cell)
    kin, limits = OmxKinematics.load(), profile()
    home = TopDownPose(**cell['home'])
    joints = dict(zip(ARM_JOINTS, kin.solve_top_down(home, limits.ik_limits()).joints))
    joints[limits.gripper_joint] = limits.gripper_open
    state = ExecutionStateSnapshot(sequence=1, joint_positions=joints, calibration_revision='sim',
        transform_revision='sim', planning_scene_revision=kin.planning_scene_revision, observed_at_monotonic_s=1.)
    planner = AnalyticCellTransferPlanner(kin, accepted_cell_sha256=lambda: compiled.plan_bundle.cell_digest,
        accepted_item_geometry=lambda sha, item: dict(grasp_width_m=.03, grasp_depth_m=.015, height_m=.03),
        monotonic=lambda: 1.)
    picks = [step for step in compiled.job['steps'] if step['kind']=='pick']
    places = [step for step in compiled.job['steps'] if step['kind']=='place']
    phases = []
    for index, (pick, place) in enumerate(zip(picks, places)):
        plan = planner.plan_transfer(CellTransferRequest(job_id='layout', recipe_sha256=compiled.plan_bundle.recipe_digest,
            cell_sha256=compiled.plan_bundle.cell_digest, step_index=index, item='box', home=home,
            pick=TopDownPose(**pick['target']), place=TopDownPose(**place['target']),
            pick_approach_z=pick['approach_z'], place_approach_z=place['approach_z'],
            carry_z=compiled.job['carry_z'], grasp_depth_m=.015, grasp_width_m=.03), limits, state)
        validate_cell_transfer_plan(plan, limits, kinematics_revision=kin.revision, now_monotonic_s=1.)
        phases.extend(plan.phases)
    assert len(phases) == 64
    assert max(phase.points[-1].time_from_start_s for phase in phases) < 30.


def test_runtime_preflight_saves_narrow_mesh_bound_report(tmp_path):
    # The CLI starts with a fresh import cache. Other collection tests intentionally
    # load the installed palletizing wheel, which the source-origin guard rejects.
    result = subprocess.run([
        sys.executable, "-c",
        "import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); "
        "from g2_common import configure_imports; configure_imports(); "
        "from g2_runner import preflight; preflight(Path(sys.argv[2]), sdk=False)",
        str(ROOT / 'deploy/robot/omx'), str(tmp_path),
    ], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=60)
    assert result.returncode == 0, result.stdout
    report = json.loads((tmp_path/'finger-envelope.json').read_text())
    assert report['scope'] == 'NOMINAL_DESCENT_FINGER_ENVELOPE_ONLY'
    assert report['mesh_binding'] == 'TRACKED_ASSETS_ONLY'
    assert report['box_count'] == 16
    preflight_report = json.loads((tmp_path / 'preflight.json').read_text())
    assert preflight_report['source_module_origins']['rosy.processes.palletizing.compiler'] == (
        'operations/processes/palletizing/src/rosy/processes/palletizing/compiler.py')


def test_changed_urdf_gripper_transform_is_unsupported_even_with_identical_meshes(tmp_path):
    from g2_clearance import check_clearance
    mesh_dir = tmp_path/'meshes/omx_f'
    mesh_dir.mkdir(parents=True)
    for source in MESHES.glob('follower_0[78]*.stl'):
        (mesh_dir/source.name).symlink_to(source)
    urdf = tmp_path/'urdf/omx_f/omx_f.urdf'
    urdf.parent.mkdir(parents=True)
    original = (MESHES.parents[1]/'urdf/omx_f/omx_f.urdf').read_text()
    urdf.write_text(original.replace('0.0295 0.0075 0', '0.0395 0.0075 0'))
    recipe, cell = fixture()
    job = PalletizingCellJobCompiler(tol_m=.001).compile(recipe, cell).job
    with pytest.raises(ValueError, match='UNSUPPORTED.*transform'):
        check_clearance(job, profile(), mesh_dir, box=recipe['box'])
