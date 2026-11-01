"""The sim state writer judges gripper and held state from the simulation and writes what the observer reads."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
ASSETS = ROOT / 'learning/envs/isaac/assets/open_manipulator_description'
JOINTS = ['joint1', 'joint2', 'joint3', 'joint4', 'joint5', 'gripper_joint_1']
BASE = {'position_m': [.45, 0, 0], 'orientation_xyzw': [0, 0, 0, 1]}


@pytest.fixture
def module():
    spec = importlib.util.spec_from_file_location('transfer_state_writer', ROOT / 'tools/sim/transfer_state_writer.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


@pytest.fixture
def writer(module, tmp_path):
    ticks = iter(range(1_000, 10**9, 1_000))
    return module.Writer(module.ArmModel.load(ASSETS), BASE, 'omx_cell_sim_01', 'green_block', 'object-1',
                         tmp_path / 'state.json', clock=lambda: next(ticks))


def feed(module, writer, gripper, *, rate=0.0, offset=(0, 0, 0)):
    positions = dict(zip(JOINTS, [0.0, 0.3, 0.2, 0.4, 0.0, gripper]))
    jaw = writer.jaw_midpoint(positions)
    writer.objects([('other', (9, 9, 9), (0, 0, 0, 1)),
                    ('green_block', tuple(a + b for a, b in zip(jaw, offset)), (0, 0, 0, 1))])
    writer.joints(JOINTS, list(positions.values()), [0.0] * 5 + [rate])
    return json.loads(writer.path.read_text())['owners']['omx_cell_sim_01']


def test_nothing_is_written_before_both_topics_arrive(module, writer):
    writer.joints(JOINTS, [0.0] * 6, [0.0] * 6)
    assert not writer.path.exists()


def test_a_closed_gripper_around_the_object_holds_it(module, writer):
    arm = feed(module, writer, .3)
    assert (arm['gripper_state'], arm['held_state'], arm['held_object_ref']) == ('CLOSED', 'HELD', 'object-1')
    state = json.loads(writer.path.read_text())
    assert state['schema'] == module.STATE_SCHEMA and state['object']['observed_at_ns'] < arm['observed_at_ns']


def test_an_open_gripper_or_a_distant_object_holds_nothing(module, writer):
    arm = feed(module, writer, module.GRIPPER_OPEN_RAD)
    assert (arm['gripper_state'], arm['held_state'], arm['held_object_ref']) == ('OPEN', 'NONE', None)
    arm = feed(module, writer, .3, offset=(0, 0, .05))
    assert (arm['gripper_state'], arm['held_state']) == ('CLOSED', 'NONE')


def test_a_turning_finger_reads_moving_and_the_sequence_advances(module, writer):
    first = feed(module, writer, .5, rate=.2)
    second = feed(module, writer, .5)
    assert first['gripper_state'] == 'MOVING' and second['gripper_state'] == 'CLOSED'
    assert second['sequence'] == first['sequence'] + 1 and second['observed_at_ns'] > first['observed_at_ns']
