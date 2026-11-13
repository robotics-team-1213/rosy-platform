"""Unified Learning workflow, isolated from the frozen review editor suite."""
import json
import os
from pathlib import Path
import re

import pytest

from browser_harness import browser_tests_enabled
from review_app import Conflict
from test_review_app import open_store
from test_review_cycle import CLASSES
from test_review_flow_browser import browser_workspace, serve  # noqa: F401
import review_masks

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='requires explicit Chromium browser run')


@pytest.mark.parametrize('width,theme', [(1366,'dark'),(1366,'light'),(390,'dark'),(390,'light'),(320,'dark'),(320,'light')])
def test_home_routes_and_keyboard_section_navigation(browser_workspace,width,theme):
    page,_,expect=browser_workspace
    base=page.url.split('?')[0].rstrip('/')
    page.set_viewport_size(dict(width=width,height=900))
    page.goto(base+'/learning',wait_until='networkidle')
    page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
    routes=page.get_by_role('navigation',name='학습 작업 선택',exact=True)
    expect(routes.get_by_role('link',name='시연 학습 과제 열기')).to_have_attribute('href','/learning/tasks')
    expect(routes.get_by_role('link',name='인식 자료·학습 열기')).to_have_attribute('href','#pipeline')
    expect(routes.get_by_role('link',name='SIM 실험 열기')).to_have_attribute('href','/learning/sim')
    expect(routes.get_by_role('link',name='VLM 판단 검수 열기')).to_have_attribute('href','/learning/vlm')
    navigation=page.get_by_role('navigation',name='학습센터 작업 이동',exact=True)
    assert navigation.evaluate("node=>node.parentElement.classList.contains('ui-subnav') && node.parentElement.parentElement.classList.contains('ui-app-body')")
    if width < 1024:
        padding=navigation.evaluate("""node=>{const s=getComputedStyle(node);return {
          top:s.paddingTop,bottom:s.paddingBottom,inset:s.getPropertyValue('--inset-rail').trim()};}""")
        assert padding['top'] == padding['bottom'] == padding['inset'], padding
    menu_box, main_box = navigation.bounding_box(), page.locator('.ui-app-main').bounding_box()
    assert menu_box['x']+menu_box['width'] <= main_box['x']+1 if width>=1024 else menu_box['y']+menu_box['height'] <= main_box['y']+1
    assert main_box['y'] < page.viewport_size['height']
    for name,target in [('인식 자료·학습','pipeline'),('검수 대기','review-section'),
                        ('실행·평가 결과','learning-results'),('저장·계정','storage-section'),
                        ('작업 선택','learning-start')]:
        link=navigation.get_by_role('link',name=name,exact=True)
        link.focus()
        page.keyboard.press('Enter')
        expect(page).to_have_url(base+'/learning#'+target)
        expect(page.locator('#'+target)).to_be_focused()
        expect(page.locator('#'+target)).to_be_visible()
        for other in ['learning-start','pipeline','review-section','learning-results','storage-section']:
            if other!=target:
                expect(page.locator('#'+other)).to_be_hidden()
        expect(link).to_have_attribute('aria-current','location')
        link.focus()
        page.keyboard.press('Enter')
        expect(page.locator('#'+target)).to_be_focused()
        paint = link.evaluate("""node=>{const s=getComputedStyle(node),other=node.closest('nav').querySelector('a:not([aria-current])');
          return {alignment:s.textAlign,selected:s.backgroundColor,other:getComputedStyle(other).backgroundColor};}""")
        assert paint['alignment'] == 'start' and paint['selected'] != paint['other'], paint
        expect(navigation).to_have_class(re.compile(r'\bui-subnav-nav\b'))
        expect(link).to_have_class(re.compile(r'\bui-subnav-item\b'))
        if output:=os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
            capture=Path(output)/f'learning-home-{target}-{theme}-{width}.png'
            capture.parent.mkdir(parents=True,exist_ok=True)
            link.focus()
            page.keyboard.press('Tab')
            page.keyboard.press('Shift+Tab')
            expect(link).to_be_focused()
            metrics=link.evaluate("""node=>{const s=getComputedStyle(node),nav=node.closest('nav');
              return {paint:Object.fromEntries(['display','alignItems','justifyContent','textAlign','paddingTop','paddingRight','paddingBottom','paddingLeft',
                'minHeight','fontSize','fontWeight','lineHeight','borderRadius','borderTopWidth','backgroundColor','color','appearance',
                'outlineStyle','outlineWidth','outlineColor','outlineOffset'].map(key=>[key,s[key]])),item:node.getBoundingClientRect().toJSON(),
                nav:nav.getBoundingClientRect().toJSON(),gap:getComputedStyle(nav).gap,
                navPadding:{top:getComputedStyle(nav).paddingTop,bottom:getComputedStyle(nav).paddingBottom,
                  inset:getComputedStyle(nav).getPropertyValue('--inset-rail').trim()},current:node.getAttribute('aria-current'),
                focus:document.activeElement===node,focusVisible:node.matches(':focus-visible'),overflow:document.documentElement.scrollWidth-innerWidth};}""")
            page.screenshot(path=str(capture))
            capture.with_suffix('.json').write_text(json.dumps(dict(viewport=page.viewport_size,theme=theme,
                state=target,filename=capture.name,**metrics),ensure_ascii=False,indent=2),encoding='utf-8')
            page.locator('#'+target).focus()
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    if output:=os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
        target=Path(output)/f'learning-home-routes-{theme}-{width}.png'
        target.parent.mkdir(parents=True,exist_ok=True)
        page.evaluate('() => { document.activeElement?.blur(); window.scrollTo(0,0); }')
        page.screenshot(path=str(target))


