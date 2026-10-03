"""Profile semantics must reject resealed, hash-consistent invalid demonstrations."""
import hashlib
import json
from pathlib import Path
import sys
import struct
import zlib

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / p) for p in (
    'contracts/learning/src', 'src/products/omx/adapter',
    'src/products/omx/adapter/test', 'src/contracts/foundation', 'learning/curation/omx')]
from test_demonstration import complete_episode
from rosy.contracts.learning.omx import validate_demonstration, validate_profile
from rosy.contracts.learning import seal
from common_episode import convert
from rosy.contracts.learning.png import verify_rgb_png


def source(tmp_path):
    manifest = complete_episode(tmp_path / 'raw')
    return tmp_path / 'raw' / manifest['episode_id']


def rewrite_samples(root, change):
    rows = [json.loads(x) for x in (root / 'samples.jsonl').read_text().splitlines()]
    change(rows)
    payload = ('\n'.join(json.dumps(x) for x in rows) + '\n').encode()
    (root / 'samples.jsonl').write_bytes(payload)
    manifest = json.loads((root / 'manifest.json').read_text())
    manifest['samples_sha256'] = hashlib.sha256(payload).hexdigest()
    (root / 'manifest.json').write_text(json.dumps(manifest))


@pytest.mark.parametrize('change,reason', [
    (lambda rows: rows[0].update(state_time_ns=1_000_000_001), 'state_from_future'),
    (lambda rows: rows[1].update(capture_time_ns=1_300_000_000), 'frame_gap'),
    (lambda rows: rows[0].update(action=[2, -.1]), 'joint_limit'),
    (lambda rows: rows[0].update(duration_s=2.01), 'goal_duration'),
])
def test_rehashed_invalid_samples_are_rejected(tmp_path, change, reason):
    root = source(tmp_path)
    rewrite_samples(root, change)
    with pytest.raises(ValueError, match=reason):
        validate_demonstration(root)


def test_complete_source_and_common_binding(tmp_path):
    root = source(tmp_path)
    assert len(validate_demonstration(root)['samples']) == 2
    doc = convert(root, tmp_path / 'common')
    validate_profile(doc, root=tmp_path / 'common')
    doc['device'] = 'invented-device'
    with pytest.raises(ValueError, match='binding'):
        validate_profile(seal(doc), root=tmp_path / 'common')


def test_incomplete_or_corrupt_png_is_rejected(tmp_path):
    root = source(tmp_path)
    image = root / 'images/front/000000.png'
    image.write_bytes(image.read_bytes()[:-4])
    rewrite_samples(root, lambda rows: rows[0].update(
        image_sha256=hashlib.sha256(image.read_bytes()).hexdigest()))
    with pytest.raises(ValueError, match='PNG'):
        validate_demonstration(root)

    manifest = json.loads((root / 'manifest.json').read_text())
    manifest['status'] = 'incomplete'
    (root / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='incomplete'):
        validate_demonstration(root)


def png(raw, *, depth=8, interlace=0):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, depth, 2, 0, 0, interlace))
            + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


@pytest.mark.parametrize('depth,interlace', [(8, 0), (16, 0), (8, 1), (16, 1)])
def test_valid_truecolor_depth_and_adam7(depth, interlace):
    verify_rgb_png(png(b'\0' * (1 + 3 * depth // 8), depth=depth, interlace=interlace), 1, 1)


@pytest.mark.parametrize('raw', [b'\0', b'\5\0\0\0', b'\0' * 100000],
                         ids=['short', 'invalid-filter', 'oversize'])
def test_crc_correct_png_with_invalid_compressed_content_is_rejected(raw):
    with pytest.raises(ValueError, match='PNG'):
        verify_rgb_png(png(raw), 1, 1)


def test_png_crc_dimensions_and_trailing_stream_rejected():
    data = png(b'\0' * 4)
    with pytest.raises(ValueError, match='dimensions'):
        verify_rgb_png(data, 2, 1)
    with pytest.raises(ValueError, match='CRC'):
        verify_rgb_png(data[:50] + bytes([data[50] ^ 1]) + data[51:], 1, 1)
    with pytest.raises(ValueError, match='IEND'):
        verify_rgb_png(data + b'trailing', 1, 1)
