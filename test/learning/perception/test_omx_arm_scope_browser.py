"""Explicit independent targets and like-action-space comparisons in Chromium."""
import copy
import threading
import uuid
from types import SimpleNamespace

import pytest
from browser_harness import browser_tests_enabled, free_port
from review_app import ReviewStore, make_server

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='requires explicit Chromium run')


def test_independent_arm_targets_both_learners_and_filters_comparisons(tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    profile = {'schema': 'rosy.omx.learning-profile/2', 'name': 'Independent fixture', 'task': 'Fixture task',
        'mode': 'independent', 'arms': [{'id': name, 'joint_names': ['joint'], 'units': 'rad',
                                      'action_limits': [[-1, 1]]} for name in ('A', 'B')],
        'cameras': [{'id': name, 'input_key': 'observation.images.' + name, 'arm_id': arm,
            'role': 'declared', 'source_identity': 'fixture:' + name, 'placement': 'declared',
            'shape': [3, 8, 8], 'purposes': ['policy']} for name, arm in [('top', None), ('a', 'A'), ('b', 'B')]]}
    cooperative = dict(copy.deepcopy(profile), mode='cooperative')

    def scope(mode, arm=None):
        return {'mode': mode, 'arm_ids': [arm] if arm else ['A', 'B'],
            'source_profile_revision': 'a' * 64, 'action_indices': [0 if arm == 'A' else 1] if arm else [0, 1],
            'camera_keys': ['observation.images.top', 'observation.images.' + arm.lower()] if arm else
                           ['observation.images.top', 'observation.images.a', 'observation.images.b']}

    def evaluated(identity, dataset, training_scope=None):
        result = {'steps': 2, 'evaluation': {'frames': 2, 'action_mae': 0.25, 'constant_train_mean_mae': 0.5}}
        if training_scope:
            result['training_scope'] = training_scope
        return dict(id=identity, dataset_id=dataset, method='act', status='succeeded', steps=2, result=result)

    runs = [evaluated('A-result', 'independent', scope('independent', 'A')),
            evaluated('B-result', 'independent', scope('independent', 'B')),
            dict(evaluated('legacy-full-vector', 'independent'), arm_id='A'),
            evaluated('group-result', 'cooperative', scope('cooperative')),
            evaluated('wrong-action-space', 'cooperative', scope('independent', 'A'))]
    requests = []

    def start(body, *, online=False):
        requests.append(dict(body, route='online-run' if online else 'run'))
        row = dict(body, id=str(uuid.uuid4()), status='queued',
                   execution_mode='online_experience' if online else 'offline_replay',
                   training_scope=scope('independent' if body['dataset_id'] == 'independent' else 'cooperative', body.get('arm_id')))
        runs.append(row)
        return row

    center = SimpleNamespace(bind_workspace=lambda project: None, profiles=SimpleNamespace(list=lambda: []),
        snapshot=lambda: {'datasets': [{'id': 'independent', 'name': 'Independent collection', 'profile': profile},
            {'id': 'cooperative', 'name': 'Cooperative collection', 'profile': cooperative}], 'runs': runs,
            'methods': {method: {'available': True} for method in ('act', 'hilserl')}},
        start=start, start_online=lambda body: start(body, online=True))
    store = ReviewStore(tmp_path / 'review', empty_training=True)
    server = make_server(store, free_port(), omx_center=center)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(f'http://127.0.0.1:{server.server_port}/learning/omx?view=all', wait_until='networkidle')
                if page.locator('#dataset option').count() > 1:
                    page.locator('#dataset').select_option(index=1)
                expect = playwright.expect
                expect(page.locator('#arm-target')).to_be_visible()
                expect(page.locator('#arm-target')).to_have_value('')
                expect(page.locator('#start')).to_be_disabled()
                expect(page.locator('#comparison')).to_contain_text('학습 팔을 선택')
                page.locator('#arm-target').select_option('A')
                expect(page.locator('#comparison tbody tr')).to_have_count(1)
                expect(page.locator('#comparison')).to_contain_text('A-result')
                expect(page.locator('#comparison')).not_to_contain_text('legacy-full-vector')
                page.get_by_role('button', name='다시 확인', exact=True).click()
                expect(page.locator('#arm-target')).to_have_value('A')
                page.locator('#start').click()
                expect(page.locator('#runs > section')).to_have_count(6)
                page.locator('#execution-mode').select_option('online_experience')
                page.locator('#start').click()
                expect(page.locator('#runs > section')).to_have_count(7)
                assert [(row['route'], row['arm_id']) for row in requests] == [('run', 'A'), ('online-run', 'A')]
                page.locator('#arm-target').select_option('B')
                expect(page.locator('#comparison tbody tr')).to_have_count(1)
                expect(page.locator('#comparison')).to_contain_text('B-result')
                expect(page.locator('#comparison')).not_to_contain_text('A-result')
                page.locator('#start').click()
                expect(page.locator('#runs > section')).to_have_count(8)
                assert requests[-1]['arm_id'] == 'B' and requests[-1]['route'] == 'online-run'
                assert requests[-1]['request_id'] != requests[-2]['request_id']
                page.locator('#execution-mode').select_option('offline')
                page.locator('#method').select_option('act')
                page.locator('#start').click()
                expect(page.locator('#runs > section')).to_have_count(9)
                assert requests[-1]['arm_id'] == 'B' and requests[-1]['route'] == 'run'
                page.locator('#dataset').select_option('cooperative')
                expect(page.locator('#arm-target')).to_be_hidden()
                expect(page.locator('#arm-target')).to_have_value('')
                expect(page.locator('#comparison tbody tr')).to_have_count(1)
                expect(page.locator('#comparison')).to_contain_text('group-result')
                expect(page.locator('#comparison')).not_to_contain_text('wrong-action-space')
                page.locator('#start').click()
                expect(page.locator('#runs > section')).to_have_count(10)
                page.locator('#execution-mode').select_option('online_experience')
                page.locator('#start').click()
                expect(page.locator('#runs > section')).to_have_count(11)
                assert all('arm_id' not in row for row in requests[-2:])
                expect(page.locator('#runs')).to_contain_text('개별 팔 A')
                expect(page.locator('#runs')).to_contain_text('협동 전체')
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
