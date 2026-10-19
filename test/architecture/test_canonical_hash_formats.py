"""Persisted JSON digest formats must survive helper consolidation."""

import hashlib
import importlib.util
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
ASCII_COMPACT = 'bf5f3a724c0edc626e1d8627c4c003dda63ea2f5cf29d5460456b37c34853a39'
UTF8_COMPACT = 'f75345d82281e57408262b04e08f63de354ea70eb40fb30b4d0d5324ce570e2e'
ASCII_SPACED = 'a8ef4c89d0d703ed8662aa426e7aa5b9e8ab9a70f8b01459bd6e31ca896f525e'
CASES = [
    ('contracts/learning/src/rosy/contracts/learning/incident_handoff.py', 'digest', ASCII_COMPACT),
    ('contracts/learning/src/rosy/contracts/learning/prediction.py', 'canonical_sha256', ASCII_COMPACT),
    ('contracts/learning/src/rosy/contracts/learning/artifacts.py', '_json', UTF8_COMPACT),
    ('learning/registry/policy/registry.py', 'canonical', UTF8_COMPACT),
    ('learning/curation/pinky/fleet_rules.py', 'digest', ASCII_COMPACT),
    ('learning/evaluation/decision/operational_comparison.py', 'digest', ASCII_COMPACT),
    ('learning/evaluation/perception/judgment_acceptance.py', 'digest', UTF8_COMPACT),
    ('learning/training/perception/review_admission.py', '_hash', ASCII_SPACED),
    ('learning/training/perception/review_migration.py', '_canonical', ASCII_SPACED),
]


@pytest.mark.parametrize('path, name, expected', CASES)
def test_persisted_json_hash_format(monkeypatch, path, name, expected):
    for folder in ('contracts/learning/src', 'learning/registry/policy', 'learning/registry/perception',
                   'learning/training/perception'):
        monkeypatch.syspath_prepend(str(ROOT / folder))
    spec = importlib.util.spec_from_file_location('_golden_' + Path(path).stem, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    if path.startswith('contracts/learning/'):
        module = __import__('rosy.contracts.learning.' + Path(path).stem, fromlist=[''])
    else:
        spec.loader.exec_module(module)
    result = getattr(module, name)({'이름': '로봇', 'b': [1, 2]})
    if isinstance(result, bytes):
        result = hashlib.sha256(result).hexdigest()
    elif name == 'canonical':
        result = hashlib.sha256(result.encode('utf-8')).hexdigest()
    assert result == expected
