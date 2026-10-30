"""Held tilt is transient; the measured final stack still has the original envelope."""
import math
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import mapped_stack_fixture as f
from test_container_stack import held_scene,bodies,touching


def native_outer():
    fixture=touching(f.container_fixture(layers=3,case='nominal'))
    sample=held_scene(fixture,1,[-.00111265748,-.00006448844,-.00481344247,.99998778105])
    sample['boxes'][0]['position'][1]=-.000390554516
    sample['boxes'][0]['orientation']=[.000324849418,0.,0.,-1.]
    return fixture,sample


def test_native_small_held_overhang_can_plan_a_flat_final_footprint():
    fixture,sample=native_outer()
    command=f.cube_release_target(1,sample,.052,fixture=fixture)
    item=f.plan(True,fixture=fixture)[1]
    extent=f.half_extent(sample['boxes'][1],item['size'],1)
    assert command[1]-extent<-.046
    assert command[1]-extent>=-.0465
    assert fixture['transient_tilt_overhang_m']==.0005
    q=sample['boxes'][1]['orientation'];yaw=math.atan2(2*(q[0]*q[3]+q[1]*q[2]),1-2*(q[2]**2+q[3]**2))
    final=bodies(fixture)[1]
    final['position'][1]=command[1]
    final['orientation']=[math.cos(yaw/2),0.,0.,math.sin(yaw/2)]
    assert f.stable_box(final,1,True,fixture=fixture)
    final['position'][1]=-.0312
    assert not f.stable_box(final,1,True,fixture=fixture)


def test_readiness_uses_the_same_bounded_tilt_admission():
    fixture,sample=native_outer()
    command=f.cube_release_target(1,sample,.052,fixture=fixture)
    sample['boxes'][1]['position']=command[:]
    sample['tcps'][0]=command[:]
    assert f.cube_release_ready(1,sample,.052,fixture=fixture)
    sample['boxes'][1]['position'][1]-=.0006
    sample['tcps'][0][1]-=.0006
    assert not f.cube_release_ready(1,sample,.052,fixture=fixture)


def test_strict_profile_and_unfit_flat_target_still_block_opening():
    fixture,sample=native_outer()
    fixture['transient_tilt_overhang_m']=0.
    with pytest.raises(ValueError,match='envelope'):
        f.cube_release_target(1,sample,.052,fixture=fixture)
    fixture['transient_tilt_overhang_m']=.0005
    sample['boxes'][0]['position'][1]=-.001
    with pytest.raises(ValueError,match='envelope'):
        f.cube_release_target(1,sample,.052,fixture=fixture)
