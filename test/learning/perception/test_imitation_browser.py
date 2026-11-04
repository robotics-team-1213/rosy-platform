"""Upload study UI state regressions; fixture APIs do not establish learner acceptance."""
import threading
from types import SimpleNamespace

import pytest
from browser_harness import browser_tests_enabled, free_port
from review_app import ReviewStore, make_server

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='requires explicit Chromium run')
STUDY = '4b590f02-c958-459d-a64a-c8ea5d183c98'
RUN = 'fe3d7133-93ee-4577-a382-cbe6c98af283'


@pytest.fixture
def imitation_page(tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    center = SimpleNamespace(bind_workspace=lambda project: None, profiles=SimpleNamespace(list=lambda: []),
                             snapshot=lambda: {'runs': [], 'methods': {}, 'datasets': []})
    server = make_server(ReviewStore(tmp_path / 'review', empty_training=True), free_port(), omx_center=center)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={'width': 1280, 'height': 900})
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                study = dict(id=STUDY, name='Uploaded study', project_id='fixture', revision=1, source_revision='source', status='ready',
                    upload=dict(files=[], total_bytes=0, uploaded_bytes=0, locked=True, manifest_revision='m'),
                    inspection=dict(revision='inspection', robot_type='fixture', fps=20, total_episodes=3,
                        total_frames=30, state={'shape': [7], 'names': []}, action={'shape': [5], 'names': []},
                        cameras=[{'key': 'observation.images.front', 'shape': [8, 8, 3], 'dtype': 'video'}],
                        episodes=[{'index': i, 'frames': 10, 'task': 'fixture'} for i in [2, 8, 12]],
                        units='unknown', capture_session_independence='unknown'), split=None, runs=[])
                state = dict(configured=True, host_id='model', methods={'act': {'available': True}},
                             busy=False, active_run=None, studies=[])
                page.route('**/api/learning/tasks', lambda route: route.fulfill(json={'token': 'fixture', 'project_id': 'fixture'}))
                page.route('**/center/lerobot-studies', lambda route: route.fulfill(json=state))
                page.route('**/center/lerobot-study/' + STUDY, lambda route: route.fulfill(json=study))
                yield page, study, state, f'http://127.0.0.1:{server.server_port}/learning/imitate', playwright.expect
                assert not errors
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_split_must_be_saved_and_poll_preserves_edits(imitation_page):
    page, study, state, url, expect = imitation_page
    posts = []

    def save(route):
        body = route.request.post_data_json
        posts.append(body)
        study['split'] = {key: body[key] for key in ['train', 'validation', 'eval']}
        study['split']['revision'] = 'saved'
        route.fulfill(json=study)

    page.route('**/center/lerobot-split', save)
    page.goto(url + '?study=' + STUDY + '&panel=inspect')
    expect(page.locator('#split-state')).to_contain_text('제안')
    page.locator('[data-episode="8"]').select_option('validation')
    page.locator('#imitate-refresh').click()
    expect(page.locator('[data-episode="8"]')).to_have_value('validation')
    page.locator('#tab-learn').click()
    expect(page.locator('#train-start')).to_be_disabled()
    page.locator('#tab-inspect').click()
    page.locator('#split-save').click()
    expect(page.locator('#split-state')).to_contain_text('저장')
    assert posts[0]['validation'] == [8]
    assert posts[0]['source_revision'] == 'source'
    page.locator('#tab-learn').click()
    expect(page.locator('#train-start')).to_be_enabled()
    page.locator('#train-steps').fill('1234')
    page.locator('#imitate-refresh').click()
    expect(page.locator('#train-steps')).to_have_value('1234')


