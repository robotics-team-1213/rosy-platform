"""The 학습 사다리 screen in Chromium: see rounds, judge one, start another; simulation evidence only."""
import json
import os
import threading
from pathlib import Path

import pytest
from browser_harness import browser_tests_enabled, free_port
import ladder_web
from ladder_fixture import config, make_root
from review_app import make_server
from test_learning_collaboration import Accounts
from test_ladder_web import MID, NEW, OLD, ROUNDS
from test_review_app import open_store

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='requires explicit Chromium run')


class Recorded(ladder_web.Ladder):
    started = None

    def start(self, body):
        self.started = body
        return True

    def start_two_arm(self, body):
        self.started_two_arm = body
        return True


def serve(tmp_path, *, configured=True):
    root = make_root(tmp_path, ROUNDS)
    bad = root / 'rounds' / '20261108T010000-dddddddd'
    bad.mkdir()
    (bad / 'round.json').write_text('{broken', encoding='utf-8')
    run = root / 'two_arm' / OLD
    run.mkdir(parents=True)
    (run / 'run.json').write_text(json.dumps(dict(
        schema=ladder_web.TWO_ARM_SCHEMA, run_id=OLD, task='rehandle', seed=0, status='failed', steps=12, steps_pass=11, final_ok=5, final_total=6,
        roll_below_floor_steps=['a1'], failed_steps=[dict(step='r2', arm='arm_a', result='blocked', reason='too far')])), encoding='utf-8')
    learned = root / 'two_arm_rounds' / OLD
    learned.mkdir(parents=True)
    (learned / 'round.json').write_text(json.dumps(dict(
        schema=ladder_web.TWO_ARM_ROUND_SCHEMA, round_id=OLD, status='passed', stage='done', data=dict(episodes=630, frames=178236), recipe=dict(steps=60000),
        eval=dict(n=63, passed=20, lifted=50, wilson_low=.2, wilson_high=.4, per_step={'stack/s1': 3, 'stack/s2': 0}, whole=[dict(task='stack', seed=1, total=9, passed=2, completed=False)]))), encoding='utf-8')
    compare = root / 'two_arm_compare' / OLD
    compare.mkdir(parents=True)
    (compare / 'compare.json').write_text(json.dumps(dict(
        schema=ladder_web.TWO_ARM_COMPARE_SCHEMA, run_id=OLD, seed=0, status='passed', runs=[
            dict(scenario='outbound', mode='one-arm-B', steps=5, steps_pass=5, completed=True, makespan_s=92.5, planned_makespan_s=90.0,
                 holds=[dict(request='bar-3', reason='NO_STAND_IN_REACH')], moves_per_arm={'arm_b': 5}),
            dict(scenario='outbound', mode='two-arm', concurrent=True, steps=10, steps_pass=10, completed=True, makespan_s=165.7, overlap_s=18.2,
                 planned_makespan_s=153.8, holds=[], moves_per_arm={'arm_a': 5, 'arm_b': 5})])), encoding='utf-8')
    ladder = Recorded(config(tmp_path, root)) if configured else None
    server = make_server(open_store(tmp_path), free_port(), accounts=Accounts(), ladder=ladder)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, ladder, root


