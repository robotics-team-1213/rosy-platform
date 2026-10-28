"""Photo-layout provenance and three physical layers must precede a stacking success claim."""
import importlib
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def fixture():
    assert importlib.util.find_spec('mapped_stack_fixture'), 'mapped physical stacking fixture is missing'
    return importlib.import_module('mapped_stack_fixture')


def test_board_uses_the_confluence_cad_and_long_bars_use_both_arms():
    mod = fixture()
    assert mod.FIXTURE['board_size_m'] == [1.22, 2.44, .018]
    assert mod.FIXTURE['confluence_page'] == '8683759'
    assert mod.FIXTURE['cad_attachment'] == '8585450'
    assert mod.FIXTURE['photo_attachment'] == '8585456'
    assert mod.FIXTURE['cell_pose_scope'] == 'PHOTO_DERIVED_NOMINAL_NOT_CALIBRATED'
    assert [p['arm'] for p in mod.plan()] == [0, 1, 0]
    assert all(p['size'] == [.09, .03, .03] for p in mod.plan())
    assert [p['target'][2] for p in mod.plan()] == pytest.approx([.04, .07, .10])


def test_all_grasp_carry_and_three_layer_targets_have_nominal_profile_ik():
    mod = fixture()
    for item in mod.plan():
        arm = item['arm']
        for point in (mod.home(arm), [.16, -.047, .04], [.16, -.047, .145],
                      [.16, 0., .145], item['target']):
            joints = mod.solve(arm, point, 0.)
            assert len(joints) == 5


def test_reference_controller_is_a_distinct_mapped_scenario():
    import run_catalog
    row = run_catalog.normalize('omx-map-long-stack', {'seed': 42})
    assert row['trials'] == 3 and row['fixture'] == 'confluence-map-long-stack-v1'
    with pytest.raises(ValueError):
        run_catalog.normalize('omx-map-long-stack', {'seed': 42, 'attachment': True})
