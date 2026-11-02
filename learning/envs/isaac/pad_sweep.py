"""Lowest point the finger pads can sweep, relative to the TCP (split from mapped_stack_fixture, D-766)."""
import math
from pathlib import Path
import xml.etree.ElementTree as ET

STOCK_URDF = Path(__file__).resolve().parent/'assets/open_manipulator_description/urdf/omx_f/omx_f.urdf'


def rotation_matrix(quaternion):
    w, x, y, z = quaternion
    return ((1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)),
              (2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)),
              (2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)))


def pad_sweep_bottom_relative_tcp(quaternion, gripper=None):
    if (len(quaternion) != 4 or not all(math.isfinite(v) for v in quaternion)
            or abs(sum(v*v for v in quaternion)-1) > .01):
        raise ValueError('A measured wrist quaternion is required')
    if gripper:  # opt-in jaw: its pad corners, from the vendored mesh
        import palletizing_gripper
        if gripper != palletizing_gripper.GRIPPER:
            raise ValueError('Unknown gripper')
        return palletizing_gripper.pad_sweep_bottom_relative_tcp(rotation_matrix(quaternion)[2])
    from run_omx_backend import PAD_HALF_LENGTH, PAD_RADIUS, PAD_CONTACT_OFFSET_M, jaw_contact_point
    root = ET.parse(STOCK_URDF).getroot()
    tcp = [float(v) for v in root.find("joint[@name='end_effector_joint']/origin").get('xyz').split()]
    row = rotation_matrix(quaternion)[2]
    x, y = jaw_contact_point()
    radius = math.hypot(x, y+PAD_RADIUS)
    sweep = math.hypot(row[0], row[1])*radius
    vertical = PAD_HALF_LENGTH*abs(row[2])+PAD_RADIUS+PAD_CONTACT_OFFSET_M
    bottoms = []
    for name in ('gripper_joint_1', 'gripper_joint_2'):
        joint = root.find(f"joint[@name='{name}']")
        if (joint.find('axis').get('xyz') != '0 0 1' or joint.find('origin').get('rpy') != '0 0 0'
                or joint.find('parent').get('link') != 'link5'):
            raise ValueError('Calibrated swept finger geometry changed')
        pivot = [float(v) for v in joint.find('origin').get('xyz').split()]
        bottoms.append(sum(row[k]*(pivot[k]-tcp[k]) for k in range(3))-sweep-vertical)
    return min(bottoms)
