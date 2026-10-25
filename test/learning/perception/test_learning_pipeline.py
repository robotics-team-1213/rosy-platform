"""Current review-to-learning lineage, using synthetic owner records only."""
import copy
import json

import pytest

from learning_pipeline import project, snapshot


AUTHORITY = dict(workspace_id='b' * 32, generation=3, decision_sha256='c' * 64)
DATASET = 'review-set@' + 'd' * 64


def ledger(status='ready'):
    return {'review_autobuild': {'status': 'request_published', 'authority': AUTHORITY,
                               'dataset': DATASET, 'cycle_keys': ['current']},
            'cycles': {'old': {'status': 'ready', 'result': {'revision': 'old-model'}},
                       'current': {'dataset': DATASET, 'status': status, 'attempts': 1,
                                   'result': {'revision': 'current-model'}}}}


def progress(doc=None, **changes):
    values = dict(counts={'approved': 1, 'pending': 0, 'excluded': 0},
                  pixel_counts={'approved': 1, 'pending': 0, 'excluded': 0},
                  preparation={'current_decisions_match': True, 'pixel_frames': 1},
                  control={'available': True, 'can_start': True, 'can_retry': True,
                           'pipeline': snapshot(ledger() if doc is None else doc)})
    values.update(changes)
    return project(AUTHORITY, **values)


def stage(value, name):
    return next(row for row in value['stages'] if row['id'] == name)


def test_current_owner_results_are_connected_without_registering_a_folder():
    value = progress()
    assert value['current'] is True
    assert value['dataset'] == DATASET
    assert [row['revision'] for row in value['cycles']] == ['current-model']
    assert stage(value, 'training')['state'] == 'done'
    assert stage(value, 'evaluation')['state'] == 'done'
    assert stage(value, 'application')['state'] != 'done'


@pytest.mark.parametrize('field,value', [('workspace_id', 'a' * 32), ('generation', 2),
                                        ('decision_sha256', 'e' * 64)])
def test_other_or_old_review_results_never_complete_current_work(field, value):
    doc = ledger()
    doc['review_autobuild']['authority'] = {**AUTHORITY, field: value}
    value = progress(doc)
    assert value['current'] is False
    assert value['dataset'] is None and value['cycles'] == []
    assert stage(value, 'training')['state'] != 'done'
    assert stage(value, 'evaluation')['state'] != 'done'


def test_changed_decisions_require_preparation_again():
    value = progress(preparation={'current_decisions_match': False, 'pixel_frames': 1})
    assert value['next']['action'] == 'prepare'
    assert stage(value, 'preparation')['state'] == 'attention'
    assert stage(value, 'evaluation')['state'] != 'done'


def test_object_approval_does_not_replace_pixel_review():
    value = progress(pixel_counts={'approved': 0, 'pending': 1, 'excluded': 0})
    assert value['next']['href'] == '/pixels?filter=pending'
    assert stage(value, 'review')['state'] != 'done'


def test_empty_workspace_starts_with_data_registration():
    value = progress(counts={'approved': 0, 'pending': 0, 'excluded': 0},
                     pixel_counts={'approved': 0, 'pending': 0, 'excluded': 0}, preparation=None)
    assert value['next']['href'] == '/catalog'


def test_unbound_owner_explains_connection_instead_of_promising_execution():
    value = progress(control=None)
    assert value['next']['href'] == '#pipeline-setup'
    assert stage(value, 'dataset')['state'] == 'connection'


@pytest.mark.parametrize('phase,training,evaluation', [('candidate', 'done', 'waiting'),
    ('running', 'running', 'waiting'), ('retry', 'attention', 'waiting'),
    ('gave_up', 'attention', 'waiting'), ('rejected', 'attention', 'attention'),
    ('pending', 'waiting', 'waiting')])
def test_training_and_evaluation_have_distinct_completion_conditions(phase, training, evaluation):
    value = progress(ledger(phase))
    assert stage(value, 'training')['state'] == training
    assert stage(value, 'evaluation')['state'] == evaluation


@pytest.mark.parametrize('change', ['missing', 'wrong_dataset', 'no_revision'])
def test_incomplete_current_cycles_cannot_be_reported_as_evaluated(change):
    doc = ledger()
    if change == 'missing':
        del doc['cycles']['current']
    elif change == 'wrong_dataset':
        doc['cycles']['current']['dataset'] = 'other@' + 'e' * 64
    else:
        doc['cycles']['current']['result'] = {}
    value = progress(doc)
    assert stage(value, 'evaluation')['state'] != 'done'


def test_hold_keeps_its_blocker_and_cannot_reuse_old_success():
    doc = ledger()
    doc['review_autobuild'].update(status='held', blockers=['no_approved_masks'])
    value = progress(doc)
    assert stage(value, 'evaluation')['state'] != 'done'
    assert value['blockers'] == ['no_approved_masks']