@pytest.mark.parametrize('route',['/catalog','/learning/sim','/learning/vlm','/learning/evaluate'])
def test_home_return_from_other_learning_areas(browser_workspace,route):
    page,_,expect=browser_workspace
    base=page.url.split('?')[0].rstrip('/')
    page.goto(base+route,wait_until='domcontentloaded')
    home=page.get_by_role('navigation',name='학습 화면',exact=True).get_by_role('link',name='홈',exact=True)
    home.focus()
    page.keyboard.press('Enter')
    expect(page).to_have_url(base+'/learning')
    start=page.get_by_role('navigation',name='학습센터 작업 이동',exact=True).get_by_role('link',name='작업 선택',exact=True)
    start.focus()
    page.keyboard.press('Enter')
    expect(page).to_have_url(base+'/learning#learning-start')
    expect(page.locator('#learning-start')).to_be_focused()


def test_home_status_strip_reads_one_learning_response(browser_workspace):
    # 5b: 홈 상태줄은 실행기·두 검수 대기 수를 /api/learning 한 번으로 보여준다(GPU 항목·새 API 없음).
    page,_,expect=browser_workspace
    base=page.url.split('?')[0].rstrip('/')
    page.goto(base+'/learning',wait_until='networkidle')
    payload=page.request.get(base+'/api/learning').json()
    strip=page.locator('#home-status-strip')
    expect(strip).to_be_visible()
    expect(strip).to_contain_text('실행기 ')
    expect(strip).to_contain_text(f"객체 검수 대기 {payload['counts']['pending']}장")
    expect(strip).to_contain_text(f"픽셀 검수 대기 {payload['pixel_counts']['pending']}장")
    control=payload.get('control')
    if not control or not control.get('available'):
        expect(strip).to_contain_text('실행기 연결 필요')


