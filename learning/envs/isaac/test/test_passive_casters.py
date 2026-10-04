"""Unactuated continuous casters must not inherit importer position brakes."""
import sys
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
import drive_runtime
from test_wheel_damping import Drive


def urdf():
    return ET.fromstring('<robot name="rosy"><joint name="caster_rotate_joint" type="continuous"/>'
                         '<joint name="caster_wheel_joint" type="continuous"/></robot>')


def test_only_proven_unactuated_caster_identity_is_accepted():
    assert drive_runtime.passive_caster_joints(urdf()) == ('caster_rotate_joint', 'caster_wheel_joint')


@pytest.mark.parametrize('kind', ['fixed', 'revolute'])
def test_noncontinuous_joint_is_not_reclassified_as_passive(kind):
    root = urdf()
    root.find('joint').set('type', kind)
    with pytest.raises(ValueError):
        drive_runtime.passive_caster_joints(root)


def test_missing_joint_fails_before_sdk_configuration():
    root = urdf()
    root.remove(root.find('joint'))
    with pytest.raises(ValueError):
        drive_runtime.passive_caster_joints(root)


@pytest.mark.parametrize('actuation', [
    '<transmission><joint name="caster_wheel_joint"/></transmission>',
    '<ros2_control><joint name="caster_wheel_joint"><command_interface name="velocity"/></joint></ros2_control>',
])
def test_declared_caster_actuator_cannot_be_disabled(actuation):
    root = urdf()
    root.append(ET.fromstring(actuation))
    with pytest.raises(ValueError):
        drive_runtime.passive_caster_joints(root)


def test_coupled_caster_joint_is_not_silently_reconfigured():
    root = urdf()
    ET.SubElement(root.find('joint'), 'mimic', joint='l_wheel_joint')
    with pytest.raises(ValueError):
        drive_runtime.passive_caster_joints(root)


def test_passive_drive_has_no_position_or_velocity_servo_and_zero_target():
    drive = Drive(50)
    drive_runtime.configure_passive_drive(drive)
    assert drive.values == {'stiffness': 0, 'damping': 0, 'target': 0}


def test_passive_drive_readback_failure_holds_configuration():
    with pytest.raises(RuntimeError, match='readback'):
        drive_runtime.configure_passive_drive(Drive(readback_offset=1))
