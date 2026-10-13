"""Model-PC consumers cannot qualify stale or unavailable GUI approval snapshots."""
import json
from pathlib import Path
import time

import pytest

from test_learning_cycle import setup
import learning_cycle as cycle
from test_review_bridge_authority import WORKSPACE, bundle, current


def delivered(config, authority, *, age=0, available=True):
    path = Path(config['reviews_dir']) / '.authority/current.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    config['authority'] = {'path': str(path), 'workspace_id': WORKSPACE, 'max_age_s': 60}
    doc = {'schema': 'rosy.pinky-review-current-delivery/1', 'workspace_id': WORKSPACE,
           'available': available, 'checked_at_unix': time.time() - age,
           'authority': authority if available else None}
    path.write_text(json.dumps(doc))
    return path


def test_current_full_authority_supersedes_old_export_without_reviving_approval(setup):
    config, out, _ = setup
    root = Path(config['reviews_dir'])
    bundle(root, current())
    newer = bundle(root / 'next', current(2, 'excluded'))
    newer.rename(root / 'export-2')
    delivered(config, current(2, 'excluded'))
    state = cycle.run_once(config, out, trainer_fn=lambda *args: {})
    assert state['current_authority']['status'] == 'verified'
    assert len(state['authority_queue']) == 1
    assert state['authority_queue'][0]['mask_decision'] == 'excluded'
    assert state['authority_queue'][0]['training_dataset_qualified'] is False
    assert any(row['status'] == 'stale' for row in state['reviews'].values())


@pytest.mark.parametrize('age,available', [(61, True), (0, False), (-30, True)])
def test_expired_unavailable_or_future_snapshot_cannot_supply_current_queue(setup, age, available):
    config, out, _ = setup
    bundle(Path(config['reviews_dir']), current())
    delivered(config, current(), age=age, available=available)
    state = cycle.run_once(config, out, trainer_fn=lambda *args: {})
    assert state['current_authority']['status'] == 'unavailable'
    assert state['authority_queue'] == []


def test_replayed_lower_generation_cannot_replace_persisted_current_authority(setup):
    config, out, _ = setup
    root = Path(config['reviews_dir'])
    bundle(root, current(2, 'excluded'))
    delivered(config, current(2, 'excluded'))
    cycle.run_once(config, out, trainer_fn=lambda *args: {})
    delivered(config, current())
    state = cycle.run_once(config, out, trainer_fn=lambda *args: {})
    assert state['current_authority']['status'] == 'unavailable'
    assert state['current_authority']['revision']['generation'] == 2
    assert state['authority_queue'] == []


def test_authority_expiring_during_bundle_verification_cannot_remain_current(setup, monkeypatch):
    import review_authority
    config, out, _ = setup
    bundle(Path(config['reviews_dir']), current())
    path = delivered(config, current())
    original = review_authority.verify_bundle
    def expire(*args, **kwargs):
        result = original(*args, **kwargs)
        value = json.loads(path.read_bytes())
        value['checked_at_unix'] = time.time() - 61
        path.write_text(json.dumps(value))
        return result
    monkeypatch.setattr(review_authority, 'verify_bundle', expire)
    state = cycle.run_once(config, out, trainer_fn=lambda *args: {})
    assert state['current_authority']['status'] == 'unavailable'
    assert state['authority_queue'] == []
