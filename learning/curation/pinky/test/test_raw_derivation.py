"""Raw-message alignment rejects plausible sidecars even if their own hashes are valid."""
import copy
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'learning/curation/pinky'))
from verify_raw import compare_rows, compare_scan
from raw_messages import ir_sample, stamp_ns


def fixture():
    row = {'index': 0, 'stamp_ns': 1_000_000_000, 'log_ns': 1_010_000_000,
           'side': {'cmd_vel': {'linear': .02, 'angular': -.1}}, 'dt': {'cmd_vel': -.01}}
    tables = {'camera': [(1_010_000_000, {'stamp_ns': 1_000_000_000})],
              'cmd_vel': [(1_000_000_000, {'linear': .02, 'angular': -.1})]}
    return [row], tables


def test_ir_sample_matches_the_recording_contract():
    sys.path.insert(0, str(ROOT / "middleware/perception"))
    from control.recording import ir_range_sample
    samples = ([120, 800, 4095], (0, 0, 0), [1, 2], [1, 2, 4096], [-1, 0, 1],
               [1.0, 2, 3], [True, 2, 3], "no", None)
    for data in samples:
        assert ir_sample(data) == ir_range_sample(data)


def test_exact_camera_and_latest_causal_command():
    rows, tables = fixture()
    tables['cmd_vel'].append((1_010_000_001, {'linear': .5, 'angular': 1}))
    assert compare_rows(rows, tables, .5)['cmd_vel'] == 1


@pytest.mark.parametrize('change', [
    lambda row: row.update(log_ns=1_010_000_001),
    lambda row: row.update(stamp_ns=1_000_000_001),
    lambda row: row['side']['cmd_vel'].update(linear=.03),
    lambda row: row['dt'].update(cmd_vel=-.02),
    lambda row: row['side'].update(cmd_vel=None),
])
def test_tampered_row_rejected(change):
    rows, tables = fixture(); change(rows[0])
    with pytest.raises(ValueError, match='raw'):
        compare_rows(rows, tables, .5)


def test_stamped_observation_uses_earliest_eligible_message_and_source():
    rows, tables = fixture()
    payload = {'source': 'CAMERA_LINE', 'stamp': 1.0, 'confidence': .8}
    tables['line/observation'] = [(999_999_999, payload), (1_005_000_000, payload),
                                  (1_006_000_000, {**payload, 'confidence': .9})]
    rows[0]['side']['line/observation'] = {**payload, 'stamp_ns': 1_000_000_000}
    rows[0]['dt']['line/observation'] = -.005
    assert compare_rows(rows, tables, .5)['line/observation'] == 1
    wrong = copy.deepcopy(rows); wrong[0]['side']['line/observation']['confidence'] = .9
    with pytest.raises(ValueError, match='raw'):
        compare_rows(wrong, tables, .5)


def test_scan_quantized_payload_and_geometry_are_checked(tmp_path):
    np = pytest.importorskip('numpy')
    rows, _ = fixture()
    geometry = dict(angle_min=-1., angle_max=1., angle_increment=.1, range_min=.05, range_max=40.)
    scan = {'stamp_ns': 999_000_000, 'ranges': np.array([.1, np.inf], np.float16), **geometry}
    series = [(1_000_000_000, scan)]
    data = {'ranges': scan['ranges'][None], 'scan_stamp_ns': np.array([scan['stamp_ns']], np.int64),
            'dt': np.array([-.01], np.float32), **{key: np.float32(value) for key, value in geometry.items()}}
    path = tmp_path / 'scan.npz'; np.savez(path, **data)
    compare_scan(path, rows, series, .5, {'beams': 2, **geometry})
    data['ranges'] = np.array([[.2, np.inf]], np.float16); np.savez(path, **data)
    with pytest.raises(ValueError, match='raw scan payload'):
        compare_scan(path, rows, series, .5, {'beams': 2, **geometry})
    np.savez(path, **{**data, 'ranges': scan['ranges'][None]})
    with pytest.raises(ValueError, match='geometry changed'):
        compare_scan(path, rows, series + [(1_100_000_000, {**scan, 'angle_min': -2.})], .5,
                     {'beams': 2, **geometry})


def test_noncanonical_ros_header_nanoseconds_rejected():
    from types import SimpleNamespace
    msg = SimpleNamespace(header=SimpleNamespace(stamp=SimpleNamespace(sec=1, nanosec=1_000_000_000)))
    with pytest.raises(ValueError, match='nanosecond'):
        stamp_ns(msg)


def test_json_boolean_does_not_match_integer():
    rows, tables = fixture()
    tables['teleop/intent'] = [(1_000_000_000, {'accepted': True})]
    rows[0]['side']['teleop/intent'] = {'accepted': 1}
    rows[0]['dt']['teleop/intent'] = -.01
    with pytest.raises(ValueError, match='raw teleop/intent'):
        compare_rows(rows, tables, .5)
