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


ARM = 'omx-cell-s-follower'
BIND = dict(arm=ARM, calibration_digest='c' * 64)
CAL = {m: dict(id=11 + i, drive_mode=0, homing_offset=0, range_min=0, range_max=4095) for i, m in enumerate(
    ('shoulder_pan', 'shoulder_lift', 'elbow_flex', 'wrist_flex', 'wrist_roll', 'gripper'))}


def test_hypothesis_holds_on_clean_registers():
    verdict = check_map.check([probe(), probe()], **BIND)
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
    verdict = check_map.check([probe(), second], **BIND)
    assert not verdict['holds'] and any(reason in row['reasons'] for row in verdict['joints'])


def test_still_tolerance_boundary():
    assert check_map.check([probe(), probe({**RAW, 13: 3004})], **BIND)['holds']


@pytest.mark.parametrize('change,reason', [({16: {'homing_offset_raw': -50}}, 'homing_offset_nonzero'),
                                           ({12: {'drive_mode': 5}}, 'reverse_bit_set')])
def test_register_state_breaks_the_hypothesis(change, reason):
    verdict = check_map.check([probe(change=change), probe(change=change)], **BIND)
    assert not verdict['holds'] and any(reason in row['reasons'] for row in verdict['joints'])


def test_main_exit_codes(tmp_path):
    def write(name, doc):
        path = tmp_path / name
        path.write_text(json.dumps(doc))
        return str(path)
    good, again = write('a.json', probe()), write('a2.json', probe())  # two reads of a still arm may be identical
    bad, bad2 = (write(n, probe(change={12: {'drive_mode': 5}})) for n in ('b.json', 'b2.json'))
    cal = write('cal.json', CAL)
    arm = ['--arm', ARM, '--calibration', cal]
    assert check_map.main([good, again, *arm, '--out', str(tmp_path / 'ok.json')]) == 0
    verdict = json.loads((tmp_path / 'ok.json').read_text())
    assert verdict['holds'] is True and verdict['arm'] == ARM and verdict['schema'] == 'rosy.omx-joint-map-check/3'
    assert [p['file'] for p in verdict['probe_files']] == ['a.json', 'a2.json']
    assert verdict['calibration_sha256'] == check_map.calibration_sha256(CAL)
    assert check_map.main([bad, bad2, *arm, '--out', str(tmp_path / 'no.json')]) == 3
    assert check_map.main([good, again, *arm, '--out', str(tmp_path / 'ok.json')]) == 2  # never replaces a verdict
    assert check_map.main([good, good, *arm, '--out', str(tmp_path / 'same.json')]) == 2  # one file named twice
    assert check_map.main([good, *arm, '--out', str(tmp_path / 'one.json')]) == 2  # one snapshot is not enough
    for bad_cal in (str(tmp_path / 'missing.json'), write('half.json', {'gripper': CAL['gripper']})):
        assert check_map.main([good, again, '--arm', ARM, '--calibration', bad_cal,
                               '--out', str(tmp_path / 'badcal.json')]) == 2
    failed = [write(n, {'error': 'busy'}) for n in ('f1.json', 'f2.json')]  # register_probe output without motors
    assert check_map.main([*failed, *arm, '--out', str(tmp_path / 'f.json')]) == 2
    for probes, bind in (([probe()], BIND), ([probe(), probe()], dict(BIND, arm=' ')),
                         ([probe(), probe()], dict(BIND, calibration_digest=None))):
        with pytest.raises(ValueError):
            check_map.check(probes, **bind)