@pytest.mark.parametrize('width', [1440, 390, 320])
@pytest.mark.parametrize('theme', ['dark', 'light'])
def test_learning_pipeline_prepares_current_reviews_in_app(browser_workspace, width, theme):
    page, store, expect = browser_workspace
    review_masks.bind_classes(store, CLASSES)
    review_masks.update(store, 0, {'version': 0, 'action': 'fill', 'label': 0}, Conflict)
    review_masks.update(store, 0, {'version': 1, 'action': 'approve',
                                   'complete_frame_review': True, 'background_reviewed': True}, Conflict)
    page.set_viewport_size({'width': width, 'height': 844})
    page.goto(page.url.split('?')[0].rstrip('/') + '/learning', wait_until='domcontentloaded')
    page.evaluate('(theme)=>document.documentElement.dataset.theme=theme', theme)
    page.get_by_role('link',name='인식 자료·학습 열기',exact=True).click()
    action = page.locator('#pipeline-action')
    expect(action).to_have_text('승인 자료 준비')
    expect(action).to_be_enabled()
    track = page.locator('#pipeline-stages')
    expect(track).to_have_class(re.compile(r'(^|\s)ui-stage-track(\s|$)'))
    expect(track).to_have_attribute('data-line', 'learning')
    payload = page.request.get(page.url.split('/learning')[0] + '/api/learning').json()
    for step in payload['pipeline']['stages']:
        station = track.locator(f'[data-stage="{step["id"]}"]')
        expect(station).to_have_class(re.compile(r'(^|\s)ui-stage(\s|$)'))
        expect(station).to_have_attribute('data-status', step['state'])
        expect(station).to_contain_text(step['detail'])
    assert action.bounding_box()['y'] + action.bounding_box()['height'] <= 844
    page.route('**/api/prepare', lambda route: route.fulfill(status=400,
               content_type='application/json', body=json.dumps({'error': '자료 준비 실패'})))
    action.click()
    expect(page.locator('#learning-error')).to_contain_text('자료 준비 실패')
    expect(action).to_be_enabled()
    page.unroute('**/api/prepare')
    action.click()
    expect(page.locator('[data-stage="preparation"]')).to_have_attribute('data-state', 'done')
    expect(page.locator('#pipeline-link')).to_have_text('학습 실행기 연결 안내')
    assert store.exports()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    if output := os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
        target = Path(output) / f'learning-stations-{theme}-{width}.png'
        target.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target))


def test_learning_pipeline_automatically_connects_owner_and_invalidates_new_decisions(tmp_path):
    import review_evidence
    from learning_control import Control
    from learning_workspace import Workspace
    from test_learning_control import binding
    from test_learning_pipeline import ledger
    (tmp_path / 'review').mkdir()
    store = open_store(tmp_path / 'review')
    review_masks.bind_classes(store, CLASSES)
    review_masks.update(store, 0, {'version': 0, 'action': 'fill', 'label': 0}, Conflict)
    review_masks.update(store, 0, {'version': 1, 'action': 'approve',
                                   'complete_frame_review': True, 'background_reviewed': True}, Conflict)
    store.prepare()
    current = review_evidence.decisions(store)
    file, home, out, _, runner = binding(tmp_path / 'owner', current['workspace_id'])
    doc = ledger()
    doc['review_autobuild']['authority'] = {key: current[key] for key in
                                           ('workspace_id', 'generation', 'decision_sha256')}
    (out / 'state.json').write_text(json.dumps(doc))
    target = Control(file, current['workspace_id'], home=home, runner=runner)
    with serve(store, target) as (page, _, expect):
        page.goto(page.url.split('?')[0].rstrip('/') + '/learning#pipeline', wait_until='domcontentloaded')
        expect(page.locator('[data-stage="evaluation"]')).to_have_attribute('data-state', 'done')
        page.locator('#pipeline-evidence summary').click()
        expect(page.locator('#pipeline-evidence')).to_contain_text('current-model')
        expect(page.locator('#pipeline-evidence')).to_contain_text('평가·READY 기록 확인')
        expect(page.locator('#training-data-state')).to_contain_text('현재 검수 자료가 데이터셋에 연결됐습니다')
        expect(page.locator('#owner-control-start')).not_to_have_attribute('reason', re.compile('.+'))
        assert Workspace(store.db).list() == []
        assert page.locator('#owner-control-status').count() == 1
        page.screenshot(path=str(tmp_path / 'learning-pipeline-desktop.png'), full_page=True)
        print('LEARNING_SCREENSHOT=' + str(tmp_path / 'learning-pipeline-desktop.png'))
        page.set_viewport_size({'width': 390, 'height': 844})
        page.screenshot(path=str(tmp_path / 'learning-pipeline-mobile.png'), full_page=True)
        print('LEARNING_SCREENSHOT=' + str(tmp_path / 'learning-pipeline-mobile.png'))
        review_masks.update(store, 0, {'version': 2, 'action': 'reopen'}, Conflict)
        # Polling must read current decisions, even if the owner service has not changed.
        expect(page.locator('[data-stage="evaluation"]')).not_to_have_attribute('data-state', 'done', timeout=12000)
        expect(page.locator('#pipeline-link')).to_have_text('픽셀 검수 시작')
        page.route('**/api/learning', lambda route: route.fulfill(status=503,
                   content_type='application/json', body='{}'))
        expect(page.locator('#pipeline-action')).to_be_disabled(timeout=12000)
        expect(page.locator('#pipeline-stages')).to_be_empty(timeout=12000)
        expect(page.get_by_role('button', name='학습 시작', exact=True)).to_be_disabled()


