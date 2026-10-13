import importlib.util
import math
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
repo = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(repo / 'tools/sim/isaac'))
for path in ('contracts/foundation', 'contracts/motion/src', 'contracts/skill/src',
             'middleware/core/services', 'middleware/core/gateway', 'middleware/perception'):
    sys.path.insert(0, str(repo / path))
from map_task import MapTask, QPolicy, SimulationOwner, load_track
from rosy.contracts.motion import BaseTwist, MotionHeader, MotionIntent, MotionKind, PriorityClass


def task():
    return MapTask([(0., 0.), (.1, 0.), (.2, 0.), (.2, .1)], half_size=(2., 2.))


def test_exact_map_lineage_and_connected_complete_route():
    track = load_track()
    assert track['source_sha256'] == 'cabf17a84175da8be1ef7562054ec598971bbb9378810acb8cee3f686fe1f92b'
    assert track['segments'] == ('ring_n', 'west:reverse', 'ring_s', 'east:reverse', 'ring_n', 'ring_w', 'ring_s', 'ring_e')
    assert track['points'][0] == track['points'][-1]
    assert all(w.height == .30 for w in track['scene'].walls)
    assert max(math.dist(a, b) for a, b in zip(track['points'], track['points'][1:])) < .025


def test_isaac_uses_the_gazebo_warning_mesh_definition():
    track = load_track()
    from build_world import caution_meshes
    assert track['caution_meshes'] == caution_meshes()
    assert len(track['caution_meshes']) == 8


def test_native_route_rejects_reentering_the_ring_at_an_exit(monkeypatch):
    import map_task
    for route in (('east', 'ring_e'), ('west', 'ring_w')):
        monkeypatch.setattr(map_task, 'SEGMENTS', route)
        with pytest.raises(ValueError, match='turn forbidden'):
            map_task.load_track()


def test_initial_goal_proximity_cannot_count_as_closed_loop_completion():
    t = MapTask([(0., 0.), (.1, 0.), (.1, .1), (0., 0.)], half_size=(2., 2.))
    s = t.observe(0., 0., 0., 0., 0., 0.)
    assert not s['terminated'] and not s['complete'] and s['progress_m'] == 0


def test_teleport_is_failure_not_progress():
    t = task()
    t.observe(0., 0., 0., 0., 0., 0.)
    s = t.observe(.2, .1, 0., 0., 0., .05)
    assert s['terminated'] and s['reason'] == 'pose_jump'
    assert not s['truncated'] and not s['complete']


def test_physical_stop_dwell_required_after_ordered_route():
    t = MapTask([(0., 0.), (.01, 0.), (.02, 0.)], half_size=(2., 2.))
    for i in range(21):
        s = t.observe(i * .001, 0., 0., .02, 0., i * .05)
    assert s['goal_reached'] and not s['complete']
    assert not t.observe(.02, 0., 0., 0., 0., 1.05)['complete']
    assert t.observe(.02, 0., 0., 0., 0., 1.4)['complete']


@pytest.mark.parametrize('pose', [(math.nan, 0.), (0., math.inf), (1.93, 0.)])
def test_invalid_observation_or_wall_overlap_terminates(pose):
    s = task().observe(*pose, 0., 0., 0., 0.)
    assert s['terminated'] and not s['complete']


def test_time_limit_is_only_truncation_and_terminal_state_is_latched():
    t = task()
    t.observe(0., 0., 0., 0., 0., 0.)
    s = t.observe(0., 0., 0., 0., 0., 500.)
    assert s['truncated'] and not s['terminated']
    assert t.observe(0., 0., 0., 0., 0., 501.) == s


def test_q_update_learns_from_reward_and_eval_does_not_mutate():
    p = QPolicy(seed=7)
    state = (0, 1)
    p.update(state, 2, 3., state, terminated=True)
    assert p.choose(state, explore=False) == 2
    before = p.export()
    p.choose((99, 99), explore=False)
    assert p.export() == before and p.updates == 1


def test_drive_tracker_alignment_boundary_is_preserved():
    t = MapTask([(0., 0.), (.1, 0.), (.2, 0.)], half_size=(2., 2.))
    _, speed, angular = t.pursuit(0., 0., .4)
    assert speed == 0. and angular < 0.


def test_closed_loop_tracker_gets_local_ordered_route_not_arrived_at_start():
    track = load_track()
    t = MapTask(track['points'], half_size=(2., 2.))
    x, y = t.points[0]
    yaw = math.atan2(t.points[1][1] - y, t.points[1][0] - x)
    _, speed, angular = t.pursuit(x, y, yaw)
    assert speed > 0. or angular != 0.


def test_route_progress_preserves_drive_alignment_hysteresis():
    t = MapTask([(i * .01, 0.) for i in range(100)], half_size=(2., 2.))
    assert t.pursuit(0., 0., .4)[1] == 0.
    t.index = 1
    assert t.pursuit(.01, 0., .25)[1] == 0.
    assert t.pursuit(.01, 0., .19)[1] > 0.


