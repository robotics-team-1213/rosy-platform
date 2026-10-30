"""New uploaded STEP dimensions must replace photo-derived workcell guesses."""
from pathlib import Path
import math
import sys
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import mapped_stack_fixture as f


def test_new_map_uses_the_opposing_stage1_pair_and_keeps_old_acceptance_fixture():
    scene=f.container_fixture(layers=3,case='nominal')
    assert scene['confluence_page']=='13205531'
    assert scene['cad_sha256']=='c455f11ab450cfcb9633a58387b0c0ec56f56727d23b4736ba5853334708f891'
    assert scene['workplate_size_m']==[.760,.603,.018]
    assert scene['workplate_center_m']==pytest.approx([-.225,-.0245,.063])
    assert scene['arm_bases_m'][0]==pytest.approx([.08,-.165,.072])
    assert scene['arm_bases_m'][1]==pytest.approx([.08,.165,.072])
    assert scene['board_size_m']==[1.220,2.440,.019]
    assert scene['board_lower_left_m']==pytest.approx([-.255,-2.013,0.])
    assert scene['cell_pose_scope']=='CAD_ASSEMBLY_DATUM_NOT_SURVEYED_MOTOR_AXIS'
    assert f.CUBE_FIXTURE['workplate_size_m']==[.40,.42,.02]
    assert f.CUBE_FIXTURE['arm_bases_m']==[[.08,-.13,.03],[.08,.13,.03]]


def test_actual_map_targets_and_homes_use_the_selected_cad_datums():
    scene=f.container_fixture(layers=3,case='nominal')
    assert scene['bin_origin_m']==pytest.approx([.035,-.0485,.074])
    assert f.plan(True,fixture=scene)[0]['target']==pytest.approx([.08,0.,.089])
    assert f.plan(True,fixture=scene)[-1]['target'][2]==pytest.approx(.149)
    assert f.home(0,True,fixture=scene)[2]==pytest.approx(.202)
    assert f.home(1,True,fixture=scene)[2]==pytest.approx(.202)
    assert 'upstream_belt_center_m' not in scene
    assert scene['road_markup']=='UNMODELED_IN_NEW_CAD_WORKCELL'


def test_belt_plane_has_the_source_slope_and_clear_pickup_before_plate():
    scene=f.container_fixture(layers=1,case='nominal')
    assert scene['belt_pitch_rad']==pytest.approx(math.atan2(34.467331,431.475521))
    assert scene['belt_size_m'][1]==.085
    assert scene['belt_velocity_m_s'][0]<0 and scene['belt_velocity_m_s'][2]<0
    assert math.dist(scene['belt_velocity_m_s'],[0.,0.,0.])==pytest.approx(.02)
    assert scene['pickup_center_m'][0]-.046>.155
    theta=scene['belt_pitch_rad']
    center=scene['belt_center_m']
    top=center[2]+math.cos(theta)*scene['belt_size_m'][2]/2
    x=center[0]-math.sin(theta)*scene['belt_size_m'][2]/2
    expected=(41.663959-19)/1000+(x-.025692804)*math.tan(theta)
    assert top==pytest.approx(expected,abs=1e-9)


def test_source_height_and_transport_use_the_sloped_active_fixture():
    scene=f.container_fixture(layers=1,case='nominal')
    point=scene['pickup_center_m']
    assert f.source_height_observed(point,scene)
    assert not f.source_height_observed(point,f.CUBE_FIXTURE)
    assert not f.source_height_observed([point[0],point[1],point[2]+.002],scene)
    start=[.252,.007,.056]
    end=[start[k]+scene['belt_velocity_m_s'][k]*2 for k in range(3)]
    assert f.belt_transport_observed(start,end,True,fixture=scene)
    end[1]+=.006
    assert not f.belt_transport_observed(start,end,True,fixture=scene)


def test_lower_belt_is_reachable_only_in_the_scoped_offline_sim_scene(tmp_path):
    from mapped_stack_task import Planner
    scene=f.container_fixture(layers=1,case='nominal')
    assert scene['planning_scene']=='cad-stage1-lower-belt-v1'
    planner=Planner(tmp_path,scene=scene['planning_scene'])
    homes=planner.request('homes',bases=scene['arm_bases_m'],base_yaws=scene['arm_base_yaws_rad'],
        points=[f.home(i,True,fixture=scene) for i in range(2)])['homes']
    frames=planner.request('move',base=scene['arm_bases_m'][0],base_yaw=math.pi/2,
        start=homes[0],target=scene['pickup_center_m'],yaw=0.,dt=f.DT)['frames']
    assert len(frames)>1
    assert planner.request('move',base=scene['arm_bases_m'][0],base_yaw=math.pi/2,
        start=frames[-1],target=[*scene['pickup_center_m'][:2],scene['carry_height_m']],yaw=0.,dt=f.DT)['frames']
    # Nine containers need ~200 plans; consumed exchange files must not exhaust the 256-file run budget.
    assert not list(tmp_path.iterdir())


def test_below_base_inside_the_plate_and_wrong_scene_bases_are_rejected(tmp_path):
    from mapped_stack_task import Planner
    scene=f.container_fixture(layers=1,case='nominal')
    planner=Planner(tmp_path,scene='cad-stage1-lower-belt-v1')
    homes=planner.request('homes',bases=scene['arm_bases_m'],base_yaws=scene['arm_base_yaws_rad'],
        points=[f.home(i,True,fixture=scene) for i in range(2)])['homes']
    with pytest.raises(ValueError,match='outside.*Stage1'):
        planner.request('move',base=scene['arm_bases_m'][0],base_yaw=math.pi/2,start=homes[0],
            target=[.1,0.,.06],yaw=0.,dt=f.DT)
    with pytest.raises(ValueError,match='CAD.*base'):
        planner.request('homes',bases=f.CUBE_FIXTURE['arm_bases_m'],base_yaws=scene['arm_base_yaws_rad'],
            points=[f.home(i,True) for i in range(2)])
    with pytest.raises(ValueError,match='CAD.*base'):
        planner.request('move',base=scene['arm_bases_m'][0],base_yaw=0.,start=homes[0],
            target=scene['pickup_center_m'],yaw=0.,dt=f.DT)


