"""Recording workspace browser states; mocked providers are not hardware acceptance."""
import threading
from types import SimpleNamespace

import pytest
from browser_harness import browser_tests_enabled, free_port
from review_app import ReviewStore, make_server

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='requires explicit Chromium run')
PROFILE = '726906cb-5b40-452d-b8a8-cb7d7aceb640'
SESSION = '25a810e4-6fb6-4ce7-af8c-3d93c600baec'


@pytest.fixture
def recording_page(tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    profile = dict(id=PROFILE, revision='revision', profile={
        'name': 'Two working arms', 'task': 'Fixture', 'mode': 'independent',
        'arms': [{'id': arm, 'joint_names': ['joint'], 'units': 'rad'} for arm in ['arm_a', 'arm_b']],
        'cameras': [{'id': 'arm_a_wrist', 'input_key': 'observation.images.arm_a_wrist',
                     'arm_id': 'arm_a', 'role': 'wrist', 'placement': 'wrist',
                     'source_identity': 'fixture:wrist', 'shape': [3, 8, 8], 'purposes': ['policy']}]})
    sources = [dict(id=arm, kind='arm', label=arm, source_identity=arm, status='ready', reason='',
                    arm_id=arm, joint_names=['joint'], units='rad', shape=None, purposes=[], preview_url=None)
               for arm in ['arm_a', 'arm_b']]
    sources.append(dict(id='wrist', kind='camera', label='arm_a_wrist', source_identity='fixture:wrist',
                        status='ready', reason='', arm_id='arm_a', joint_names=None, units=None,
                        shape=[3, 8, 8], purposes=['policy'], preview_url=None))
    snapshot = dict(configured=True, host_id='local', profiles=[profile], sources=sources,
                    sessions=[], active=None, exporter={'available': True, 'reason': ''}, import_available=True)
    session = dict(id=SESSION, name='Fixture capture', profile_id=PROFILE, profile_revision='revision',
                   status='ready', timing={}, episodes=[], export=None, study_id=None, error=None)
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
                page.route('**/api/learning/tasks', lambda route: route.fulfill(json={'token': 'fixture', 'project_id': 'fixture'}))
                page.route('**/recording/snapshot', lambda route: route.fulfill(json=snapshot))
                page.route('**/recording/session/' + SESSION, lambda route: route.fulfill(json=session))
                yield page, snapshot, session, f'http://127.0.0.1:{server.server_port}/learning/record', playwright.expect
                assert not errors
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize('target', ['new', 'other'])
def test_recording_selection_rejects_late_session_and_refreshes_latest(recording_page, target):
    page, snapshot, session, url, expect = recording_page
    other = dict(session, id='b5a810e4-6fb6-4ce7-af8c-3d93c600baec', name='Other capture')
    snapshot['sessions'] = [session, other]
    latest = []
    page.route('**/recording/session/' + other['id'], lambda route: latest.append(route))
    page.goto(url + '?session=' + SESSION, wait_until='networkidle')
    expect(page.locator('#record-name')).to_have_value(session['name'])
    delayed = []
    page.route('**/recording/session/' + SESSION, lambda route: delayed.append(route))
    with page.expect_request('**/recording/session/' + SESSION):
        page.locator('#record-refresh').click()
    expect(page.locator('#record-refresh')).to_be_disabled()
    if target == 'new':
        page.locator('#record-new').click()
    else:
        page.locator('#record-session').select_option(other['id'])
    assert len(delayed) == 1
    if target == 'new':
        delayed.pop().fulfill(json=session)
    else:
        with page.expect_request('**/recording/session/' + other['id']):
            delayed.pop().fulfill(json=session)
        expect(page.locator('#episode-start')).to_be_disabled()
        assert len(latest) == 1
        latest.pop().fulfill(json=other)
    expect(page.locator('#record-refresh')).to_be_enabled()
    if target == 'new':
        expect(page.locator('#record-session')).to_have_value('')
        expect(page.locator('#record-name')).to_have_value('')
        expect(page.locator('#record-name')).to_be_enabled()
        expect(page.locator('#episode-start')).to_be_disabled()
        expect(page.locator('#record-export')).to_be_disabled()
    else:
        expect(page.locator('#record-name')).to_have_value(other['name'])
        expect(page.locator('#record-session')).to_have_value(other['id'])
        posts = []
        page.route('**/recording/start', lambda route: (posts.append(route.request.post_data_json), route.fulfill(json=other)))
        page.locator('#episode-start').click()
        expect(page.locator('#record-status')).to_contain_text('요청 접수')
        assert posts[0]['session_id'] == other['id']


def test_setup_fields_survive_poll_and_preview_only_blocks_start(recording_page):
    page, snapshot, session, url, expect = recording_page
    snapshot['sources'][0].update(status='unavailable', reason='accepted-reference producer missing')
    snapshot['sources'][-1].update(status='preview_only', reason='preview lacks sequence provenance')
    page.goto(url)
    page.locator('#record-name').fill('Unsaved capture name')
    page.locator('#record-timing > summary').click()
    for key, value in [('record-fps', '5'), ('record-camera-age', '0.15'), ('record-arm-age', '0.05'),
                       ('record-camera-skew', '0.1'), ('record-arm-skew', '0.04'), ('record-gap', '0.3')]:
        expect(page.locator('#' + key)).to_have_value(value)
    page.locator('#record-fps').fill('7')
    page.locator('#record-refresh').click()
    expect(page.locator('#record-name')).to_have_value('Unsaved capture name')
    expect(page.locator('#record-fps')).to_have_value('7')
    expect(page.locator('#record-sources')).to_contain_text('accepted-reference producer missing')
    expect(page.locator('#record-sources')).to_contain_text('preview lacks sequence provenance')
    expect(page.locator('#episode-start')).to_be_disabled()
    expect(page.locator('#record-profile-summary')).to_contain_text('arm_a_wrist')


def test_stop_keep_unknown_and_async_export_handoff(recording_page):
    page, snapshot, session, url, expect = recording_page
    session.update(status='recording', episodes=[{'id': 'ep1', 'status': 'recording', 'frames': 3,
                   'integrity_verified': False, 'task_outcome': 'unknown', 'error': None}])
    snapshot['active'] = session
    stops, keeps = [], []

    def stop(route):
        stops.append(route.request.post_data_json)
        session['status'] = 'ready'
        session['episodes'][0].update(status='draft', integrity_verified=True)
        snapshot['active'] = None
        route.fulfill(json=session)

    def keep(route):
        keeps.append(route.request.post_data_json)
        session['episodes'][0].update(status='kept', task_outcome='unknown')
        session['episodes'].append(dict(id='ep2', status='kept', frames=3, integrity_verified=True,
                                        task_outcome='unknown', error=None))
        route.fulfill(json=session)

    def export(route):
        session['export'] = {'status': 'running', 'artifact_url': None, 'error': None}
        route.fulfill(json=session)

    page.route('**/recording/stop', stop)
    page.route('**/recording/keep', keep)
    page.route('**/recording/export', export)
    page.route('**/recording/publish', lambda route: route.fulfill(json={
        'study_id': 'study-fixture', 'url': '/learning/imitate?study=study-fixture&panel=inspect'}))
    page.goto(url + '?session=' + SESSION)
    expect(page.locator('#episode-stop')).to_be_visible()
    expect(page.locator('#episode-stop')).to_be_enabled()
    expect(page.locator('#record-profile')).to_be_disabled()
    page.locator('#episode-stop').click()
    expect(page.locator('[data-keep="ep1"]')).to_be_enabled()
    page.locator('[data-keep="ep1"]').click()
    assert keeps[0]['task_outcome'] == 'unknown'
    assert stops[0]['session_id'] == SESSION
    expect(page.locator('#record-episodes')).to_contain_text('과제 결과 미확인')
    page.locator('#record-export').click()
    expect(page.locator('#export-status')).to_contain_text('변환 중')
    expect(page.locator('#record-publish')).to_be_disabled()
    session['export'] = {'status': 'succeeded', 'artifact_url': '/api/learning/recording/artifact/' + SESSION,
                         'error': None}
    session['episodes'].append(dict(id='leftover', status='draft', frames=3,
                                   integrity_verified=True, task_outcome='unknown', error=None))
    page.locator('#record-refresh').click()
    expect(page.locator('#record-download')).to_be_visible()
    expect(page.locator('#episode-start')).to_be_disabled()
    expect(page.locator('#episode-start-reason')).to_contain_text('새 녹화는 새 세션에서 시작하세요.')
    expect(page.locator('[data-keep="leftover"]')).to_be_disabled()
    expect(page.locator('[data-discard="leftover"]')).to_be_disabled()
    expect(page.locator('[data-outcome="leftover"]')).to_be_disabled()
    page.locator('#record-publish').click()
    expect(page.locator('#record-study-link')).to_have_attribute('href', '/learning/imitate?study=study-fixture&panel=inspect')


def test_record_only_host_exports_without_learning_import(recording_page):
    page, snapshot, session, url, expect = recording_page
    snapshot['import_available'] = False
    session['export'] = {'status': 'succeeded', 'artifact_url': '/api/learning/recording/artifact/' + SESSION,
                         'error': None}
    page.goto(url + '?session=' + SESSION)
    expect(page.locator('#record-download')).to_be_visible()
    expect(page.locator('#record-publish')).to_be_disabled()
    expect(page.locator('#export-status')).to_contain_text('폴더 업로드')


def test_recording_profile_presets_are_unverified_editable_drafts(recording_page):
    page, snapshot, session, url, expect = recording_page
    page.route('**/recording/profiles', lambda route: route.fulfill(json={'profiles': []}))
    page.goto(url.replace('/record', '/omx') + '?profile-store=recording&profile-preset=bimanual#profile-panel')
    expect(page.locator('[data-arm]')).to_have_count(2)
    expect(page.locator('[data-camera]')).to_have_count(3)
    expect(page.locator('[data-arm="0"] [data-field="joints"]')).to_have_value('')
    expect(page.locator('[data-arm="0"] [data-field="units"]')).to_have_value('')
    expect(page.locator('[data-camera="1"] [data-field="id"]')).to_have_value('arm_a_wrist')
    expect(page.locator('[data-camera="1"] [data-field="source_identity"]')).to_have_value('')
    expect(page.locator('[data-camera="1"] [data-field="height"]')).to_have_value('')
    expect(page.locator('[data-camera="2"] [data-field="id"]')).to_have_value('arm_b_wrist')
    page.locator('#profile-add-camera').click()
    expect(page.locator('[data-camera]')).to_have_count(4)


def saved_review_fixture(page, session):
    session['episodes'] = [dict(id='review-fixture', status='draft', frames=2,
                               integrity_verified=True, task_outcome='unknown', error=None)]
    metadata = dict(status='ready', frames=2, fps=5, profile_revision='revision', evidence_revision='a' * 64,
                    checked_at='fixture-check', arms=[dict(id='arm_a', joint_names=['joint'], units='rad')],
                    cameras=[dict(id='arm_a_wrist', role='wrist', placement='wrist', purposes=['policy'], shape=[3, 8, 8]),
                             dict(id='review_only', role='side', placement='side', purposes=['record'], shape=[3, 8, 8])],
                    scope='content_integrity_at_load', physical_learning_verified=False)
    page.route('**/recording/review/' + SESSION + '/review-fixture*', lambda route: route.fulfill(json=metadata))
    page.route('**/recording/review-close', lambda route: route.fulfill(json={'closed': True}))
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"><rect width="8" height="8"/></svg>'
    page.route('**/fixture-saved/**', lambda route: route.fulfill(body=svg, content_type='image/svg+xml'))

    def frame(index):
        return dict(frame_index=index, total_frames=2, grid_time=100 + index / 5, processed_at=100.05 + index / 5,
                    state=[.125 + index], action=[.25 + index], scope='content_integrity_at_load',
                    arms=[dict(id='arm_a', joint_names=['joint'], units='rad', state=[.125 + index],
                               accepted_reference=[.25 + index], state_timestamp=99.99 + index / 5,
                               reference_timestamp=100 + index / 5, received_at=100.01 + index / 5)],
                    cameras=[dict(id=key, role=role, purposes=purposes, sequence=index + 1,
                                  timestamp=100 + index / 5, received_at=100.02 + index / 5,
                                  image_url=f'/fixture-saved/{key}/{index}.svg')
                             for key, role, purposes in [('arm_a_wrist', 'wrist', ['policy']),
                                                         ('review_only', 'side', ['record'])]])

    return frame


def test_saved_review_uses_archived_raw_views_and_joint_values_preserves_frame(recording_page):
    page, snapshot, session, url, expect = recording_page
    snapshot['configured'] = False
    frame = saved_review_fixture(page, session)
    page.route('**/recording/review-frame/**', lambda route: route.fulfill(json=frame(int(route.request.url.rsplit('/', 1)[1]))))
    posts = []
    page.route('**/recording/keep', lambda route: (posts.append(route.request.post_data_json), route.fulfill(json=session)))
    page.goto(url + '?session=' + SESSION)
    expect(page.locator('[data-review="review-fixture"]')).to_have_text('저장 기록 재생·검수')
    page.locator('[data-review="review-fixture"]').click()
    expect(page.locator('#record-review-panel')).to_be_visible()
    expect(page.locator('#review-cameras img')).to_have_count(2)
    expect(page.locator('#review-cameras')).to_contain_text('review_only')
    expect(page.locator('#review-cameras img').first).to_have_attribute('src', '/fixture-saved/arm_a_wrist/0.svg')
    expect(page.locator('#review-joints')).to_contain_text('0.125')
    expect(page.locator('#review-joints')).to_contain_text('0.25')
    expect(page.locator('#review-joints')).to_contain_text('rad')
    expect(page.locator('#review-clocks')).to_contain_text('99.99')
    expect(page.locator('#record-review-status')).to_contain_text('무결성')
    page.locator('#review-next').click()
    expect(page.locator('#review-frame')).to_have_value('1')
    expect(page.locator('#review-joints')).to_contain_text('1.125')
    page.locator('#record-refresh').click()
    expect(page.locator('#review-frame')).to_have_value('1')
    expect(page.locator('#review-frame-position')).to_contain_text('0.2')
    assert posts == []
    assert session['episodes'][0]['task_outcome'] == 'unknown'


def test_saved_review_stale_frame_cannot_paint_after_session_change(recording_page):
    page, snapshot, session, url, expect = recording_page
    frame = saved_review_fixture(page, session)
    delayed = []
    page.route('**/recording/review-frame/**', lambda route: delayed.append(route))
    page.goto(url + '?session=' + SESSION)
    with page.expect_request('**/recording/review-frame/**'):
        page.locator('[data-review="review-fixture"]').click()
    expect(page.locator('#record-review-panel')).to_be_visible()
    page.wait_for_function('document.querySelector("#record-review-status").textContent.length > 0')
    page.locator('#record-new').click()
    assert delayed
    delayed[0].fulfill(json=frame(0))
    expect(page.locator('#record-review-panel')).to_be_hidden()
    expect(page.locator('#review-cameras img')).to_have_count(0)
