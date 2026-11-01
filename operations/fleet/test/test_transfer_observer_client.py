"""The simulation transfer observer turns sim state into facts Fleet accepts, and its FK is the arm's."""
import importlib.util
from pathlib import Path
import sys
from urllib.error import HTTPError

import pytest

from test_physical_transfer_observer_api import TOKEN, approved, rig  # noqa: F401
from test_physical_transfer_store import installation  # noqa: F401
from test_physical_transfer_evidence import geometry, policy  # noqa: F401
from test_recovery_observer_client import ApiTransport

ROOT = Path(__file__).resolve().parents[3]
ASSETS = ROOT / 'learning/envs/isaac/assets/open_manipulator_description'
JOINTS = ['joint1', 'joint2', 'joint3', 'joint4', 'joint5', 'gripper_joint_1']
# Both arms face away from the shared zone around the origin.
BASES = ({'position_m': [.45, 0, 0], 'orientation_xyzw': [0, 0, 0, 1]},
         {'position_m': [-.45, 0, 0], 'orientation_xyzw': [0, 0, 1, 0]})


@pytest.fixture
def module():
    spec = importlib.util.spec_from_file_location('transfer_observer', ROOT / 'tools/sim/transfer_observer.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def states(context, position, *, rate=0.0, start=0):
    """Two sim states after not_before, min_separation apart; the sim's sequence keeps counting from start."""
    base = context['not_before_ns']
    for sequence, stamp in ((start + 1, base + 100_000_000), (start + 2, base + 300_000_000)):
        yield {'schema': 'rosy.sim-transfer-state/1',
               'object': {'position_m': position, 'orientation_xyzw': [0, 0, 0, 1], 'observed_at_ns': stamp},
               'owners': {owner['instance_id']: {'sequence': sequence, 'observed_at_ns': stamp, 'joint_names': JOINTS,
                   'positions_rad': [0.0] * len(JOINTS), 'velocities_rad_s': [rate] + [0.0] * (len(JOINTS) - 1),
                   'gripper_state': 'OPEN', 'held_state': 'NONE', 'held_object_ref': None}
                   for owner in context['owners']}}


def answer(module, rig, position, bases, **kwargs):
    client = module.Client('http://127.0.0.1:8765', TOKEN)
    client.opener = ApiTransport(rig)
    context = client.context()
    feed = states(context, position, **kwargs)
    rig.clock[0] = context['not_before_ns'] + 350_000_000
    arms = {owner['instance_id']: base for owner, base in zip(context['owners'], bases)}
    seen = set()
    return module.observe_once(client, lambda: next(feed), module.ArmModel.load(ASSETS), arms, seen), seen


def test_sim_states_close_a_job_through_pre_dispatch_and_post_action(module, rig):
    approved(rig)
    reply, seen = answer(module, rig, [0, 0, .2], BASES)
    assert reply['receipt'] is None and len(seen) == 1
    assert rig.app.state.arm_transfer_dispatcher.tick()['status'] == 'ACTION_SUCCEEDED'
    reply, _ = answer(module, rig, [.05, 0, .2], BASES, start=10)
    assert reply['job']['status'] == 'GOAL_CONFIRMED'
    assert reply['receipt']['physical_status'] == 'AT_TARGET_AND_CLEAR'


@pytest.mark.parametrize('bases, rate', [
    (({'position_m': [0, 0, 0], 'orientation_xyzw': [0, 0, 0, 1]}, BASES[1]), 0.0),  # arm A inside the zone
    (BASES, .5),  # arm still turning
])
def test_fleet_refuses_an_arm_in_the_zone_or_moving_and_the_observer_retries_later(module, rig, bases, rate):
    approved(rig)
    with pytest.raises(HTTPError):
        answer(module, rig, [0, 0, .2], bases, rate=rate)


def test_end_effector_frame_matches_the_adapter_tcp_fk(module):
    sys.path.insert(0, str(ROOT / 'middleware/devices/omx/adapter'))
    from omx_adapter.kinematics import OmxKinematics
    model, kinematics = module.ArmModel.load(ASSETS), OmxKinematics.load()
    base = {'position_m': [0, 0, 0], 'orientation_xyzw': [0, 0, 0, 1]}
    for joints in ([0, 0, 0, 0, 0], [.3, -.5, .4, .2, .1], [-1, .7, -.3, -.6, 0]):
        frames = model.frames({**dict(zip(JOINTS, joints)), 'gripper_joint_1': 0}, base)
        tcp = kinematics.fk(joints)
        assert frames['end_effector_link'][1] == pytest.approx((tcp.x, tcp.y, tcp.z), abs=1e-6)
