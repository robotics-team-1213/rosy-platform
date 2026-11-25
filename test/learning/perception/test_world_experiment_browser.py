"""Chromium drives same-origin experiment controls on the Learning server."""

import json
import uuid

import pytest

from browser_harness import browser_tests_enabled
from test_world_experiment_web import Accounts, Center, PATH, RUN_ID, START, running


pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='requires explicit Chromium run')


class VisibleCenter(Center):
    def __init__(self):
        super().__init__()
        self.row = None

    def world_experiment(self):
        return {'preset': {'id': START['preset_id'], 'label': 'MuJoCo 시뮬레이션 자료',
                           'kind': 'offline_act', 'steps': 5}, 'runs': [self.row] if self.row else []}

    def start_world_experiment(self, body):
        self.row = dict(super().start_world_experiment(body), progress={'step': 2, 'steps': 5, 'loss': 0.25})
        return self.row

    def stop_world_experiment(self, body):
        self.row = dict(self.row, **super().stop_world_experiment(body))
        self.row.pop('status_uncertain', None)
        return self.row


def test_manager_retries_same_run_and_reader_can_only_watch(tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    center = VisibleCenter()
    with running(tmp_path, Accounts(), center) as base, playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            manager = browser.new_page(viewport={'width': 390, 'height': 880})
            manager.context.add_cookies([{'name': 'rosy_learning_session', 'value': 'reviewer', 'url': base}])
            errors, submissions = [], []
            manager.on('pageerror', lambda error: errors.append(str(error)))

            def lose_first_ack(route):
                submissions.append(route.request.post_data_json)
                if len(submissions) == 1:
                    response = route.fetch()
                    assert response.ok
                    route.abort()
                else:
                    route.continue_()

            manager.route('**' + PATH + '/start', lose_first_ack)
            manager.goto(base + '/learning/world', wait_until='domcontentloaded')
            expect = playwright.expect
            start = manager.locator('#experiment-start')
            expect(manager.locator('#experiment-preset')).to_contain_text('오프라인 ACT')
            expect(start).to_be_enabled()
            start.click()
            expect(start).to_contain_text('다시 확인')
            expect(manager.locator('#experiment-error')).to_be_visible()
            manager.reload(wait_until='domcontentloaded')
            expect(start).to_contain_text('다시 확인')
            start.click()
            expect(manager.locator('#experiment-state')).to_have_text('학습 중')
            expect(manager.locator('#experiment-step')).to_have_text('2 / 5')
            assert submissions[0] == submissions[1]
            assert uuid.UUID(submissions[0]['request_id']).version == 4
            expect(start).to_be_disabled()

            manager.reload(wait_until='domcontentloaded')
            expect(manager.locator('#experiment-run')).to_have_value(RUN_ID)
            reader = browser.new_page()
            reader.context.add_cookies([{'name': 'rosy_learning_session', 'value': 'reader', 'url': base}])
            reader.goto(base + '/learning/world', wait_until='domcontentloaded')
            expect(reader.locator('#experiment-connection')).to_contain_text('조회 전용')
            expect(reader.locator('#experiment-start')).to_be_disabled()
            expect(reader.locator('#experiment-stop')).to_be_disabled()
            expect(reader.locator('#experiment-state')).to_have_text('학습 중')

            manager.locator('#experiment-stop').click()
            expect(manager.locator('#experiment-state')).to_have_text('중지 중')
            expect(manager.locator('#experiment-stop')).to_be_disabled()
            center.row = dict(center.row, status_uncertain=True)
            expect(manager.locator('#experiment-state')).to_contain_text('상태 확인 필요')
            expect(manager.locator('#experiment-stop')).to_be_enabled()
            manager.locator('#experiment-stop').click()
            expect(manager.locator('#experiment-state')).to_have_text('중지 중')
            center.row = dict(center.row, status='stopped')
            expect(manager.locator('#experiment-state')).to_have_text('중지됨')
            assert center.calls[-1] == ('stop', {'id': RUN_ID})
            assert not errors
        finally:
            browser.close()


def test_s3_replay_only_opens_matching_saved_episodes(tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    binding = dict(run_id='physics-run', scene_sha256='a'*64, task='omx-s-s3-pickup-alignment',
                   registration='unregistered-arm-local-proxy', engine='mujoco')
    condition = dict(seed=1000, stratum='nominal', box_dx_m=.001, box_dy_m=0, box_yaw_rad=0,
                     observed_dx_m=.002, observed_dy_m=0, observed_yaw_rad=.01)
    report = dict(binding, schema='rosy.world.s3-evaluation.v1', checkpoint_sha256='b'*64, pairs=[{
        'ik': dict(condition=condition, replay='episode-1000-ik.json', result='not_lifted'),
        'learned': dict(condition=condition, replay='episode-1000-learned.json', result='placed'),
    }])
    episode = dict(binding, schema='rosy.world.s3-replay.v1', policy='learned', checkpoint_sha256='b'*64,
                   condition=condition, result='placed', geometry={
                       'tray': dict(center=[.072, .106], size=[.06, .06], top=.035),
                       'belt': dict(center=[.15, 0], size=[.08, .14], top=.039),
                       'pinky_frame': dict(center=[.072, .168], size=[.08, .034], top=.06),
                       'box_size_m': .04,
                   }, frames=[
                       dict(sim_time_s=0, phase='ready', arm_joints_rad=[0]*6, box_pose_m_wxyz=[.1, 0, .02, 1, 0, 0, 0], tcp_m=[.08, 0, .04]),
                       dict(sim_time_s=.2, phase='lift', arm_joints_rad=[.1]*6, box_pose_m_wxyz=[.1, 0, .09, 1, 0, 0, 0], tcp_m=[.09, .11, .08]),
                   ])

    def file(name, value):
        return {'name': name, 'mimeType': 'application/json', 'buffer': json.dumps(value).encode()}

    with running(tmp_path, Accounts(), VisibleCenter()) as base, playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.context.add_cookies([{'name': 'rosy_learning_session', 'value': 'reader', 'url': base}])
            page.goto(base + '/learning/world', wait_until='domcontentloaded')
            expect = playwright.expect
            page.locator('#experiment-s3-report').set_input_files(file('evaluation.json', report))
            expect(page.locator('#experiment-s3-ik')).to_contain_text('배치 성공 0회')
            expect(page.locator('#experiment-s3-learned')).to_contain_text('배치 성공 1회')
            target = page.locator('#experiment-s3-files')
            target.set_input_files(file('episode-1000-learned.json', dict(episode, checkpoint_sha256='c'*64)))
            expect(page.locator('#experiment-s3-error')).to_contain_text('일치하는 에피소드')
            expect(page.locator('#experiment-s3-player')).to_be_hidden()
            target.set_input_files(file('episode-1000-learned.json', episode))
            expect(page.locator('#experiment-s3-time')).to_have_text('0.00초 · 준비')
            canvas = page.locator('#experiment-s3-canvas')
            expect(canvas).to_be_visible()
            first_frame = canvas.evaluate('(el) => el.toDataURL()')
            page.locator('#experiment-s3-play').click()
            expect(page.locator('#experiment-s3-time')).to_have_text('0.20초 · 들기')
            expect(page.locator('#experiment-s3-box')).to_have_text('0.1000, 0.0000, 0.0900')
            assert canvas.evaluate('(el) => el.toDataURL()') != first_frame
            page.locator('#experiment-s3-scrub').press('Home')
            expect(page.locator('#experiment-s3-time')).to_have_text('0.00초 · 준비')
        finally:
            browser.close()
