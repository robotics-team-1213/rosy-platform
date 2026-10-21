"""Review images refer to an exact local episode/frame, without substituting another row."""
import io
import base64
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
from PIL import Image
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def setup(tmp_path, monkeypatch):
    import experiment_preview as module
    inspection = dict(repo_id='local/recording', frame_count=4,
                      camera_keys=['observation.images.top'],
                      episodes=[{'episode_index': 0, 'frames': 2}, {'episode_index': 1, 'frames': 2}])
    current = dict(root=tmp_path, source_revision='a'*64, inspection=inspection)
    source_calls = []
    reviews = SimpleNamespace(source=lambda row: source_calls.append(row) or current)
    rows = [dict(episode_index=i//2, frame_index=i%2, index=i, timestamp=(i % 2) / 2,
                 **{'observation.images.top': np.full((3, 4, 5), i/4, np.float32)}) for i in range(4)]
    positions = []
    class Reader:
        meta = SimpleNamespace(info={'fps': 2.0}, episodes=[dict(episode_index=i, dataset_from_index=i*2,
                               dataset_to_index=i*2+2) for i in range(2)])
        def __len__(self):
            return len(rows)
        def __getitem__(self, index):
            positions.append(index)
            return rows[index]
    monkeypatch.setattr(module.native, 'load_dataset', lambda root, repo_id: Reader())
    return module, reviews, current, rows, positions, source_calls


def test_exact_episode_frame_encodes_real_rgb_and_rechecks_source(tmp_path, monkeypatch):
    module, reviews, current, rows, positions, calls = setup(tmp_path, monkeypatch)
    result = module.frame(reviews, {'id': 'registered'}, 'a'*64, 1, 1, 0)
    assert positions == [3] and len(calls) == 2
    image = Image.open(io.BytesIO(result))
    assert image.format == 'JPEG' and image.size == (5, 4)
    np.testing.assert_allclose(np.asarray(image), 191, atol=2)


@pytest.mark.parametrize('fault', ['revision', 'frame', 'camera', 'episode', 'wrong_row', 'pixel', 'source_change'])
def test_stale_or_invalid_preview_never_uses_a_neighbor_frame(tmp_path, monkeypatch, fault):
    module, reviews, current, rows, positions, calls = setup(tmp_path, monkeypatch)
    args = ['a'*64, 1, 1, 0]
    if fault == 'revision': args[0] = 'b'*64
    if fault == 'frame': args[2] = 2
    if fault == 'camera': args[3] = 1
    if fault == 'episode': args[1] = 5
    if fault == 'wrong_row': rows[3]['episode_index'] = 0
    if fault == 'pixel': rows[3]['observation.images.top'][0, 0, 0] = np.nan
    if fault == 'source_change':
        def changed(row):
            calls.append(row)
            return dict(current, source_revision='a'*64 if len(calls) == 1 else 'b'*64)
        reviews.source = changed
    with pytest.raises(ValueError):
        module.frame(reviews, {'id': 'registered'}, *args)
    assert positions in ([], [3])


def test_frame_set_reads_one_exact_row_and_binds_all_camera_images_and_time(tmp_path, monkeypatch):
    module, reviews, current, rows, positions, calls = setup(tmp_path, monkeypatch)
    current['inspection']['camera_keys'].append('observation.images.wrist')
    for row in rows:
        row['observation.images.wrist'] = 1 - row['observation.images.top']
    result = module.frame_set(reviews, {'id': 'registered'}, 'a'*64, 1, 1, [1, 0])
    assert positions == [3] and len(calls) == 2
    assert result == dict(prepared_id='registered', source_revision='a'*64, episode_index=1,
                          frame_index=1, index=3, timestamp_seconds=0.5, fps=2.0, frames=result['frames'])
    assert [(row['camera_index'], row['camera_key']) for row in result['frames']] == [
        (1, 'observation.images.wrist'), (0, 'observation.images.top')]
    for value, expected in zip(result['frames'], (64, 191)):
        image = Image.open(io.BytesIO(base64.b64decode(value['jpeg_base64'], validate=True)))
        assert image.format == 'JPEG' and image.size == (value['width'], value['height']) == (5, 4)
        np.testing.assert_allclose(np.asarray(image), expected, atol=2)


@pytest.mark.parametrize('cameras', [[], [0, 0], [True], [-1], [1], list(range(9)), '0'])
def test_frame_set_refuses_ambiguous_or_unbounded_camera_selection(tmp_path, monkeypatch, cameras):
    module, reviews, current, rows, positions, calls = setup(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        module.frame_set(reviews, {'id': 'registered'}, 'a'*64, 0, 0, cameras)
    assert positions == []


@pytest.mark.parametrize('fault', ['timestamp', 'time_shape', 'time_mismatch', 'fps', 'pixels', 'jpeg_size', 'source_change', 'missing_camera'])
def test_frame_set_never_publishes_a_partial_or_invalid_time_group(tmp_path, monkeypatch, fault):
    module, reviews, current, rows, positions, calls = setup(tmp_path, monkeypatch)
    if fault == 'timestamp': rows[3]['timestamp'] = float('nan')
    if fault == 'time_shape': rows[3]['timestamp'] = [0.5, 0.5]
    if fault == 'time_mismatch': rows[3]['timestamp'] = 3.5
    if fault == 'fps': module.native.load_dataset(tmp_path, 'local').meta.info['fps'] = 0
    if fault == 'pixels': monkeypatch.setattr(module, 'MAX_PIXELS', 19)
    if fault == 'jpeg_size': monkeypatch.setattr(module, 'MAX_JPEG_BYTES', 1)
    if fault == 'missing_camera': rows[3].pop('observation.images.top')
    if fault == 'source_change':
        def changed(row):
            calls.append(row)
            return dict(current, source_revision='a'*64 if len(calls) == 1 else 'b'*64)
        reviews.source = changed
    with pytest.raises(ValueError):
        module.frame_set(reviews, {'id': 'registered'}, 'a'*64, 1, 1, [0])
