"""Model road proposals outside visible lane edges remain unknown."""
import hashlib
import json
import sys
from pathlib import Path

import cv2
import numpy as np

from clip_lane_draft import clip_drivable, main


CLASSES = (Path(__file__).resolve().parents[1] / 'classes' /
           'lane_lr6_drivable.yaml').read_bytes()


def test_clip_drivable_preserves_lanes_and_marks_only_outside_as_unknown():
    mask = np.array([[5, 5, 255, 1, 5, 5, 2, 5],
                     [5, 5, 255, 255, 5, 5, 255, 5]], dtype=np.uint8)
    result, removed = clip_drivable(mask, left=1, right=2, drivable=5)
    assert removed == 3
    assert result.tolist() == [[255, 255, 255, 1, 5, 5, 2, 255],
                               [5, 5, 255, 255, 5, 5, 255, 5]]
    assert mask[0, 0] == 5


def test_cli_writes_new_pending_catalog_and_receipt(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    source.mkdir()
    classes = source / 'classes.yaml'
    classes.write_bytes(CLASSES)
    mask = np.array([[5, 1, 5, 2, 5]], dtype=np.uint8)
    raw = cv2.imencode('.png', mask)[1].tobytes()
    (source / 'mask.png').write_bytes(raw)
    row = {'width': 5, 'height': 1, 'image_sha256': 'a' * 64,
           'mask': {'indexed_png': 'mask.png', 'sha256': hashlib.sha256(raw).hexdigest(),
                    'classes_sha256': hashlib.sha256(CLASSES).hexdigest()}}
    catalog = source / 'verified-inputs.jsonl'
    catalog.write_text(json.dumps(row) + '\n')
    out = tmp_path / 'clipped'
    monkeypatch.setattr(sys, 'argv', ['clip_lane_draft.py', '--catalog', str(catalog),
                                       '--classes', str(classes), '--out', str(out)])
    main()
    result = json.loads((out / 'verified-inputs.jsonl').read_text(encoding='utf-8'))
    clipped = cv2.imread(str(out / result['mask']['indexed_png']), cv2.IMREAD_UNCHANGED)
    assert clipped.tolist() == [[255, 1, 5, 2, 255]]
    assert json.loads((out / 'receipt.json').read_text())['removed_to_255'] == 2
    assert cv2.imread(str(source / 'mask.png'), cv2.IMREAD_UNCHANGED).tolist() == [[5, 1, 5, 2, 5]]