@pytest.mark.parametrize('width', [1280, 390])
@pytest.mark.parametrize('session', ['reader', 'reviewer'])
def test_rounds_detail_decision_and_start(tmp_path, width, session):
    playwright = pytest.importorskip('playwright.sync_api')
    server, ladder, root = serve(tmp_path)
    base = f'http://127.0.0.1:{server.server_port}'
    shots = os.environ.get('ROSY_LADDER_SHOTS')
    try:
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': width, 'height': 900})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            browser.contexts[0].add_cookies([{'name': 'rosy_learning_session', 'value': session, 'url': base}])
            expect = playwright.expect
            try:
                page.goto(base + '/learning/ladder', wait_until='networkidle')
                cards = page.locator('#ladder-rounds article')
                expect(cards).to_have_count(4)
                expect(cards.nth(0)).to_contain_text('읽을 수 없습니다')
                expect(cards.nth(1)).to_contain_text(NEW)
                expect(cards.nth(3)).to_contain_text('이유: Gazebo 시험 PC에 연결되지 않았습니다.')
                expect(cards.nth(3)).to_contain_text('⊘ 막힘')
                expect(cards.nth(3)).to_contain_text('– 실행 안 함')
                expect(cards.nth(3)).to_contain_text('말할 수 있는 범위: ROS 실행 계약')
                cards.nth(3).locator('ui-button').click()
                detail = page.locator('#ladder-detail')
                expect(detail).to_contain_text('시뮬레이션 근거입니다. 실제 팔이 성공했다는 뜻이 아닙니다')
                expect(detail).to_contain_text('엄격 성공 12 / 50 (24.0%)')
                expect(detail).to_contain_text('아직 비교 기준이 없습니다')
                expect(detail.locator('img')).to_have_count(1)
                two_arm = page.locator('#ladder-two-arm')
                expect(two_arm).to_contain_text('임시 칸 재취급')
                expect(two_arm).to_contain_text('단계 통과 11 / 12')
                expect(two_arm).to_contain_text('실패 r2 (arm_a): too far')
                expect(two_arm).to_contain_text('실물 손목 하한 아래로 가는 단계')
                compared = page.locator('#ladder-compare')
                expect(compared).to_contain_text('bar-3: 반출 자리(임시 칸 줄)로 옮길 팔 없음')
                expect(compared).to_contain_text('165.7초 (계획 153.8초)')
                expect(compared.locator('table')).to_have_count(1)
                learned = page.locator('#ladder-two-arm-rounds')
                expect(learned).to_contain_text('단계별 통과 20 / 63')
                expect(learned).to_contain_text('3×3×3 적층 전체 · 시드 1: 2 / 9 단계에서 멈춤')
                expect(learned).to_contain_text('한 번도 통과하지 못한 단계: stack/s2')
                body = page.locator('main').inner_text()
                assert '승인' not in body and '승격' not in body
                if session == 'reader':
                    expect(page.locator('#ladder-decide')).to_be_disabled()
                    expect(page.locator('#ladder-start')).to_be_disabled()
                    expect(page.locator('#ladder-two-arm-start')).to_be_disabled()
                    expect(page.locator('#ladder-compare-start')).to_be_disabled()
                else:
                    expect(page.locator('#ladder-decide')).to_be_enabled()
                    page.locator('#ladder-note').fill('엄격 성공이 높다')
                    page.locator('#ladder-decide').click()
                    expect(page.locator('#ladder-decided')).to_contain_text('현재 비교 기준: ' + OLD)
                    expect(page.locator('#ladder-rounds')).to_contain_text('현재 비교 기준')
                    assert (root / 'best.json').exists()
                    cards.nth(2).locator('ui-button').click()
                    expect(detail).to_contain_text('더 좋음')
                    cards.nth(1).locator('ui-button').click()
                    expect(detail).to_contain_text('✕ 실패')
                    expect(page.locator('#ladder-decide')).to_be_disabled()
                    page.locator('#ladder-steps').fill('300')
                    page.locator('#ladder-start').click()
                    expect(page.locator('#ladder-notice')).to_contain_text('라운드를 시작했습니다')
                    assert ladder.started == {'episodes': 60, 'eval_episodes': 50, 'steps': 300, 'lr': 1e-05, 'parent': None}
                    page.locator('#ladder-two-arm-task').select_option('rehandle')
                    page.locator('#ladder-two-arm-seed').fill('2')
                    page.locator('#ladder-two-arm-start').click()
                    expect(page.locator('#ladder-notice')).to_contain_text('양팔 태스크를 시작했습니다')
                    assert ladder.started_two_arm == {'task': 'rehandle', 'seed': 2}
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                assert errors == []
                if shots:
                    page.screenshot(path=str(Path(shots) / f'ladder-{session}-{width}.png'), full_page=True)
            finally:
                browser.close()
    finally:
        server.shutdown(); server.server_close()


def test_unconfigured_screen_says_not_connected_and_cannot_start(tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    server, _, _ = serve(tmp_path, configured=False)
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            browser.contexts[0].add_cookies([{'name': 'rosy_learning_session', 'value': 'reviewer', 'url': base}])
            try:
                page.goto(base + '/learning/ladder', wait_until='networkidle')
                playwright.expect(page.locator('#ladder-rounds')).to_contain_text('연결되지 않았습니다')
                playwright.expect(page.locator('#ladder-start')).to_be_disabled()
                playwright.expect(page.locator('#ladder-start-state')).to_contain_text('연결되지 않았습니다')
            finally:
                browser.close()
    finally:
        server.shutdown(); server.server_close()
