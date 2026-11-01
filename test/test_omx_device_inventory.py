"""D-943 §2: the bench inventory names only boards an observer already owns and drafts a valid profile."""
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('device_inventory', ROOT / 'deploy/robot/omx/device_inventory.py')
inventory_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(inventory_module)
sys.path.insert(0, str(ROOT / 'learning/training/omx'))
from experiment_profile import validate_profile  # noqa: E402


def test_assigned_followers_become_arms_and_other_boards_stay_unassigned(tmp_path):
    config, by_id, calibration = tmp_path / 'config', tmp_path / 'by-id', tmp_path / 'calibration'
    config.mkdir(); by_id.mkdir()
    names = [f'usb-ROBOTIS_OpenRB-150_{n}-if00' for n in ('AAA', 'BBB', 'CCC', 'DDD')]
    for name in names:
        (by_id / name).write_text('')
    for arm, name in (('arm_a', names[0]), ('arm_b', names[1])):
        (config / f'omx-observer-{arm}.env').write_text(f'ROS_DOMAIN_ID=13\nROSY_OBSERVER_DEVICE=/dev/serial/by-id/{name}\n')
    (config / 'omx-cameras.json').write_text(json.dumps({'cameras': [
        {'role': 'arm_a_wrist', 'device': '/dev/v4l/by-path/a', 'topic': '/a'},
        {'role': 'side', 'device': '/dev/v4l/by-id/side', 'topic': '/side'}]}))
    (calibration / 'robots/omx_follower').mkdir(parents=True)
    (calibration / 'robots/omx_follower/arm_a_follower.json').write_text('{}')
    result = inventory_module.inventory(config, by_id, calibration)
    assert [b['arm_id'] for b in result['boards']] == ['arm_a', 'arm_b', None, None]
    assert result['unassigned_boards'] == names[2:]  # leaders are not guessed
    assert result['calibrations']['robots'] == ['arm_a_follower']
    draft = result['draft']
    assert [arm['id'] for arm in draft['arms']] == ['arm_a', 'arm_b']
    assert {c['id']: c['arm_id'] for c in draft['cameras']} == {'arm_a_wrist': 'arm_a', 'side': None}
    validate_profile(dict(draft, name='bench draft', task='pick', mode='independent'))
