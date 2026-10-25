"""An explicit saved setup can bind a run without changing its dataset."""
import copy
import json
from types import SimpleNamespace
import uuid

import pytest

from test_experiment_center import center
from test_experiment_center_online import registered


@pytest.mark.parametrize('online', [False, True])
def test_selected_profile_pins_run_but_preserves_dataset_document(tmp_path, monkeypatch, online):
    import experiment_center as module
    c = center(tmp_path, monkeypatch)
    did = registered(c)
    original = (c.root / 'datasets' / did / 'dataset.json').read_bytes()
    profile = json.loads(original)['profile']
    saved_profile = copy.deepcopy(profile)
    saved_profile['arms'][0]['action_limits'] = [[float(a), float(b)]
                                                for a, b in profile['arms'][0]['action_limits']]
    saved = c.profiles.save({'profile': saved_profile, 'request_id': str(uuid.uuid4())})
    method = 'hilserl' if online else 'act'
    c.methods[method]['available'] = True
    receipt = {'pid': 12345, 'start': '77', 'boot': 'boot'}
    monkeypatch.setattr(module, 'process_stamp', lambda *args: receipt)
    calls = []
    child = SimpleNamespace(pid=12345, poll=lambda: None)
    monkeypatch.setattr(module.subprocess, 'Popen', lambda *a, **k: calls.append(a) or child)
    body = dict(dataset_id=did, method=method, steps=2, batch_size=2, device='cpu',
                seed=7, request_id=str(uuid.uuid4()), profile_id=saved['id'])
    start = c.start_online if online else c.start
    changed = copy.deepcopy(saved_profile)
    changed['cameras'][0]['placement'] += '-moved'
    mismatch = c.profiles.save({'profile': changed, 'request_id': str(uuid.uuid4())})
    with pytest.raises(ValueError, match='profile'):
        start(dict(body, profile_id=mismatch['id']))
    assert not calls and not c.snapshot()['runs']
    row = start(body)
    assert row['selected_profile'] == {'id': saved['id'], 'revision': saved['revision']}
    assert start(body)['id'] == row['id'] and len(calls) == 1
    worker = json.loads((c.root / 'runs' / row['id'] / 'request.json').read_text())
    assert 'profile_id' not in worker and 'selected_profile' not in worker
    assert (c.root / 'datasets' / did / 'dataset.json').read_bytes() == original
    with pytest.raises(ValueError, match='different inputs'):
        start({k: v for k, v in body.items() if k != 'profile_id'})