def test_lost_train_reply_reuses_identity_after_reload_and_stop_is_global(imitation_page):
    page, study, state, url, expect = imitation_page
    study['split'] = {'train': [2, 8], 'validation': [], 'eval': [12], 'revision': 'saved'}
    posts, stops = [], []

    def train(route):
        posts.append(route.request.post_data_json)
        if len(posts) == 1:
            route.fulfill(status=503, json={'error': '응답 유실'})
        else:
            run = dict(id=RUN, status='running', study_id=STUDY, execution_mode='lerobot_train',
                       progress={'phase': 'training', 'step': 1, 'steps': 1000})
            study['runs'] = [run]
            state.update(busy=True, active_run=run)
            route.fulfill(json=run)

    page.route('**/center/lerobot-run', train)
    page.route('**/center/stop', lambda route: (stops.append(route.request.post_data_json), route.fulfill(json={})))
    page.goto(url + '?study=' + STUDY + '&panel=learn')
    page.locator('#train-start').click()
    expect(page.locator('#imitate-error')).to_contain_text('응답 유실')
    page.reload()
    expect(page.locator('#train-start')).to_contain_text('같은')
    page.locator('#train-start').click()
    expect(page.locator('#active-run')).to_contain_text('ACT')
    assert posts[0] == posts[1]
    page.locator('#tab-upload').click()
    expect(page.locator('#active-stop')).to_be_visible()
    page.locator('#active-stop').click()
    assert stops == [{'id': RUN}]


def test_upload_exclusions_and_changed_manifest_block_resume(imitation_page, tmp_path):
    page, study, state, url, expect = imitation_page
    study.update(status='uploading', inspection=None)
    study['upload'] = dict(files=[{'name': 'meta/info.json', 'size': 2, 'sha256': '0' * 64, 'offset': 1}],
                           total_bytes=2, uploaded_bytes=1, locked=False, manifest_revision='m')
    page.goto(url + '?study=' + STUDY)
    folder = tmp_path / 'source'
    (folder / 'meta').mkdir(parents=True)
    (folder / '.cache').mkdir()
    (folder / 'meta/info.json').write_bytes(b'{}')
    (folder / '.cache/state.json').write_bytes(b'{}')
    page.locator('#source-folder').set_input_files(str(folder))
    expect(page.locator('#upload-excluded')).to_contain_text('.cache/state.json')
    expect(page.locator('#imitate-error')).to_contain_text('다릅니다')
    expect(page.locator('#upload-start')).to_be_disabled()
    expect(page.locator('#inspect-start')).to_be_disabled()


def test_upload_requires_storage_but_not_ready_learner(imitation_page, tmp_path):
    page, study, state, url, expect = imitation_page
    state.update(configured=False, methods={'act': {'available': False}})
    folder = tmp_path / 'source'
    (folder / 'meta').mkdir(parents=True)
    (folder / 'meta/info.json').write_bytes(b'{}')
    page.goto(url)
    page.locator('#study-name').fill('Storage availability fixture')
    page.locator('#source-folder').set_input_files(str(folder))
    expect(page.locator('#upload-status')).to_contain_text('파일 내용 확인됨')
    expect(page.locator('#upload-start')).to_be_disabled()
    expect(page.locator('#upload-start')).to_have_attribute('reason', '자료 저장소 연결이 필요합니다.')
    state['configured'] = True
    page.locator('#imitate-refresh').click()
    expect(page.locator('#upload-start')).to_be_enabled()


def test_results_show_original_units_reload_and_no_physical_claim(imitation_page):
    page, study, state, url, expect = imitation_page
    study['runs'] = [dict(id=RUN, status='succeeded', execution_mode='lerobot_train', result={'evaluation': {
        'samples': 10, 'mae_per_joint': [0.25], 'train_mean_baseline_mae_per_joint': [0.5],
        'joint_names': ['action[0]'], 'units': 'unknown', 'model_reloaded_in_new_process': True}})]
    page.goto(url + '?study=' + STUDY + '&panel=results')
    expect(page.locator('#study-results')).to_contain_text('0.25')
    expect(page.locator('#study-results')).to_contain_text('0.5')
    expect(page.locator('#study-results')).to_contain_text('별도 프로세스')
    expect(page.locator('#study-results')).to_contain_text('실물')
    expect(page.locator('[data-artifact]')).to_have_attribute('href', '/api/learning/omx/center/artifact/' + RUN)
