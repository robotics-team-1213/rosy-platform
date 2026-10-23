"""Exercise the actual teacher verification boundary without ROS or commands."""
import ast
import importlib
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT/'deploy/robot/omx'))
import sim_pick_place_teacher as teacher


@pytest.fixture
def boundary(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT/'middleware/devices/omx/adapter'))
    from omx_adapter.gripper_contract import (
        GripperObservation, GripperReadbackError, verify_held_object, verify_released_object,
    )

    def prepare(position, *, received=9.9):
        class Arm:
            reads = 0

            @property
            def latest_joint_state(self):
                self.reads += 1
                assert self.reads == 1, 'failure evidence must retain the original snapshot'
                return SimpleNamespace(positions={'joint1': .1, 'gripper_joint_1': position}, sequence=7,
                                       received_at=received)

            def monotonic(self):
                return 10.

        arm = Arm()
        receipt = {'gripper_verification_failure': None}
        namespace = dict(vars(teacher), arm=arm, receipt=receipt,
            event={'phase_id': 'transfer'}, commands=[{'command_id': 'last-command'}],
            profile=SimpleNamespace(gripper_joint='gripper_joint_1', gripper_open=1.,
                gripper_close_for_width=lambda width: .38,
                gripper_contact_for_width=lambda width: .41, max_joint_state_age_s=.5),
            recipe=SimpleNamespace(box=SimpleNamespace(width=.02)),
            config=SimpleNamespace(workcell_id='cell', instance_id='arm'),
            GripperObservation=GripperObservation, verify_held_object=verify_held_object,
            verify_released_object=verify_released_object)
        run = next(n for n in ast.parse(Path(teacher.__file__).read_text()).body
                   if isinstance(n, ast.FunctionDef) and n.name == 'run')
        grip = next(n for n in run.body if isinstance(n, ast.FunctionDef) and n.name == 'grip')
        exec(compile(ast.Module(body=[grip], type_ignores=[]), teacher.__file__, 'exec'), namespace)
        return namespace['grip'], receipt, arm

    return prepare, GripperReadbackError, GripperObservation


@pytest.mark.parametrize('expect,position,received', [('held', .39, 9.9), ('held', .41, 9.), ('open', .41, 9.9)])
def test_rejected_sample_keeps_original_evidence_and_exception(boundary, expect, position, received):
    prepare, error_type, _ = boundary
    grip, receipt, arm = prepare(position, received=received)
    with pytest.raises(error_type) as failure:
        grip(expect)
    assert 'gripper' in str(failure.value)
    evidence = receipt['gripper_verification_failure']
    assert evidence is not None
    assert evidence['position_rad'] == position
    assert evidence['joint_positions_rad'] == {'joint1': .1, 'gripper_joint_1': position}
    assert evidence['expected'] == expect and evidence['phase_id'] == 'transfer'
    assert evidence['preceding_command_id'] == 'last-command'
    assert evidence['close_rad'] == .38 and evidence['contact_rad'] == .41
    assert evidence['contact_lower_rad'] == pytest.approx(.395)
    assert evidence['contact_upper_rad'] == pytest.approx(.425)
    assert evidence['checked_owner_s'] == 10. and evidence['max_age_s'] == .5
    assert evidence['observation']['sequence'] == 7
    assert evidence['observation']['received_at'] == received
    assert evidence['observation']['object_present'] is (False if position == .39 else True if expect == 'held' else None)
    assert arm.reads == 1


@pytest.mark.parametrize('expect,position', [('held', .41), ('open', 1.)])
def test_success_preserves_verified_receipt_without_failure(boundary, expect, position):
    prepare, _, _ = boundary
    grip, receipt, arm = prepare(position)
    evidence, actual = grip(expect)
    assert actual == position and evidence['receipt']['sequence'] == 7
    assert receipt['gripper_verification_failure'] is None and arm.reads == 1


def test_failure_preserves_the_same_exception_object(boundary):
    prepare, error_type, _ = boundary
    grip, receipt, arm = prepare(.39)
    original = error_type('original gripper rejection')
    def reject(*args, **kwargs):
        raise original
    grip.__globals__['verify_held_object'] = reject
    with pytest.raises(error_type) as caught:
        grip('held')
    assert caught.value is original
    assert receipt['gripper_verification_failure']['position_rad'] == .39
    assert arm.reads == 1


@pytest.mark.parametrize('invalid', ['malformed', 'nonfinite', 'serializer'])
def test_diagnostic_failure_is_bounded_and_cannot_replace_verifier_error(boundary, monkeypatch, invalid):
    prepare, error_type, observation_type = boundary
    diagnostic = importlib.import_module('sim_teacher_gripper_evidence')
    observation = observation_type('cell', 'arm', 'sensor', 7, 9.9, 'CLOSED', False, None, 1)
    position = .39
    if invalid == 'malformed':
        observation = object()
    elif invalid == 'nonfinite':
        position = float('nan')
    else:
        def fail(*args, **kwargs):
            raise RuntimeError('private serializer detail')
        monkeypatch.setattr(diagnostic.json, 'dumps', fail)
    value = diagnostic.gripper_failure_evidence(observation, position_rad=position,
        joint_positions_rad={'joint1': .1, 'gripper_joint_1': .39}, expected='held',
        close_rad=.38, contact_rad=.41, checked_owner_s=10., max_age_s=.5,
        phase_id='transfer', preceding_command_id='last-command')
    assert value == {'error': 'RuntimeError' if invalid == 'serializer' else 'TypeError' if invalid == 'malformed' else 'ValueError'}
    if invalid == 'serializer':
        grip, receipt, arm = prepare(.39)
        with pytest.raises(error_type, match='requested object is held'):
            grip('held')
        assert receipt['gripper_verification_failure'] == {'error': 'RuntimeError'}
        assert arm.reads == 1
