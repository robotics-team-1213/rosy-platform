"""D-874/D-891: the shared promotion-request encoder writes Learning's exact bytes, and the shape is checked once."""

import hashlib
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
for folder in ('contracts/learning/src', 'learning/curation/perception', 'learning/registry/perception'):
    sys.path.insert(0, str(ROOT / folder))

from rosy.contracts.learning import promotion_request as contract  # noqa: E402
import review_evidence  # noqa: E402

SAMPLE = {'schema': contract.SCHEMA, 'state': 'requested', 'requester': '검수자', 'created_at': '2026-10-25T00:00:00+00:00',
          'model': {'revision': 'seg-r7', 'files': [{'name': 'model.pt', 'sha256': 'b' * 64}]},
          'dataset': {'name': 'pinky-floor', 'revision': 'c' * 64,
                      'external_sources': {'huggingface_frames': 3, 'percent': 7.5, 'groups': ['hf:floor'],
                                           'split': 'train_only', 'own_forced_train': 0}},
          'evaluation': {'set': 'floor-eval', 'content_sha': 'd' * 64, 'sources': list(contract.HUMAN),
                         'frames': 40, 'miou': 0.71, 'iou': [{'class': '바닥', 'value': 0.8}]},
          'training': None}


def test_contract_encoder_is_learnings_review_evidence_bytes():
    raw = contract.encoded(SAMPLE)
    assert raw == review_evidence.encoded(SAMPLE)
    assert raw.endswith(b'}\n') and '검수자'.encode() in raw  # non-ASCII kept, trailing newline
    assert hashlib.sha256(raw).hexdigest() == review_evidence.sha(raw)
    contract.validate(SAMPLE)


def test_learning_uses_the_contract_validator():
    import promotion_request as learning
    assert learning.validate is contract.validate and learning.encoded is contract.encoded


@pytest.mark.parametrize('change', [{'grant': True}, {'evaluation': dict(SAMPLE['evaluation'], miou=float('inf'))}])
def test_contract_refuses_authority_keys_and_non_finite_numbers(change):
    with pytest.raises(ValueError):
        contract.validate(dict(SAMPLE, **change))
