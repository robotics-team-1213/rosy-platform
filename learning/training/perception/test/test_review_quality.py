"""Overexposure triage leaves review authority and originals intact."""
import hashlib
import json

import cv2
import numpy as np

from review_app import ReviewStore
from test_review_return import fixture_inputs
from review_quality import triage


def test_overexposure_triage_is_dry_run_then_excludes_only_pending(tmp_path):
    source, human, images = fixture_inputs(tmp_path)
    photo = np.zeros((24, 32, 3), dtype=np.uint8)
    photo[12:] = 255
    raw = cv2.imencode('.jpg', photo)[1].tobytes()
    (images / '0.jpg').write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    for path in (source, human):
        rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
        rows[0]['image_sha256'] = digest
        path.write_text('\n'.join(json.dumps(row) for row in rows), encoding='utf-8')
    store = ReviewStore(tmp_path / 'state', source, human, images)
    original = store.image(0).read_bytes()
    dry = triage(store, 0.15)
    assert dry[0]['clipped_fraction'] == 1.0
    assert dry[0]['candidate'] is True
    assert dry[0]['changed'] is False  # imported approval is never overridden
    assert store.get(0)['status'] == 'approved'
    pending = store.update(0, {'version': store.get(0)['version'], 'action': 'reopen'})
    assert pending['status'] == 'pending'
    assert triage(store, 0.15)[0]['changed'] is False
    applied = triage(store, 0.15, apply=True)
    assert applied[0]['changed'] is True
    assert applied[0]['status'] == 'excluded'
    assert store.get(0)['status'] == 'excluded'
    assert triage(store, 0.15, apply=True)[0]['changed'] is False
    assert store.image(0).read_bytes() == original
