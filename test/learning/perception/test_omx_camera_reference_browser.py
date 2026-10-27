"""PR #200 / D-792 S3: the OMX page tells prepare-native reference matches apart from shadow evidence."""
import threading

import pytest
from browser_harness import browser_tests_enabled, free_port
from learning_workspace import Workspace
from review_app import ReviewStore, make_server
from test_omx_web import native, prepared
from test_review_return import fixture_inputs

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='requires explicit Chromium run')
MATCH = '기준 일치(prepare-native에서 거부 검사 통과)'
NONE = '카메라 맞춤 판정 없음'


@pytest.mark.parametrize('width,height', [(1440, 1000), (390, 844)])
def test_native_shadow_both_and_none_are_distinguished(tmp_path, width, height):
    playwright = pytest.importorskip('playwright.sync_api')
    source, human, images = fixture_inputs(tmp_path)
    store = ReviewStore(tmp_path / 'state', source, human, images)
    (store.state / 'camera-setup').mkdir(parents=True)
    (store.state / 'camera-setup' / f'{"c" * 64}.json').write_text('{}')
    sets = {'Native set': lambda r: native(r, {'top': 'c' * 64, 'wrist': 'd' * 64}),
            'Both set': lambda r: native(r, {'top': 'c' * 64}, camera=True),
            'Shadow set': prepared, 'Plain set': lambda r: prepared(r, camera=False)}
    for index, (name, make) in enumerate(sets.items()):
        make(tmp_path / f'set{index}')
        Workspace(store.db).register(dict(kind='omx', name=name, path=str(tmp_path / f'set{index}')))
    server = make_server(store, free_port())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport=dict(width=width, height=height))
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            try:
                page.goto(f'http://127.0.0.1:{server.server_port}/learning/omx', wait_until='networkidle')
                playwright.expect(page.locator('#omx-status')).to_have_text('세트 4개')
                page.locator('#omx-sections a[href="#dataset-section"]').click()
                page.evaluate("document.querySelectorAll('details.omx-source-info').forEach(d=>d.open=true)")
                section = {name: page.locator('#sets > section').filter(has=page.locator('h3', has_text=name)) for name in sets}
                natives = section['Native set'].locator('.omx-native-reference')
                playwright.expect(natives.first).to_be_visible()
                playwright.expect(natives).to_have_text([f'top: {MATCH} · 기준 {"c" * 12}', f'wrist: {MATCH} · 기준 {"d" * 12}'])
                # Only the revision the camera-setup store holds is linked, and only to the same-site still.
                assert natives.locator('a').evaluate_all('a=>a.map(x=>x.getAttribute("href"))') == [
                    f'/api/learning/camera/stills/{"c" * 64}']
                playwright.expect(section['Native set'].locator('.omx-shadow-reference')).to_have_count(0)
                playwright.expect(section['Both set'].locator('.omx-native-reference')).to_have_count(1)
                playwright.expect(section['Both set'].locator('.omx-shadow-reference')).to_contain_text('섀도 증거')
                playwright.expect(section['Shadow set'].locator('.omx-native-reference')).to_have_count(0)
                playwright.expect(section['Shadow set'].locator('.omx-shadow-reference')).to_contain_text('섀도 증거')
                for name in ('Native set', 'Both set', 'Shadow set'):
                    playwright.expect(section[name].get_by_text(NONE)).to_have_count(0)
                playwright.expect(section['Plain set'].get_by_text(NONE)).to_be_visible()
                assert str(tmp_path) not in page.content()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                assert errors == []
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
