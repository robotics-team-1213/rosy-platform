"""The integrated panel consumes the real standalone sample router, without API interception."""
import json
from urllib.parse import urlsplit

from test_sample_browser import sample_site, pytestmark  # noqa: F401


def test_integrated_sample_reads_ownership_and_stops_without_claiming_device_proof(sample_site):
    from playwright.sync_api import expect, sync_playwright
    engine, origin = sample_site
    prefix = '/api/fleet/control-unit'
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={'width': 390, 'height': 844})
            assert page.request.post(origin + '/api/fleet/auth/login', headers={'Origin': origin},
                                     data={'login': 'sample', 'password': 'CHANGE_ME'}).status == 204
            errors, external, writes = [], [], []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: external.append(request.url)
                    if request.url.startswith('http') and urlsplit(request.url).netloc != urlsplit(origin).netloc else None)
            page.on('request', lambda request: writes.append((urlsplit(request.url).path, request.post_data))
                    if request.method == 'POST' and urlsplit(request.url).path.startswith(prefix + '/stops') else None)
            page.goto(origin + '/console?view=work')
            page.locator('#work-integrations > summary').click()  # the panel sits in a closed disclosure
            panel = page.locator('#integrated-control')
            expect(panel).to_be_visible()
            expect(panel).to_contain_text('구성 sample-v1')
            expect(panel).to_contain_text('A1 · 직접 상위 A')
            expect(page.locator('#integrated-control-detail')).to_contain_text('sample-robot')
            panel.get_by_role('button', name='선택 관제 지도 보기', exact=True).click()
            expect(panel.locator('svg[role=img]')).to_have_attribute('aria-label', 'R 관제 활성 지도 · 읽기 전용')
            expect(panel).to_contain_text('지도 sample-site')
            panel.get_by_role('button', name='A · 직접 상위 R', exact=True).click()
            expect(page.locator('#integrated-control-detail')).to_contain_text('직접 소유 로봇이 없습니다')
            page.locator('#integrated-stop').click()
            expect(page.locator('#integrated-stop-results')).to_contain_text('A · 요청 수신')
            expect(page.locator('#integrated-stop-results')).to_contain_text('물리 정지 미확인')
            assert len(writes) == 1
            payload = json.loads(writes[0][1])
            assert payload['target_unit'] == 'A' and set(payload['expected_controls']) == {'A', 'A1'}
            assert engine.work.dispatch['dispatch_enabled'] is True
            child_generation = engine.control_units.fence('A')['generation']
            page.reload()
            page.locator('#work-integrations > summary').click()
            expect(page.locator('#integrated-control')).to_be_visible()
            page.locator('#integrated-control summary').filter(has_text='이 관제의 정지 요청 기록').click()
            page.locator('#integrated-stop-history').get_by_role('button').click()
            expect(page.locator('#integrated-stop-results')).to_contain_text('A · 요청 수신')
            assert len(writes) == 1 and engine.control_units.fence('A')['generation'] == child_generation
            panel.get_by_role('button', name='새 정지 요청 준비', exact=True).click()
            page.locator('#integrated-stop').click()
            expect(page.locator('#integrated-stop-results')).to_contain_text('R · 전달 결과 미확인')
            assert engine.work.dispatch['dispatch_enabled'] is False
            form = page.locator('#integrated-reconcile')
            expect(form).to_be_visible()
            form.locator('summary').click()
            page.get_by_label('기존 정지 전송 연결을 종료했습니다', exact=True).check()
            page.get_by_label('영향받은 receiver의 재시운전을 확인했습니다', exact=True).check()
            page.get_by_label('전송 종료·재시운전 확인 근거', exact=True).fill('실제 장치가 없는 합성 재시운전 확인 예제입니다')
            form.get_by_role('button', name='이 관제의 재시운전 확인 기록', exact=True).click()
            expect(page.locator('#integrated-stop-results')).to_contain_text('운영자 재시운전 확인 기록')
            expect(page.locator('#integrated-stop-results')).to_contain_text('물리 정지 미확인')
            assert len(writes) == 3 and writes[-1][0].endswith('/reconcile')
            assert engine.work.dispatch['dispatch_enabled'] is False
            assert not errors and not external and not engine.unhandled
        finally:
            browser.close()
