"""ROOT frozen file and installation boundaries, with no runtime or provider activation."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def owner():
    path = ROOT / 'tools/incident_operating.py'
    assert path.exists(), 'root operating evidence owner missing'
    spec = importlib.util.spec_from_file_location('incident_operating', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def frozen(tmp_path, raw):
    path = tmp_path / 'original.json'; path.write_bytes(raw)
    return path, hashlib.sha256(raw).hexdigest()


def test_loader_pins_original_bytes_instead_of_document_hash(tmp_path):
    path, expected = frozen(tmp_path, b'{"schema":"source-fixture","value":1}')
    assert owner().load_frozen_json(path, expected_sha256=expected)['value'] == 1
    path.write_bytes(b'{"schema":"source-fixture","value":2}')
    with pytest.raises(ValueError): owner().load_frozen_json(path, expected_sha256=expected)


@pytest.mark.parametrize('raw', [b'{"value":1,"value":2}', b'{"value":NaN}', b'[]', b'x' * (1048576 + 1)],
                         ids=['duplicate', 'nonfinite', 'nonobject', 'oversized'])
def test_loader_rejects_duplicate_nonfinite_nonobject_or_large_original(tmp_path, raw):
    path, expected = frozen(tmp_path, raw)
    with pytest.raises(ValueError): owner().load_frozen_json(path, expected_sha256=expected)


def test_importer_refuses_compiled_hold_before_existing_db_apply():
    module = owner()
    class ExistingOwner:
        def apply(self, *args):
            raise AssertionError('HOLD must not reach the existing DB importer')
    with pytest.raises(ValueError):
        module.import_operation(ExistingOwner(), 'grant', {}, evidence=lambda _: {'report': {'state': 'HOLD'}})
