"""Actual-camera world derivation and bounded commands preserve source geometry."""
from pathlib import Path
import hashlib
import sys
import xml.etree.ElementTree as ET

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'deploy/robot/omx'))


def test_camera_world_preserves_every_original_model_and_plugin(tmp_path):
    from sim_pick_place_demonstrations import camera_world
    source = ROOT / 'integrations/simulation/gazebo/worlds/omx_cell_workcell_sim_aid.sdf'
    camera = ROOT / 'integrations/simulation/gazebo/worlds/omx_pilot_workcell.sdf'
    original = source.read_bytes()
    output = tmp_path / 'camera-world.sdf'
    receipt = camera_world(source, camera, output)
    before = ET.fromstring(original).find('world')
    after = ET.parse(output).getroot().find('world')
    assert after.attrib == before.attrib
    assert [ET.tostring(node) for node in list(after)[:len(before)]] == [ET.tostring(node) for node in before]
    assert len(after.findall("model[@name='workcell_camera']")) == 1
    sensor = after.find("model[@name='workcell_camera']/link/sensor")
    assert sensor.findtext('topic') == '/workcell_camera/image'
    assert sensor.findtext('camera/image/width') == '320'
    assert sensor.findtext('camera/image/height') == '240'
    assert receipt['derived_sha256'] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert source.read_bytes() == original
    with pytest.raises(FileExistsError):
        camera_world(source, camera, output)


def test_short_targets_keep_every_planned_waypoint_without_enlarging_steps():
    from sim_pick_place_demonstrations import short_targets
    points = [(0., 0.), (0.07, 0.), (0.07, 0.07), (0.03, 0.07)]
    targets = short_targets(points)
    assert targets[-1] == points[-1]
    assert points[1] in targets and points[2] in targets
    assert all(max(abs(b-a) for a,b in zip(left,right)) <= 0.035 + 1e-12
               for left,right in zip([points[0]] + targets[:-1], targets))


@pytest.mark.parametrize('points', [[], [(0.,), (float('nan'),)], [(0.,), (0., 1.)]])
def test_malformed_trajectory_is_rejected(points):
    from sim_pick_place_demonstrations import short_targets
    with pytest.raises(ValueError):
        short_targets(points)


def test_demonstrations_use_the_same_protected_native_entry_and_output_scope():
    from native_sim_prepare import run_script
    script = run_script('/candidate', experiment='pick-place-demonstrations')
    assert '/candidate/deploy/robot/omx/sim_pick_place_demonstrations.py' in script
    assert '$OMX_NATIVE_STATE/pick-place' in script
    assert '--approve-isolated-simulation --approve-startup-home' in script
