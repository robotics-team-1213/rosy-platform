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


def _checkpoint(tmp_path):
    (tmp_path / 'sub').mkdir()
    (tmp_path / 'sub/b.bin').write_bytes(b'two')
    (tmp_path / 'a.bin').write_bytes(b'one')
    return tmp_path


def test_checkpoint_digest_golden_vector(tmp_path):
    # Fixed bytes -> fixed hex: the OMX policy runner and the policy registry pin this algorithm (D-854 2).
    from rosy.contracts.learning.digest import checkpoint_sha256
    root = _checkpoint(tmp_path)
    golden_sha256 = 'f505742c0e0556a3c08d63640fbaaae6a6761d00857d5e0c73f932c00929c8ab'
    assert checkpoint_sha256(root) == golden_sha256
    assert checkpoint_sha256(root, ['sub/b.bin', 'a.bin']) == golden_sha256  # explicit list, sorted by path


def test_checkpoint_digest_skips_cache_and_checks_links(tmp_path):
    from rosy.contracts.learning.digest import checkpoint_sha256
    root = _checkpoint(tmp_path)
    first = checkpoint_sha256(root)
    (root / '.cache').mkdir()
    (root / '.cache/x').write_bytes(b'ignored')
    assert checkpoint_sha256(root) == first
    try:
        (root / 'link.bin').symlink_to(root / 'a.bin')
    except (OSError, NotImplementedError):
        return
    with pytest.raises(ValueError, match='symlinks'):
        checkpoint_sha256(root, allow_symlinks=False)
    assert checkpoint_sha256(root) != first


def test_checkpoint_digest_needs_local_files(tmp_path):
    from rosy.contracts.learning.digest import checkpoint_sha256
    with pytest.raises(ValueError):
        checkpoint_sha256(tmp_path / 'missing')
    with pytest.raises(ValueError):
        checkpoint_sha256(tmp_path)