def test_home_nested_tools_keep_drafts_and_history(browser_workspace):
    page,_,expect=browser_workspace
    base=page.url.split('?')[0].rstrip('/')
    page.goto(base+'/learning#connection-panel',wait_until='networkidle')
    expect(page.locator('#name')).to_be_focused()
    page.locator('#name').fill('keep my draft')
    page.locator('#path').fill('/draft/report')
    if output:=os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
        capture=Path(output)/'learning-home-connection-draft.png'
        capture.parent.mkdir(parents=True,exist_ok=True)
        page.screenshot(path=str(capture))
    navigation=page.locator('.learning-home-nav')
    navigation.locator('a[href="#pipeline"]').click()
    expect(page.locator('#connection-panel')).to_be_hidden()
    track=page.locator('#pipeline-stages')
    for stage,href in [('data','/catalog'),('review','/pixels?filter=pending'),
                       ('preparation','/pixels#pixel-preparation'),('dataset','#pipeline-evidence'),
                       ('training','#pipeline-setup'),('evaluation','#pipeline-evidence'),
                       ('application','/learning/evaluate')]:
        expect(track.locator(f'[data-stage="{stage}"] a')).to_have_attribute('href',href)
    track.locator('[data-stage="training"] a').click()
    expect(page.locator('#pipeline-setup')).to_be_visible()
    if output:=os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
        capture=Path(output)/'learning-home-pipeline-setup.png'
        capture.parent.mkdir(parents=True,exist_ok=True)
        page.screenshot(path=str(capture))
    expect(page.locator('#pipeline-evidence')).to_be_hidden()
    page.go_back()
    expect(page.locator('#pipeline')).to_be_visible()
    page.go_back()
    expect(page.locator('#name')).to_have_value('keep my draft')
    expect(page.locator('#path')).to_have_value('/draft/report')
    expect(page.locator('#connection-panel')).to_be_visible()
    page.go_forward()
    expect(page.locator('#pipeline')).to_be_visible()
    assert page.locator('details').count()<=1


@pytest.mark.parametrize('width,theme',[(1366,'dark'),(1366,'light'),(390,'dark'),(390,'light')])
def test_home_many_jobs_use_selected_detail_without_extra_folds(browser_workspace,width,theme):
    page,_,expect=browser_workspace
    base=page.url.split('?')[0].rstrip('/')
    payload=page.request.get(base+'/api/learning').json()
    kind=payload['workflows'][0]['id']
    payload['items']=[dict(id=f'job-{n}',name=f'Example {n}',kind=kind,path=f'/result/{n}',version=1,
                           reports=[dict(name='report.json',status='unchanged',declared={},steps=[],metrics=[],images=[])])
                      for n in range(8)]
    page.route('**/api/learning',lambda route:route.fulfill(json=payload))
    page.set_viewport_size(dict(width=width,height=900))
    page.goto(base+'/learning#learning-results',wait_until='networkidle')
    page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
    expect(page.locator('#jobs [data-job]')).to_have_count(8)
    assert page.locator('details').count()==1
    page.locator('#jobs [data-job="job-3"] a[href^="#job-"]').click()
    expect(page.locator('#jobs')).to_be_hidden()
    expect(page.locator('[data-job-detail="job-3"]')).to_be_visible()
    expect(page.locator('[data-job-detail="job-2"]')).to_be_hidden()
    expect(page.locator('[data-job-detail="job-3"]')).to_contain_text('/result/3')
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.go_back()
    expect(page.locator('#jobs [data-job]')).to_have_count(8)
    expect(page.locator('#job-detail')).to_be_hidden()


