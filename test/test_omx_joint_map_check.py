"""D-864 §2 joint map check: register state from read-only probes only; no ROS driver, no device."""
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
        row = dict(id=motor_id, model_number=1200, position_raw=position, homing_offset_raw=0,
                   drive_mode=4, operating_mode=4)
        row.update((change or {}).get(motor_id, {}))
        rows.append(row)
    return {'motors': rows}


def test_hypothesis_holds_on_clean_registers():
    verdict = check_map.check([probe(), probe()])
    assert verdict['holds'] and all(row['holds'] for row in verdict['joints'])
    # Independent of the code's formula: 2048 ticks is 0 rad, 1024 is -pi/2 (vendor model unit, offset -pi).
    assert verdict['joints'][0]['ros_rad'] == pytest.approx(0.0)
    assert verdict['joints'][1]['ros_rad'] == pytest.approx(-math.pi / 2)


@pytest.mark.parametrize('second,reason', [
    (probe(change={16: {'homing_offset_raw': 120}}), 'register_changed_between_probes'),
    (probe(change={12: {'operating_mode': 3}}), 'register_changed_between_probes'),
    (probe({**RAW, 13: 3005}), 'moved_between_probes'),
])
def test_changes_between_probes_are_named(second, reason):
    verdict = check_map.check([probe(), second])
    assert not verdict['holds'] and any(reason in row['reasons'] for row in verdict['joints'])


def test_still_tolerance_boundary():
    assert check_map.check([probe(), probe({**RAW, 13: 3004})])['holds']


@pytest.mark.parametrize('change,reason', [({16: {'homing_offset_raw': -50}}, 'homing_offset_nonzero'),
                                           ({12: {'drive_mode': 5}}, 'reverse_bit_set')])
def test_register_state_breaks_the_hypothesis(change, reason):
    verdict = check_map.check([probe(change=change)])
    assert not verdict['holds'] and any(reason in row['reasons'] for row in verdict['joints'])


def test_main_exit_codes(tmp_path):
    def write(name, doc):
        path = tmp_path / name
        path.write_text(json.dumps(doc))
        return str(path)
    good, bad = write('a.json', probe()), write('b.json', probe(change={12: {'drive_mode': 5}}))
    assert check_map.main([good, good, '--out', str(tmp_path / 'ok.json')]) == 0
    assert json.loads((tmp_path / 'ok.json').read_text())['holds'] is True
    assert check_map.main([bad, '--out', str(tmp_path / 'no.json')]) == 3
    assert check_map.main([good, '--out', str(tmp_path / 'ok.json')]) == 2  # never replaces a verdict
    failed_probe = write('failed.json', {'error': 'busy'})  # register_probe output without motors
    assert check_map.main([failed_probe, '--out', str(tmp_path / 'f.json')]) == 2
    with pytest.raises(ValueError):
        check_map.check([])
