"""Catalog readiness and immutable import conditions; no SDK required."""
import importlib
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def catalog_module():
    assert (ROOT / 'run_catalog.py').is_file(), 'Isaac run catalog is missing'
    sys.path.insert(0, str(ROOT))
    return importlib.import_module('run_catalog')


def test_import_conditions_are_bounded_and_seed_effect_is_explicit():
    mod = catalog_module()
    config = mod.normalize('omx-f-import', {'seed': 7})
    assert config == {'model': 'omx_f', 'headless': True, 'frames': 120, 'seed': 7}
    entry = next(row for row in mod.catalog() if row['id'] == 'omx-f-import')
    assert entry['seed_effect'] == 'NOT_USED_BY_MODEL_IMPORT'
    assert entry['stage'] == 'model_import'
    assert entry['timeout_seconds'] == 180


@pytest.mark.parametrize('scenario,config', [
    ('pinky-conveyor-roundtrip', {'seed': 0}),
    ('port-e0-pick-place', {'seed': 0}),
    ('port-mixed-stacking', {'seed': 0}),
    ('port-retrieval', {'seed': 0}),
    ('port-cooperative-recovery', {'seed': 0}),
    ('unknown', {'seed': 0}),
    ('omx-f-import', {'seed': True}),
    ('omx-f-import', {'seed': -1}),
    ('omx-f-import', {'seed': 2147483648}),
    ('omx-f-import', {'seed': 0, 'frames': 0}),
    ('omx-f-import', {'seed': 0, 'argv': ['anything']}),
    ('omx-f-import', {}),
])
def test_catalog_refuses_physics_and_extra_settings(scenario, config):
    with pytest.raises(ValueError):
        catalog_module().normalize(scenario, config)


def test_readiness_catalog_cannot_be_mutated_by_a_caller():
    mod = catalog_module()
    rows = mod.catalog()
    rows[0]['id'] = 'changed'
    assert mod.catalog()[0]['id'] == 'omx-f-import'
