"""D-969 units: both arms' Isaac radians <-> the real arm's units, arm_a (fixture arm 0) then arm_b, six joints each.

Body joints use the real arm's own mapping (deploy/robot/omx/grasp_planner.rad_to_norm / norm_to_rad, normalized_-100_100).
The gripper is the pad gap over OPEN_GAP_M x 100: ASSUMED until the real gripper's 0-100 is measured against the jaw gap.
Stdlib plus the jaw mesh, so the Isaac task and the dataset exporter share it.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]/'deploy/robot/omx'))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]/'middleware/devices/omx/adapter'))
from grasp_planner import norm_to_rad, rad_to_norm  # noqa: E402
from palletizing_gripper import angle_for_gap, gap_m  # noqa: E402

OPEN_GAP_M = .040  # gripper 100 (the v2.1 release gap); 0 is closed pads


def to_units(radians):
    """12 radians (per arm: joint1..5, first finger) -> 12 values in the real arm's units."""
    out = []
    for arm in (0, 1):
        body, finger = radians[6*arm:6*arm+5], radians[6*arm+5]
        out += [rad_to_norm(v) for v in body] + [min(max(gap_m(finger)/OPEN_GAP_M*100., 0.), 100.)]
    return out


def to_radians(units):
    """The inverse of to_units: a policy action back to Isaac joint targets."""
    out = []
    for arm in (0, 1):
        body, gripper = units[6*arm:6*arm+5], units[6*arm+5]
        gap = min(max(gripper, 0.), 100.)/100.*OPEN_GAP_M
        out += [norm_to_rad(v) for v in body] + [angle_for_gap(min(max(gap, gap_m(-.2)), gap_m(1.2)))]  # the jaw's stroke
    return out
