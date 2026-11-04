"""A task journey derives evidence without inventing collection or physical acceptance."""
import copy
import uuid

import pytest


def fixture():
    task_id = str(uuid.uuid4())
    task = dict(id=task_id, revision='a'*64, name='Move cup', objective='Cup to tray',
        success='Cup on tray', failure='Cup drops', reset='Return cup', runnable=True,
        profile_id=str(uuid.uuid4()), profile_revision='b'*64,
        profile={'profile': {'arms': [{'id': 'arm_a', 'joint_names': ['joint'], 'units': 'rad'}],
                            'cameras': [{'id': 'top', 'role': 'top'}]}})
    source = dict(prepared_id='c'*32, id='c'*32, name='Reviewed source', source_revision='d'*64,
        fixture_only=False, available=True, latest_review_id=str(uuid.uuid4()),
        trainable={'ok': True}, segment_review={'version': 0, 'document': None},
        binding=dict(task_id=task_id, task_revision=task['revision'],
                     source_revision='d'*64, profile_revision=task['profile_revision']))
    methods = {'act': {'available': True}, 'hilserl': {'available': True}}
    return task, source, methods


def test_recording_is_the_first_task_and_profile_does_not_prove_device_readiness():
    from learning_workflow import project_task
    task, _, methods = fixture()
    result = project_task(task, [], [], methods, 'model')
    assert result['stage'] == 'record'
    assert result['recording']['available'] is False
    assert result['recording']['reason']
    assert result['setup']['device_verified'] is False
    assert result['completion']['recording_complete'] is False
    assert result['completion']['physical_evaluation_complete'] is False


def test_saved_review_and_explicit_current_source_reach_learning():
    from learning_workflow import project_task
    task, source, methods = fixture()
    result = project_task(task, [source], [], methods, 'model')
    assert result['stage'] == 'learn'
    assert result['completion']['review_complete'] is True
    assert result['completion']['recording_complete'] is False  # Explicit historical attachment.
    assert result['inputs'][0]['prepared_id'] == source['prepared_id']
    assert result['methods'][0]['id'] == 'act'


@pytest.mark.parametrize('fault', ['unbound', 'source_changed', 'task_changed', 'fixture', 'unsaved_review'])
def test_incomplete_or_historical_metadata_cannot_enable_learning(fault):
    from learning_workflow import project_task
    task, source, methods = fixture()
    if fault == 'unbound':
        source['binding'] = None
    elif fault == 'source_changed':
        source['source_revision'] = 'e'*64
    elif fault == 'task_changed':
        source['binding']['task_revision'] = 'e'*64
    elif fault == 'fixture':
        source['fixture_only'] = True
    else:
        source['latest_review_id'] = None
    result = project_task(task, [source], [], methods, 'model')
    assert result['stage'] != 'learn'
    assert result['completion']['review_complete'] is False


def test_only_exact_task_runs_prove_offline_completion_not_physical_success():
    from learning_workflow import project_task
    task, source, methods = fixture()
    lineage = dict(task_id=task['id'], task_revision=task['revision'], source_revision=source['source_revision'])
    run = dict(id=str(uuid.uuid4()), status='succeeded', execution_mode='native_train', learning_task=lineage,
        result=dict(learning_task=copy.deepcopy(lineage), evaluation=dict(samples=3,
            model_reloaded_in_new_process=True, physical_task_success=None, mae_per_joint=[.1]*6)))
    result = project_task(task, [source], [run], methods, 'model')
    assert result['stage'] == 'results'
    assert result['completion']['offline_evaluation_complete'] is True
    assert result['completion']['physical_evaluation_complete'] is False
    assert result['completion']['application_approved'] is False
    for changed in [dict(run, learning_task=None), dict(run, status='cancelled')]:
        result = project_task(task, [source], [changed], methods, 'model')
        assert result['completion']['training_complete'] is False


def test_learning_families_keep_their_real_prerequisites_and_pinned_version():
    from learning_workflow import method_catalog
    catalog = method_catalog({'act': {'available': True}, 'hilserl': {'available': True}})
    assert catalog['lerobot_version'] == '0.4.4'
    methods = {row['id']: row for row in catalog['methods']}
    assert methods['act']['state'] == 'available'
    assert methods['hilserl']['label'] == '저장 경험으로 배우기'
    for key in ('online_hilserl', 'vla', 'simulation'):
        assert methods[key]['state'] == 'unavailable'
        assert methods[key]['requirements'] and methods[key]['reason']


def test_active_run_next_action_opens_the_status_and_stop_panel():
    from learning_workflow import project_task
    task, source, methods = fixture()
    for status in ('launching','running','stopping'):
        run = dict(id=str(uuid.uuid4()),status=status,
            learning_task=dict(task_id=task['id'],task_revision=task['revision']))
        result = project_task(task,[source],[run],methods,'model')
        assert result['stage'] == 'learn'
        assert result['next_action']['href'] == '#workflow-results'


def test_missing_registered_source_stays_visible_as_an_unavailable_task_input():
    from types import SimpleNamespace
    from learning_native_catalog import list_inputs
    from learning_workflow import project_task
    task, source, methods = fixture()
    binding = dict(source['binding'], prepared_id=source['prepared_id'])
    inputs = list_inputs(SimpleNamespace(list=lambda: []), None, [binding])
    result = project_task(task, inputs, [], methods, 'model')
    assert len(result['inputs']) == 1 and result['stage'] == 'review'
    assert result['blocked_reason']
    assert result['completion']['review_complete'] is False


def test_recording_card_preserves_task_identity_and_never_guesses_storage_or_calibration():
    from learning_recording_card import make_card
    task, _, _ = fixture()
    with pytest.raises(ValueError):
        make_card(task, {})
    options = dict(root_prefix='/operator/demonstrations', episode_time_s=30, reset_time_s=10, num_episodes=5)
    card = make_card(task, options)
    assert card['schema'] == 'rosy.omx-task-card.v1'
    assert card['single_task'] == task['objective']
    assert card['rosy_learning_task']['id'] == task['id']
    assert card['rosy_learning_task']['revision'] == task['revision']
    assert card['record'] == options
    assert 'calibration' not in card and 'port' not in card and 'policy' not in card
