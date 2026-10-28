"""A local SDK compatibility wheel must remain distinguishable and auditable."""
import base64
import csv
import hashlib
import importlib.util
import io
from pathlib import Path
import zipfile

import pytest

SOURCE = Path(__file__).resolve().parents[1] / 'lab3' / 'kernel_wheel.py'


def module():
    spec = importlib.util.spec_from_file_location('lab3_kernel_wheel', SOURCE)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def record(files):
    out = io.StringIO(newline='')
    writer = csv.writer(out, lineterminator='\n')
    for name, data in files.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode()
        writer.writerow((name, 'sha256=' + digest, len(data)))
    return out.getvalue()


def original(tmp_path, *, dependency='urllib3==2.7.0', corrupt=False):
    name = 'isaacsim_kernel-6.2.0.0.dist-info/'
    files = {
        'isaacsim/kit/runtime.bin': b'original runtime payload\x00\xff',
        name + 'METADATA': ('Metadata-Version: 2.1\nName: isaacsim-kernel\nVersion: 6.2.0.0\nRequires-Dist: ' + dependency + '\nRequires-Dist: numpy==2.3.1\n\nVendor description\n').encode(),
        name + 'WHEEL': b'Wheel-Version: 1.0\nRoot-Is-Purelib: false\nTag: cp312-none-manylinux_2_35_x86_64\n',
    }
    files[name + 'RECORD'] = (record(files) + name + 'RECORD,,\n').encode()
    if corrupt:
        files['isaacsim/kit/runtime.bin'] = b'tampered'
    path = tmp_path / 'isaacsim_kernel-6.2.0.0-cp312-none-manylinux_2_35_x86_64.whl'
    with zipfile.ZipFile(path, 'w') as wheel:
        for key, data in files.items():
            wheel.writestr(key, data)
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_rebuild_labels_local_version_preserves_runtime_and_record(tmp_path):
    source, digest = original(tmp_path)
    before = source.read_bytes()
    output = module().rebuild(source, tmp_path / 'out', digest)
    assert source.read_bytes() == before
    assert output.name == 'isaacsim_kernel-6.2.0.0+rosy.1-cp312-none-manylinux_2_35_x86_64.whl'
    with zipfile.ZipFile(output) as wheel:
        prefix = 'isaacsim_kernel-6.2.0.0+rosy.1.dist-info/'
        metadata = wheel.read(prefix + 'METADATA').decode()
        assert 'Version: 6.2.0.0+rosy.1\n' in metadata
        assert 'Requires-Dist: urllib3==2.8.0\n' in metadata
        assert 'Requires-Dist: numpy==2.3.1\n' in metadata
        assert wheel.read('isaacsim/kit/runtime.bin') == b'original runtime payload\x00\xff'
        rows = list(csv.reader(io.StringIO(wheel.read(prefix + 'RECORD').decode())))
        assert {r[0] for r in rows} == set(wheel.namelist())
        for name, encoded, size in rows:
            if encoded:
                assert int(size) == len(wheel.read(name))
                assert encoded == 'sha256=' + base64.urlsafe_b64encode(hashlib.sha256(wheel.read(name)).digest()).rstrip(b'=').decode()


def test_refuses_untrusted_source_hash(tmp_path):
    source, _ = original(tmp_path)
    with pytest.raises(ValueError, match='source SHA'):
        module().rebuild(source, tmp_path / 'out', '0' * 64)


def test_refuses_corrupt_record(tmp_path):
    source, digest = original(tmp_path, corrupt=True)
    with pytest.raises(ValueError, match='RECORD'):
        module().rebuild(source, tmp_path / 'out', digest)


def test_refuses_changed_vendor_pin(tmp_path):
    source, digest = original(tmp_path, dependency='urllib3==9.0.0')
    with pytest.raises(ValueError, match='vendor pin'):
        module().rebuild(source, tmp_path / 'out', digest)


def test_refuses_overwriting_previous_wheel(tmp_path):
    source, digest = original(tmp_path)
    api = module()
    out = api.rebuild(source, tmp_path / 'out', digest)
    before = out.read_bytes()
    with pytest.raises(FileExistsError):
        api.rebuild(source, tmp_path / 'out', digest)
    assert out.read_bytes() == before
