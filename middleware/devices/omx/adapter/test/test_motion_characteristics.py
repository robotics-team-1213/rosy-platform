"""Device-specific characteristics are data, never command authority."""
from copy import deepcopy
import json

import pytest

from load_motion_fixtures import characteristics
from omx_adapter.motion_characteristics import (
    characteristics_digest, load_characteristics, save_characteristics, validate_characteristics,
)


def test_atomic_round_trip_and_digest_are_content_bound(tmp_path):
    p = characteristics()
    path = tmp_path / 'arm.json'
    digest = save_characteristics(path, p)
    assert load_characteristics(path) == p
    assert digest == characteristics_digest(dict(reversed(list(p.items()))))
    p['binding']['tool_revision'] = 'changed'
    assert characteristics_digest(p) != digest


def test_invalid_replacement_preserves_previous_document(tmp_path):
    path = tmp_path / 'arm.json'
    p = characteristics()
    save_characteristics(path, p)
    p['joints']['joint2']['velocity_rad_s'] = float('nan')
    with pytest.raises(ValueError):
        save_characteristics(path, p)
    assert load_characteristics(path) == characteristics()
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize('raw', ['{"schema":1,"schema":2}', '{"value":NaN}', '{"value":Infinity}'])
def test_json_boundary_rejects_duplicate_and_nonfinite_values(tmp_path, raw):
    path = tmp_path / 'arm.json'
    path.write_text(raw)
    with pytest.raises(ValueError):
        load_characteristics(path)


@pytest.mark.parametrize('path,value', [
    (('schema',), 'v99'), (('revision',), ''), (('status',), 'accepted'),
    (('binding', 'robot_model_sha256'), 'not-a-hash'), (('binding', 'device_id'), None),
    (('measured_at',), '2026-02-30'), (('evidence_ref',), ''),
    (('joints', 'joint2', 'motor_id'), True), (('joints', 'joint2', 'rad_per_raw'), 0.),
    (('joints', 'joint2', 'position_rad'), [1., -1.]),
    (('joints', 'joint2', 'velocity_rad_s'), 10 ** 400),
    (('monitor', 'max_gap_s'), 2.), (('monitor', 'oscillation_cycles'), 0),
    (('monitor', 'joints', 'joint2', 'clear_error_rad'), .1),
    (('envelopes', 0, 'payload_mass_kg'), [-.1, .1]),
    (('envelopes', 0, 'max_cycles'), False),
    (('envelopes', 0, 'position_rad', 'joint2'), [-2., 2.]),
])
def test_invalid_measurement_contract_is_rejected(path, value):
    p = characteristics()
    node = p
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    with pytest.raises(ValueError):
        validate_characteristics(p)


def test_unknown_fields_joint_map_and_motor_aliases_rejected():
    for mutate in [
        lambda p: p.update(enabled=True),
        lambda p: p['joints']['joint2'].update(current_a=1.),
        lambda p: p['joints']['joint3'].update(motor_id=12),
        lambda p: p['monitor']['joints'].pop('joint3'),
        lambda p: p['envelopes'][0]['position_rad'].pop('joint3'),
    ]:
        p = characteristics()
        mutate(p)
        with pytest.raises(ValueError):
            validate_characteristics(p)


def test_draft_preserves_missing_measurements_without_claiming_acceptance(tmp_path):
    p = characteristics()
    p.update(status='draft', measured_at=None, evidence_ref=None, joints={}, monitor=None, envelopes=[])
    p['binding'] = {k: None for k in p['binding']}
    path = tmp_path / 'draft.json'
    save_characteristics(path, p)
    assert load_characteristics(path) == p


def test_atomic_write_failure_preserves_previous_profile(tmp_path, monkeypatch):
    path = tmp_path / 'arm.json'
    p = characteristics()
    save_characteristics(path, p)
    changed = deepcopy(p)
    changed['revision'] = 'v2'

    def fail(*args):
        raise OSError('simulated replacement failure')
    monkeypatch.setattr('omx_adapter.motion_characteristics.os.replace', fail)
    with pytest.raises(OSError):
        save_characteristics(path, changed)
    assert json.loads(path.read_text()) == p
    assert list(tmp_path.iterdir()) == [path]


def test_characteristics_and_hardware_profile_helper_parity():
    from omx_adapter import policy_parent
    from omx_adapter.contracts import hardware_profile
    from rosy.contracts.learning import fleet_export
    from rosy.contracts.motion import characteristics as motion_characteristics

    valid_map = {'a': 1, 'b': 2}
    assert motion_characteristics._fields(valid_map, 'a b', 'lbl') == hardware_profile._fields(valid_map, 'a b', 'lbl')
    for bad_map in ([1, 2], {'a': 1}, {'a': 1, 'b': 2, 'c': 3}):
        with pytest.raises(ValueError) as exc_mc:
            motion_characteristics._fields(bad_map, 'a b', 'lbl')
        with pytest.raises(ValueError) as exc_hp:
            hardware_profile._fields(bad_map, 'a b', 'lbl')
        assert str(exc_mc.value) == str(exc_hp.value)

    for num, pos in ((0, False), (-1.5, False), (2.5, True), (1, True)):
        assert motion_characteristics._number(num, 'lbl', positive=pos) == hardware_profile._number(
            num, 'lbl', positive=pos,
        )
    for bad_num, pos in (
        (True, False), (False, False), ('1', False), (float('nan'), False),
        (float('inf'), False), (10 ** 400, False), (0, True), (-0.1, True),
    ):
        with pytest.raises(ValueError) as exc_mc:
            motion_characteristics._number(bad_num, 'lbl', positive=pos)
        with pytest.raises(ValueError) as exc_hp:
            hardware_profile._number(bad_num, 'lbl', positive=pos)
        assert str(exc_mc.value) == str(exc_hp.value)

    assert motion_characteristics._vector([1, 2.5, -3], 3, 'vec') == hardware_profile._vector([1, 2.5, -3], 3, 'vec')
    for bad_vec in ((1, 2, 3), [1, 2], [1, 2, 3, 4], [1, True, 3], [1, float('nan'), 3]):
        with pytest.raises(ValueError) as exc_mc:
            motion_characteristics._vector(bad_vec, 3, 'vec')
        with pytest.raises(ValueError) as exc_hp:
            hardware_profile._vector(bad_vec, 3, 'vec')
        assert str(exc_mc.value) == str(exc_hp.value)

    assert motion_characteristics._range([-1.0, 2.0], 'rng') == hardware_profile._range([-1.0, 2.0], 'rng')
    for bad_rng in ([1.0, 1.0], [2.0, -1.0], [1.0], [1.0, 2.0, 3.0]):
        with pytest.raises(ValueError) as exc_mc:
            motion_characteristics._range(bad_rng, 'rng')
        with pytest.raises(ValueError) as exc_hp:
            hardware_profile._range(bad_rng, 'rng')
        assert str(exc_mc.value) == str(exc_hp.value)

    sample = {'z': [1, 2, {'b': 'x', 'a': 'y'}], 'a': True}
    assert fleet_export.encoded(sample) == policy_parent.encoded(sample) == b'{"a":true,"z":[1,2,{"a":"y","b":"x"}]}'
    for non_finite in (float('nan'), float('inf'), float('-inf')):
        with pytest.raises(ValueError):
            fleet_export.encoded({'v': non_finite})
        with pytest.raises(ValueError):
            policy_parent.encoded({'v': non_finite})

