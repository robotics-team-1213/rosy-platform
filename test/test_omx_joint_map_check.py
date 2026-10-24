"""D-864 §2 joint map comparison: pure function over a register probe and one /joint_states sample."""
import json
import math
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deploy/robot/omx'))
import joint_map_check as check_map  # noqa: E402

RAW = {11: 2048, 12: 1024, 13: 3000, 14: 2600, 15: 1500, 16: 2300}


def probe(raw=RAW, change=None):
    rows = []
    for motor_id, position in raw.items():
        row = dict(id=motor_id, model_number=1200, position_raw=position, homing_offset_raw=0, drive_mode=4)
        row.update((change or {}).get(motor_id, {}))
        rows.append(row)
    return {'motors': rows}


def states(offset=0.0):
    names = list(check_map.JOINTS.values()) + ['gripper_joint_2']
    positions = [RAW[m] * 2 * math.pi / 4096 - math.pi + offset for m in check_map.JOINTS] + [0.0]
    return {'name': names, 'position': positions}


def test_vendor_hypothesis_holds_on_matching_reads():
    verdict = check_map.check(probe(), states(), probe())
    assert verdict['holds'] and all(row['holds'] for row in verdict['joints'])
    assert verdict['joints'][0]['predicted_rad'] == pytest.approx(0.0)


@pytest.mark.parametrize('fault', ['offset', 'homing', 'reverse', 'moved'])
def test_any_mismatch_breaks_the_hypothesis(fault):
    before, sample, after = probe(), states(), probe()
    if fault == 'offset':
        sample = states(offset=0.05)
    elif fault == 'homing':
        before = probe(change={16: {'homing_offset_raw': 120}})
    elif fault == 'reverse':
        before = probe(change={12: {'drive_mode': 5}})
    else:
        after = probe({**RAW, 13: 3100})
    assert not check_map.check(before, sample, after)['holds']


def test_incomplete_inputs_are_invalid(tmp_path):
    with pytest.raises(ValueError):
        check_map.check({'motors': probe()['motors'][:5]}, states(), probe())
    with pytest.raises(ValueError):
        check_map.check(probe(), {'name': ['joint1'], 'position': [0.0]}, probe())
    paths = {}
    for name, doc in (('a', probe()), ('b', probe())):
        paths[name] = tmp_path / f'{name}.json'
        paths[name].write_text(json.dumps(doc))
    sample = tmp_path / 'js.yaml'
    sample.write_text('name: [joint1]\nposition: [0.0]\n')
    assert check_map.main([str(paths['a']), str(sample), str(paths['b']), '--out', str(tmp_path / 'v.json')]) == 2