def intent(epoch=1, **overrides):
    fields = dict(intent_id='sim:1', device_id='isaac-pinky', source='learned_policy',
                  priority_class=PriorityClass.POLICY, issued_at=10., valid_for_s=.1,
                  envelope_ref='isaac-map-v1', state_sequence=epoch,
                  limits={'linear_mps': .06, 'angular_radps': .8})
    fields.update(overrides)
    return MotionIntent(MotionKind.BASE_TWIST, MotionHeader(**fields), BaseTwist(.03, .2))


def test_policy_admission_uses_core_and_stop_clears_old_episode():
    owner = SimulationOwner()
    owner.begin(1)
    out = owner.submit(intent(), observed_at=10., now=10.01)
    assert out.linear == .03 and out.angular == .2
    owner.stop()
    assert owner.command.select_output().linear == 0
    owner.begin(2)
    assert owner.submit(intent(), observed_at=10., now=10.01).linear == 0
    assert owner.halted


def test_final_output_refuses_intent_before_nav_slot_timeout():
    owner = SimulationOwner(); owner.begin(1)
    assert owner.submit(intent(), observed_at=10., now=10.01).linear > 0
    assert owner.select_output(now=10.11).linear == 0
    assert owner.halted and owner.command.select_output(now=10.12).linear == 0


@pytest.mark.parametrize('overrides', [dict(device_id='real-pinky'), dict(source='manual'),
    dict(envelope_ref='other'), dict(priority_class=PriorityClass.NAVIGATION),
    dict(valid_for_s=5.), dict(limits={'linear_mps': .2, 'angular_radps': .8})])
def test_policy_identity_or_envelope_refusal_latches_zero(overrides):
    owner = SimulationOwner(); owner.begin(1)
    assert owner.submit(intent(**overrides), observed_at=10., now=10.01).linear == 0
    assert owner.halted


@pytest.mark.parametrize('observed_at,now', [(10., 10.2), (9., 10.01), (11., 10.01), (10., math.nan),
                                          (-1., -1.), (True, True)])
def test_expired_or_nonfinite_observation_cannot_refresh_command(observed_at, now):
    owner = SimulationOwner(); owner.begin(1)
    owner.submit(intent(), observed_at=10., now=10.01)
    assert owner.submit(intent(), observed_at=observed_at, now=now).linear == 0
    assert owner.halted


@pytest.mark.parametrize('now', [-1., True, math.inf, '10'])
def test_final_output_invalid_clock_clears_previous_intent(now):
    owner = SimulationOwner(); owner.begin(1)
    owner.submit(intent(), observed_at=10., now=10.01)
    assert owner.select_output(now=now).linear == 0
    assert owner.halted


def test_two_simulation_owners_reject_cross_device_commands_and_reset_independently():
    a = SimulationOwner(device_id='isaac-pinky-a')
    b = SimulationOwner(device_id='isaac-pinky-b')
    a.begin(1); b.begin(1)
    ia = intent(device_id='isaac-pinky-a')
    ib = intent(device_id='isaac-pinky-b')
    assert a.submit(ia, observed_at=10., now=10.01).linear == .03
    assert b.submit(ib, observed_at=10., now=10.01).linear == .03
    assert b.submit(ia, observed_at=10., now=10.02).linear == 0
    assert b.halted and a.select_output(now=10.02).linear == .03
    b.begin(2)
    assert b.submit(intent(2, device_id='isaac-pinky-b'), observed_at=10., now=10.03).linear == .03
    a.stop()
    assert a.select_output(now=10.04).linear == 0
    assert b.select_output(now=10.04).linear == .03
    a.begin(2)
    assert a.submit(ia, observed_at=10., now=10.05).linear == 0
    assert a.halted and b.select_output(now=10.05).linear == .03


def test_one_simulation_owner_expiry_does_not_expire_another_owner():
    a = SimulationOwner(device_id='isaac-pinky-a')
    b = SimulationOwner(device_id='isaac-pinky-b')
    a.begin(1); b.begin(1)
    a.submit(intent(device_id='isaac-pinky-a'), observed_at=10., now=10.01)
    b.submit(intent(device_id='isaac-pinky-b', issued_at=10.05), observed_at=10.05, now=10.06)
    assert a.select_output(now=10.11).linear == 0
    assert a.halted and b.select_output(now=10.11).linear == .03
    assert not b.halted


@pytest.mark.parametrize('device_id', ['real-pinky', 'isaac-pinky-c', '', None, True])
def test_simulation_owner_refuses_non_simulation_identity(device_id):
    with pytest.raises(ValueError, match='simulation device'):
        SimulationOwner(device_id=device_id)
