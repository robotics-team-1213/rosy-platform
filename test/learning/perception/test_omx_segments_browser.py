"""Human range marking and explicit outcome persist independently of source episode labels."""
import json
import threading

import numpy as np
import pytest
from browser_harness import browser_tests_enabled, free_port
from review_app import ReviewStore, make_server
from learning_workspace import Workspace
from test_omx_web import prepared
from test_review_return import fixture_inputs
import omx_web
import native_segments

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='requires explicit Chromium run')


def test_mark_review_and_download_original_grasp_range(tmp_path, monkeypatch):
    playwright = pytest.importorskip('playwright.sync_api')
    source, human, images = fixture_inputs(tmp_path)
    store = ReviewStore(tmp_path/'state',source,human,images)
    root = tmp_path/'prepared'
    prepared(root)
    report = json.loads((root/'inspection.json').read_text())
    report.update(repo_id='local/native',camera_keys=['observation.images.front'],files={'meta/info.json':'a'*64})
    (root/'inspection.json').write_text(json.dumps(report))
    before = (root/'decisions.json').read_bytes()
    Workspace(store.db).register(dict(kind='omx',name='Grasp source',path=str(root)))
    rows = [dict(episode_index=e,frame_index=f,timestamp=f/30,task='pick',
                 **{'observation.images.front':np.full((3,32,32),f/12,dtype=np.float32)})
            for e in range(2) for f in range(12)]
    monkeypatch.setattr(native_segments.native,'dataset_files',lambda p:report['files'])
    monkeypatch.setattr(native_segments.native,'load_dataset',lambda *a:rows)
    server = make_server(store,free_port())
    thread = threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
            try:
                page.goto(f'http://127.0.0.1:{server.server_port}/learning/omx',wait_until='networkidle')
                page.get_by_text('파지 구간 검수',exact=True).click()
                page.get_by_label('확인 프레임',exact=True).fill('2')
                page.get_by_role('button',name='프레임 확인',exact=True).click()
                playwright.expect(page.locator('details img')).to_be_visible()
                playwright.expect(page.locator('details img')).to_have_js_property('naturalWidth', 32)
                for width,height in [(1440,1000),(390,844),(320,568)]:
                    page.set_viewport_size(dict(width=width,height=height))
                    page.evaluate('scrollTo(0,0)')
                    assert page.locator('details img').bounding_box()['y'] < height
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    for button in page.locator('details [role="button"]').all():
                        if button.is_visible():
                            box=button.bounding_box()
                            assert box['height'] >= 44 and box['width'] >= 44
                page.set_viewport_size(dict(width=1440,height=1000))
                page.get_by_label('원본 Episode',exact=True).select_option('1')
                playwright.expect(page.locator('details img')).to_be_hidden()
                page.get_by_label('원본 Episode',exact=True).select_option('0')
                page.get_by_role('button',name='프레임 확인',exact=True).focus()
                page.keyboard.press('Enter')
                playwright.expect(page.locator('details img')).to_be_visible()
                page.get_by_role('button',name='현재 프레임을 시작으로').click()
                page.get_by_label('끝 프레임 (제외)',exact=True).fill('6')
                page.get_by_label('대상 물체',exact=True).fill('cube')
                page.get_by_label('검수자',exact=True).fill('human')
                page.get_by_label('관찰 근거',exact=True).fill('observed retained object')
                page.get_by_label('구간 결과',exact=True).select_option('success')
                page.get_by_label('분할',exact=True).select_option('train')
                page.get_by_role('button',name='구간 추가',exact=True).click()
                page.get_by_role('button',name='검수 저장',exact=True).click()
                playwright.expect(page.locator('.omx-review')).to_contain_text('검수 1 저장됨')
                with page.expect_download() as download:
                    page.get_by_role('button',name='선택 JSON 내려받기').click()
                document = json.loads(open(download.value.path(),encoding='utf-8').read())
                assert document['segments'][0]['start_frame'] == 2
                assert document['segments'][0]['end_frame'] == 6
                assert document['segments'][0]['outcome'] == 'success'
                page.reload(wait_until='networkidle')
                page.get_by_text('파지 구간 검수',exact=True).click()
                playwright.expect(page.locator('.omx-review')).to_contain_text('[2, 6)')
                # Hold the real POST before it reaches the server; edits must survive its late response.
                page.get_by_label('대상 물체',exact=True).fill('second cube')
                page.get_by_label('검수자',exact=True).fill('human')
                page.get_by_label('관찰 근거',exact=True).fill('second observed grasp')
                page.get_by_role('button',name='구간 추가',exact=True).click()
                pending=[]
                page.route('**/api/learning/omx/segments',lambda route:pending.append(route))
                with page.expect_request('**/api/learning/omx/segments'):
                    page.get_by_role('button',name='검수 저장',exact=True).click()
                assert len(pending) == 1
                playwright.expect(page.get_by_role('button',name='검수 저장',exact=True)).to_be_disabled()
                page.get_by_role('button',name='삭제',exact=True).first.click()
                page.get_by_label('시작 프레임 (포함)',exact=True).fill('7')
                page.get_by_label('끝 프레임 (제외)',exact=True).fill('9')
                page.get_by_label('대상 물체',exact=True).fill('pending cube')
                page.get_by_role('button',name='구간 추가',exact=True).click()
                pending.pop().continue_()
                page.unroute('**/api/learning/omx/segments')
                playwright.expect(page.locator('.omx-review')).to_contain_text('검수 2 저장됨')
                playwright.expect(page.locator('.omx-review')).to_contain_text('pending cube')
                playwright.expect(page.locator('.omx-review')).not_to_contain_text('· cube ·')
                playwright.expect(page.get_by_role('button',name='선택 JSON 내려받기')).to_be_disabled()
                page.get_by_role('button',name='다시 확인',exact=True).click()
                playwright.expect(page.get_by_role('dialog')).to_be_visible()
                page.get_by_role('button',name='취소',exact=True).click()
                playwright.expect(page.locator('.omx-review')).to_contain_text('pending cube')
                page.get_by_role('button',name='검수 저장',exact=True).click()
                playwright.expect(page.locator('.omx-review')).to_contain_text('검수 3 저장됨')
                page.reload(wait_until='networkidle')
                page.get_by_text('파지 구간 검수',exact=True).click()
                playwright.expect(page.locator('.omx-review')).to_contain_text('pending cube')
                playwright.expect(page.locator('.omx-review')).to_contain_text('second cube')
                # An independently saved revision must cause a visible conflict without discarding edits.
                listing=page.request.get(f'http://127.0.0.1:{server.server_port}/api/learning/omx').json()['sets'][0]
                external=page.request.post(f'http://127.0.0.1:{server.server_port}/api/learning/omx/segments',
                    headers={'X-Pinky-Token':page.request.get(f'http://127.0.0.1:{server.server_port}/api/workspace').json()['token']},data=dict(id=listing['id'],version=3,
                    segments=listing['segment_review']['document']['segments']))
                assert external.ok
                page.get_by_role('button',name='삭제',exact=True).first.click()
                page.get_by_role('button',name='검수 저장',exact=True).click()
                playwright.expect(page.locator('.omx-review')).to_contain_text('저장하지 못했습니다')
                playwright.expect(page.locator('.omx-review')).to_contain_text('pending cube')
                page.get_by_role('button',name='다시 확인',exact=True).click()
                page.get_by_role('button',name='편집 버리고 다시 확인',exact=True).click()
                page.get_by_text('파지 구간 검수',exact=True).click()
                playwright.expect(page.locator('.omx-review')).to_contain_text('검수 4 저장됨')
                # A refresh snapshot fetched before a newer save may not detach the live editor.
                page.get_by_role('button',name='삭제',exact=True).first.click()
                stale=[]
                snapshot=page.request.get(f'http://127.0.0.1:{server.server_port}/api/learning/omx')
                page.route('**/api/learning/omx',lambda route:stale.append(route))
                page.get_by_role('button',name='다시 확인',exact=True).click()
                with page.expect_request('**/api/learning/omx'):
                    page.get_by_role('button',name='편집 버리고 다시 확인',exact=True).click()
                assert len(stale) == 1
                page.get_by_role('button',name='검수 저장',exact=True).click()
                playwright.expect(page.locator('.omx-review')).to_contain_text('검수 5 저장됨')
                stale.pop().fulfill(response=snapshot)
                playwright.expect(page.locator('#omx-status')).to_contain_text('기존 화면을 보존했습니다')
                playwright.expect(page.locator('.omx-review')).to_contain_text('검수 5 저장됨')
                playwright.expect(page.locator('.omx-review')).not_to_contain_text('second cube')
                page.unroute('**/api/learning/omx')
                assert (root/'decisions.json').read_bytes() == before
                assert not errors
            finally:
                browser.close()
    finally:
        server.shutdown();server.server_close();thread.join()