def test_completed_owner_iteration_keeps_selected_dataset_and_models():
    doc = ledger()
    # The producer's next already_completed iteration omits the top-level dataset.
    doc['review_autobuild']['status'] = 'already_completed'
    del doc['review_autobuild']['dataset']
    value = progress(doc)
    assert value['dataset'] == DATASET
    assert value['cycles'][0]['revision'] == 'current-model'
    assert stage(value, 'evaluation')['state'] == 'done'


def test_owner_hold_without_authority_keeps_diagnostics_without_completion():
    doc = ledger()
    doc['review_autobuild'] = {'status': 'held', 'blockers': ['no sealed export matches current authority']}
    value = progress(doc)
    assert value['blockers'] == ['no sealed export matches current authority']
    assert value['current'] is False and value['cycles'] == []
    assert stage(value, 'evaluation')['state'] != 'done'


def test_projection_is_read_only_and_does_not_expose_private_inputs():
    doc = ledger()
    doc['config'] = {'token': 'private-value'}
    doc['cycles']['current']['recipe'] = {'secret': 'private-value'}
    doc['cycles']['current']['result']['location'] = '/private/location'
    before = copy.deepcopy(doc)
    value = snapshot(doc)
    assert doc == before
    assert 'private-value' not in json.dumps(value)
    assert '/private/location' not in json.dumps(value)
    assert 'old-model' not in json.dumps(value)


def test_absent_cycle_selection_never_falls_back_to_historical_runs():
    doc = ledger()
    del doc['review_autobuild']['cycle_keys']
    assert snapshot(doc)['cycles'] == []
    assert stage(progress(doc), 'evaluation')['state'] != 'done'


def test_owner_snapshot_is_included_in_existing_control_response(tmp_path):
    from test_learning_control import control
    target, _, out, _, _ = control(tmp_path)
    (out / 'state.json').write_text(json.dumps(ledger()))
    value = target.status()
    assert value['pipeline']['dataset'] == DATASET
    assert value['pipeline']['cycles'][0]['revision'] == 'current-model'


@pytest.mark.parametrize('doc', [[], {'cycles': []}, {'review_autobuild': []},
    {'review_autobuild': {'cycle_keys': ['one'] * 1001}},
    {'review_autobuild': {'cycle_keys': ['one', 'one']}}])
def test_malformed_or_unbounded_ledger_is_refused(doc):
    with pytest.raises(ValueError):
        snapshot(doc)


def test_http_counts_and_identity_use_one_review_snapshot(tmp_path, monkeypatch):
    import threading
    import urllib.request
    import review_evidence
    import review_masks
    from review_app import make_server, Conflict
    from test_review_app import open_store
    from test_review_cycle import CLASSES
    store = open_store(tmp_path)
    review_masks.bind_classes(store, CLASSES)
    review_masks.update(store, 0, {'version': 0, 'action': 'fill', 'label': 0}, Conflict)
    review_masks.update(store, 0, {'version': 1, 'action': 'approve',
                                   'complete_frame_review': True, 'background_reviewed': True}, Conflict)
    observed = []
    original_snapshot, original_get = review_evidence.snapshot, review_masks.get

    def capture(target):
        value = original_snapshot(target)
        observed.append(value['authority'])
        return value

    changed = False

    def concurrent_reopen(target, index):
        nonlocal changed
        value = original_get(target, index)
        if index == 0 and not changed:
            changed = True
            review_masks.update(target, index, {'version': 2, 'action': 'reopen'}, Conflict)
        return value

    monkeypatch.setattr(review_evidence, 'snapshot', capture)
    monkeypatch.setattr(review_masks, 'get', concurrent_reopen)
    server = make_server(store, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        value = json.load(urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}/api/learning'))
        expected = sum(row['mask_decision'] == 'approved' and not row['frame_excluded']
                       for row in observed[-1]['frames'])
        assert value['pixel_counts']['approved'] == expected
        assert value['pipeline']['identity']['decision_sha256'] == observed[-1]['decision_sha256']
    finally:
        server.shutdown(); server.server_close(); thread.join()


def test_dataset_record_shows_the_hf_share():
    doc = ledger()
    doc['review_autobuild']['build'] = {'external_sources': {'huggingface_frames': 3, 'percent': 60.0,
                                                             'groups': ['hf:dataset/org/data@' + 'a' * 40]}}
    assert snapshot(doc)['external'] == {'huggingface_frames': 3, 'percent': 60.0}
    assert progress(doc)['external'] == {'huggingface_frames': 3, 'percent': 60.0}
    assert 'external' not in progress()