@pytest.mark.parametrize('fragment',['#job-%','#job-missing'])
def test_home_invalid_job_link_falls_back_without_losing_draft(browser_workspace,fragment):
    page,_,expect=browser_workspace
    base=page.url.split('?')[0].rstrip('/')
    page.goto(base+'/learning#connection-panel',wait_until='networkidle')
    page.locator('#name').fill('saved draft')
    page.locator('#path').fill('/draft/unchanged')
    page.evaluate('(fragment)=>location.hash=fragment',fragment)
    expect(page.locator('#learning-start')).to_be_visible()
    expect(page.locator('#job-detail')).to_be_hidden()
    expect(page.locator('#connection-panel')).to_be_hidden()
    page.go_back()
    expect(page.locator('#connection-panel')).to_be_visible()
    expect(page.locator('#name')).to_have_value('saved draft')
    expect(page.locator('#path')).to_have_value('/draft/unchanged')


@pytest.mark.parametrize('status',[401,403,503])
def test_home_selected_job_is_cleared_when_polling_loses_access(browser_workspace,status):
    page,_,expect=browser_workspace
    base=page.url.split('?')[0].rstrip('/')
    payload=page.request.get(base+'/api/learning').json()
    kind=payload['workflows'][0]['id']
    payload['items']=[dict(id='protected-job',name='Protected result',kind=kind,
                           path='/private/result-path',version=1,
                           reports=[dict(name='report.json',status='unchanged',declared={},steps=[],metrics=[],images=[])])]
    page.route('**/api/learning',lambda route:route.fulfill(json=payload))
    page.clock.install()
    page.goto(base+'/learning#learning-results',wait_until='networkidle')
    page.locator('#jobs a[href="#job-protected-job"]').click()
    expect(page.locator('#job-detail-content')).to_contain_text('/private/result-path')
    page.route('**/api/learning',lambda route:route.fulfill(status=status,json={'error':'unavailable'}))
    page.clock.fast_forward(5000)
    expect(page.locator('#learning-status')).to_have_attribute('state','error')
    expect(page.locator('#job-detail-content')).to_be_empty()
    expect(page.locator('#jobs')).to_be_empty()
    page.locator('.learning-home-nav a[href="#learning-start"]').click()
    page.go_back()
    expect(page).to_have_url(base+'/learning#job-protected-job')
    expect(page.locator('#learning-start')).to_be_visible()
    expect(page.locator('#job-detail')).to_be_hidden()
    expect(page.locator('#job-detail-content')).to_be_empty()
    expect(page.locator('#refresh')).to_be_enabled()


def test_home_shows_top_level_failure_reason_and_separates_failed_from_rejected(browser_workspace):
    page,_,expect=browser_workspace
    base=page.url.split('?')[0].rstrip('/')
    payload=page.request.get(base+'/api/learning').json()
    kind=payload['workflows'][0]['id']
    def job(name,declared):
        return dict(id=name,name=name,kind=kind,path='/result/'+name,version=1,
                    reports=[dict(name='state.json',status='unchanged',declared=declared,steps=[],metrics=[],images=[])])
    payload['items']=[job('stopped',dict(status='failed',error='학습 데이터가 비어 있어 중단했습니다')),
                      job('refused',dict(outcome='rejected')),
                      job('busy',dict(status='running'))]
    page.route('**/api/learning',lambda route:route.fulfill(json=payload))
    page.goto(base+'/learning#learning-results',wait_until='networkidle')
    stopped=page.locator('#jobs [data-job="stopped"]')
    expect(stopped).to_contain_text('학습 데이터가 비어 있어 중단했습니다')
    expect(stopped).to_contain_text('실패 확인')
    expect(page.locator('#jobs [data-job="refused"]')).to_contain_text('거절 확인')
    expect(page.locator('#jobs [data-job="busy"]')).to_contain_text('끝나기를 기다리세요')


def test_home_app_bar_stays_usable_when_learning_is_forbidden(browser_workspace):
    page,_,expect=browser_workspace
    base=page.url.split('?')[0].rstrip('/')
    page.route('**/api/learning',lambda route:route.fulfill(status=403,json=dict(detail='denied')))
    page.goto(base+'/learning',wait_until='networkidle')
    expect(page.locator('#refresh')).to_be_enabled()
    assert page.locator('ui-topbar ui-button:not([data-always-live])').evaluate_all('nodes=>nodes.every(n=>!n.disabled&&!n.getAttribute("reason"))')
