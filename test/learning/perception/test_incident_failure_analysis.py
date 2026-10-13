import copy
import json
import sys

import pytest


def test_failure_analysis_keeps_opt_in_handoff_evidence_unreviewed():
    from test_incident_feedback import handoff_feedback
    exported = handoff_feedback()
    value = analysis(review('judgment'))
    value['model_feedback_digest'] = exported['digest']
    base = incident_feedback.bind({'reports': [report()]}, markers('stuck-a'))
    result = incident_feedback.attach_failure_analysis(base, exported, value)
    row = result['matches'][0]
    assert row['model_feedback']['handoff'] == exported['case']['handoff']
    assert row['failure_analysis']['label_state'] == row['model_feedback']['label_state'] == 'UNREVIEWED'

from test_incident_feedback import incident_feedback, report, markers, model_feedback


def analysis(*reviews):
    return dict(schema='rosy.incident.failure_analysis/1', subject_id='rosy_40', case_id='stuck-a',
                model_feedback_digest=model_feedback()['digest'], reviews=list(reviews))


def review(category='judgment', source='model'):
    return dict(category=category, source=source, author_id='private-author', at='2026-10-12T01:00:00Z')


def attach(value):
    base = incident_feedback.bind({'reports': [report()]}, markers('stuck-a'))
    before = copy.deepcopy(base)
    result = incident_feedback.attach_failure_analysis(base, model_feedback(), value)
    assert base == before
    assert result['schema'] == 'rosy.recording.incident_feedback/3'
    row = result['matches'][0]
    assert row['review_state'] == 'unreviewed' and row['reviewed_root_cause'] is None
    assert row['failure_analysis']['label_state'] == 'UNREVIEWED'
    assert 'private-author' not in json.dumps(result)
    return row['failure_analysis']


@pytest.mark.parametrize('category,owner', [('judgment', 'Decision'), ('observation', 'Perception'),
    ('map', 'SiteMap'), ('field_connection', 'Fleet'), ('device', 'CORE/device'), ('unknown', 'unassigned')])
def test_model_classification_is_only_a_responsibility_proposal(category, owner):
    value = attach(analysis(review(category)))
    assert value['review_state'] == 'unreviewed' and value['reviewed_category'] is None
    assert value['candidates'][0]['owner'] == owner


def test_human_candidate_and_conflict_do_not_become_training_truth():
    value = attach(analysis(review(), review('device', 'human')))
    assert (value['review_state'], value['reviewed_category']) == ('review_candidate', 'device')
    value = attach(analysis(review('map', 'human'), review('device', 'human')))
    assert (value['review_state'], value['reviewed_category']) == ('disputed', None)


@pytest.mark.parametrize('fault', ['case', 'hash', 'extra', 'category', 'source', 'author', 'time', 'duplicate', 'empty'])
def test_invalid_analysis_refuses(fault):
    value = analysis(review())
    if fault == 'case': value['case_id'] = 'other'
    elif fault == 'hash': value['model_feedback_digest'] = 'a' * 64
    elif fault == 'extra': value['token'] = 'private'
    elif fault == 'category': value['reviews'][0]['category'] = 'robot_fault'
    elif fault == 'source': value['reviews'][0]['source'] = 'trusted'
    elif fault == 'author': value['reviews'][0]['author_id'] = ''
    elif fault == 'time': value['reviews'][0]['at'] = '2026-10-12'
    elif fault == 'duplicate': value['reviews'] *= 2
    else: value['reviews'] = []
    with pytest.raises(ValueError): attach(value)


def test_cli_connects_analysis_only_with_bound_model_feedback(tmp_path, monkeypatch):
    files = {name: tmp_path / (name + '.json') for name in ('incidents', 'markers', 'model', 'analysis', 'out')}
    for name, value in [('incidents', {'reports': [report()]}), ('markers', markers('stuck-a')),
                        ('model', model_feedback()), ('analysis', analysis(review()))]:
        files[name].write_text(json.dumps(value), encoding='utf-8')
    argv = ['incident_feedback.py', str(files['incidents']), str(files['markers']), '--model-feedback',
            str(files['model']), '--failure-analysis', str(files['analysis']), '--out', str(files['out'])]
    monkeypatch.setattr(sys, 'argv', argv)
    incident_feedback.main()
    assert json.loads(files['out'].read_text())['schema'].endswith('/3')
    with pytest.raises(FileExistsError): incident_feedback.main()


@pytest.mark.parametrize('fault', ['missing_model', 'oversized'])
def test_cli_rejects_missing_binding_and_oversized_analysis_before_output(tmp_path, monkeypatch, fault):
    files = {name: tmp_path / (name + '.json') for name in ('incidents', 'markers', 'model', 'analysis', 'out')}
    for name, value in [('incidents', {'reports': [report()]}), ('markers', markers('stuck-a')),
                        ('model', model_feedback()), ('analysis', analysis(review()))]:
        files[name].write_text(json.dumps(value), encoding='utf-8')
    argv = ['incident_feedback.py', str(files['incidents']), str(files['markers']),
            '--failure-analysis', str(files['analysis']), '--out', str(files['out'])]
    if fault == 'oversized':
        argv += ['--model-feedback', str(files['model'])]
        files['analysis'].write_bytes(b' ' * 65537)
    monkeypatch.setattr(sys, 'argv', argv)
    with pytest.raises(ValueError): incident_feedback.main()
    assert not files['out'].exists()
