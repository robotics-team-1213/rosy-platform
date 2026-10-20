"""Learning digests keep lowercase SHA-256 and stream complete file contents."""

import hashlib
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'contracts/learning/src'))


@pytest.mark.parametrize('value, expected', [('a' * 64, True), ('0' * 64, True),
    ('A' * 64, False), ('g' * 64, False), ('a' * 63, False), ('a' * 65, False),
    ('a' * 64 + '\n', False), (None, False), (123, False), (b'a' * 64, False)])
def test_sha256_hex(value, expected):
    from rosy.contracts.learning.digest import is_sha256_hex
    assert is_sha256_hex(value) is expected


@pytest.mark.parametrize('size', [0, 1, 1024 * 1024, 1024 * 1024 + 17])
def test_file_digest_reads_every_block(tmp_path, size):
    from rosy.contracts.learning.digest import file_sha256
    path = tmp_path / 'bytes.bin'
    data = bytes(range(256)) * (size // 256) + bytes(range(size % 256))
    path.write_bytes(data)
    assert file_sha256(path) == hashlib.sha256(data).hexdigest()


def test_file_digest_propagates_read_failure(tmp_path):
    from rosy.contracts.learning.digest import file_sha256
    with pytest.raises(FileNotFoundError):
        file_sha256(tmp_path / 'missing')
