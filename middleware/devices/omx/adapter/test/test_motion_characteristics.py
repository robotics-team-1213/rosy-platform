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