def test_default_scene_still_rejects_below_base_pickup(tmp_path):
    from mapped_stack_task import Planner
    scene=f.container_fixture(layers=1,case='nominal')
    planner=Planner(tmp_path)
    homes=planner.request('homes',bases=scene['arm_bases_m'],base_yaws=scene['arm_base_yaws_rad'],
        points=[f.home(i,True,fixture=scene) for i in range(2)])['homes']
    with pytest.raises(ValueError,match='OUTSIDE_WORKSPACE'):
        planner.request('move',base=scene['arm_bases_m'][0],base_yaw=math.pi/2,
            start=homes[0],target=scene['pickup_center_m'],yaw=0.,dt=f.DT)


@pytest.mark.parametrize('target',[[.2009,.007,.06],[.2701,.007,.06],
    [.207,-.0131,.06],[.207,.0271,.06],[.207,.007,.0399]])
def test_low_corridor_bounds_are_checked_on_every_target(tmp_path,target):
    from mapped_stack_task import Planner
    scene=f.container_fixture(layers=1,case='nominal')
    planner=Planner(tmp_path,scene='cad-stage1-lower-belt-v1')
    homes=planner.request('homes',bases=scene['arm_bases_m'],base_yaws=scene['arm_base_yaws_rad'],
        points=[f.home(i,True,fixture=scene) for i in range(2)])['homes']
    with pytest.raises(ValueError,match='outside.*Stage1'):
        planner.request('move',base=scene['arm_bases_m'][0],base_yaw=math.pi/2,
            start=homes[0],target=target,yaw=0.,dt=f.DT)


def test_safe_destination_cannot_hide_a_low_corridor_crossing(tmp_path):
    from mapped_stack_task import Planner
    scene=f.container_fixture(layers=1,case='nominal')
    planner=Planner(tmp_path,scene='cad-stage1-lower-belt-v1')
    homes=planner.request('homes',bases=scene['arm_bases_m'],base_yaws=scene['arm_base_yaws_rad'],
        points=[f.home(i,True,fixture=scene) for i in range(2)])['homes']
    frames=planner.request('move',base=scene['arm_bases_m'][0],base_yaw=math.pi/2,
        start=homes[0],target=[.1,0.,.08],yaw=0.,dt=f.DT)['frames']
    with pytest.raises(ValueError,match='outside.*Stage1'):
        planner.request('move',base=scene['arm_bases_m'][0],base_yaw=math.pi/2,
            start=frames[-1],target=scene['pickup_center_m'],yaw=0.,dt=f.DT)


def test_unknown_sim_planning_scene_is_not_an_override(tmp_path):
    from mapped_stack_task import Planner
    scene=f.container_fixture(layers=1,case='nominal')
    planner=Planner(tmp_path,scene='arbitrary-limits')
    with pytest.raises(ValueError,match='Unknown SIM planning scene'):
        planner.request('homes',bases=scene['arm_bases_m'],base_yaws=scene['arm_base_yaws_rad'],
            points=[f.home(i,True,fixture=scene) for i in range(2)])


def test_pending_dynamic_cargo_is_parked_on_the_new_base_plate():
    scene=f.container_fixture(layers=3,case='nominal')
    origin,size=scene['board_lower_left_m'],scene['board_size_m']
    for i in range(9):
        point=[scene['parking_origin_m'][0],scene['parking_origin_m'][1]+i*scene['parking_step_y_m'],scene['parking_origin_m'][2]]
        assert origin[0]+.045 < point[0] < origin[0]+size[0]-.045
        assert origin[1]+.015 < point[1] < origin[1]+size[1]-.015
        assert point[2]==pytest.approx(origin[2]+.016)


@pytest.mark.parametrize('noise',[0.,-1e-6,1e-6])
def test_measured_near_half_turn_chooses_a_continuous_symmetric_path(tmp_path,noise):
    from mapped_stack_task import Planner
    sys.path.insert(0,str(f.ROOT/'middleware/devices/omx/adapter'))
    from omx_adapter.kinematics import OmxKinematics
    scene=f.container_fixture(layers=1,case='nominal')
    # Captured from the failed native stage transfer, not rounded nominal IK.
    start=[.637981094180318,.13504347065745126,-.49193897149361354,1.9276918276310588,-.9328152983575576]
    start[-1]+=noise
    planner=Planner(tmp_path,scene=scene['planning_scene'])
    frames=planner.request('move',base=scene['arm_bases_m'][1],base_yaw=-math.pi/2,
        start=start,target=[-.04,0.,.212],yaw=-math.pi/2,dt=f.DT)['frames']
    assert max(abs(q[-1]) for q in frames)<=2.
    assert max(abs(q[j]-p[j]) for p,q in zip([start,*frames],frames) for j in range(5))<=.5*f.DT+1e-7
    pose=OmxKinematics.load().fk(frames[-1])
    base=scene['arm_bases_m'][1]
    world=[pose.y+base[0],-pose.x+base[1],pose.z+base[2]]
    assert world==pytest.approx([-.04,0.,.212],abs=1e-6)
    assert abs(math.sin(pose.yaw))<1e-6
