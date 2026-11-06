"""SAM provenance keeps its original class hash across compatible managed revisions."""
import base64
import copy
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
import yaml

import review_classes
import review_evidence
import review_masks
import review_sam_assistance
from review_ai_jobs import Jobs
from review_store import Conflict
from test_review_ai_jobs import workspace, finished
from test_review_classes import request as class_request


def test_sam_history_survives_managed_revision_reapproval_and_export(tmp_path):
    store = workspace(tmp_path)
    proposal = np.full((24, 32), 255, np.uint8)
    proposal[:, 1] = 0
    jobs = Jobs(store, backend=lambda *_: {'mask': base64.b64encode(review_masks.encode(proposal)).decode()})
    jobs.config['sam_checkpoint_sha256'] = 'e' * 64
    try:
        jobs.create(0, 'sam_points', 1, 'human-a', prompt={'label': 0, 'points': [[1, 2]]})
        job = finished(jobs)
        assert job['state'] == 'succeeded'
        mask = review_masks.update(store, 0, {'action': 'sample', 'version': 1, 'label': 0,
            'seeds': [[1, 2]], 'selection_sha256': job['result']['selection_sha256'], 'preserve_existing': True}, Conflict)
        mask = review_masks.update(store, 0, {'action': 'fill_unknown', 'version': mask['version']}, Conflict)
        mask = review_masks.update(store, 0, {'action': 'approve', 'version': mask['version'],
            'complete_frame_review': True, 'background_reviewed': True}, Conflict)
        original_sha = review_masks.served_classes(store)['sha256']
        original_mask_sha = mask['sha256']
        for color in ([91, 92, 93], [94, 95, 96]):
            rows = copy.deepcopy(review_masks.served_classes(store)['classes'])
            rows[0]['color'] = color
            review_classes.revise(store, class_request(store, 'pixel', rows, 1 if mask['status']=='approved' else 0), 'admin', Conflict)
            mask = review_masks.get(store, 0)
        assert mask['sha256'] == original_mask_sha and mask['status'] == 'pending'
        mask = review_masks.update(store, 0, {'action': 'approve', 'version': mask['version'],
            'complete_frame_review': True, 'background_reviewed': True}, Conflict)
        authority = review_evidence.decisions(store)
        row = authority['frames'][0]
        use = row['sam_assistance'][0]
        assert use['classes_sha256'] == original_sha != authority['pixel_classes_sha256']
        assert len(use['class_history']) == 3
        assert hashlib.sha256(use['class_history'][0].encode()).hexdigest() == original_sha
        assert hashlib.sha256(use['class_history'][-1].encode()).hexdigest() == authority['pixel_classes_sha256']
        assert review_evidence.validate_authority(authority)
        receipt = store.prepare()
        exported = json.loads((Path(receipt['path']) / 'review-contract.json').read_text(encoding='utf-8'))
        assert exported['authority']['frames'][0]['sam_assistance'] == [use]
        assert review_evidence.validate_authority(exported['authority'])
        bad = copy.deepcopy(use)
        bad['class_history'][0] += '\n'
        with pytest.raises(ValueError):
            review_sam_assistance.validate([bad], row, authority['pixel_classes_sha256'])
        for field, value in [('name', 'renamed'), ('semantic', 'road_surface/1'), ('hotkey', '9')]:
            bad = copy.deepcopy(use)
            document = yaml.safe_load(bad['class_history'][-1])
            document['classes'][0][field] = value
            bad['class_history'][-1] = yaml.safe_dump(document, sort_keys=True)
            changed_sha = hashlib.sha256(bad['class_history'][-1].encode()).hexdigest()
            with pytest.raises(ValueError):
                review_sam_assistance.validate([bad], row, changed_sha)
        middle_sha = hashlib.sha256(use['class_history'][1].encode()).hexdigest()
        middle = store.state / 'pixel' / (middle_sha + '.yaml')
        middle.write_bytes(middle.read_bytes() + b'\n')
        with pytest.raises(ValueError, match='hash'):
            review_evidence.decisions(store)
    finally:
        jobs.close()
