"""Device procedure feedback stays visible beside its action."""

from __future__ import annotations

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest
from browser_harness import browser_tests_enabled, free_port
from playwright.sync_api import expect, sync_playwright


REPO = Path(__file__).resolve().parents[4]
pytestmark = pytest.mark.skipif(
    not browser_tests_enabled(),
    reason="set ROSY_RUN_BROWSER_TESTS=1 to run the optional Chromium regression",
)


class _Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(REPO), **kwargs)

    def translate_path(self, path):
        # The dashboard serves web_common under /common/ (operations.js imports the label maps).
        if path.startswith("/common/"):
            path = "/shared/web/" + path[len("/common/"):]
        return super().translate_path(path)

    def log_message(self, _format, *_args):
        pass


def test_network_action_reports_rejection_and_success_beside_controls():
    server = ThreadingHTTPServer(("127.0.0.1", free_port()), _Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 390, "height": 844})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{server.server_port}/")
            page.evaluate("""async () => {
              await import('/common/ui.js');
              const {mount} = await import('/middleware/ui/robot/panels/host/operations.js');
              const root = document.createElement('main'); document.body.append(root);
              const callbacks = {};
              window.__callbacks = callbacks;
              const store = {poll(path, _interval, onData, onError) {
                callbacks[path] = {onData, onError}; return () => {};
              }};
              window.__result = {available: true, ok: false, detail: '프로파일이 거부되었습니다.'};
              window.__calls = [];
              window.__unmount = mount(root, {role:'administrator', store,
                api: async (path, options) => {
                  window.__calls.push({path, method: options.method}); return window.__result;
                }});
              callbacks['/api/v1/host/network'].onData({available:true,ok:true,
                evidence:{evidence:'fresh',age_s:0},data:{mode:'SITE_STA'}});
              window.confirm = () => true;
              root.querySelector('input[aria-label="네트워크 프로파일 ID"]').value = 'site-a';
            }""")
            advanced = page.locator("details").filter(has=page.get_by_text("고급 네트워크 작업", exact=True))
            assert advanced.get_attribute("open") is None
            expect(page.get_by_text("Wi-Fi 이름 (SSID)", exact=True)).to_be_visible()
            expect(page.get_by_text("Wi-Fi 암호 (8~63자)", exact=True)).to_be_visible()
            page.get_by_role("textbox", name="Wi-Fi SSID", exact=True).fill("site")
            expect(page.get_by_text("Wi-Fi 이름 (SSID)", exact=True)).to_be_visible()
            expect(page.get_by_text("프로파일 적용", exact=True)).to_be_hidden()
            expect(page.get_by_text("Wi-Fi 연결", exact=True)).to_be_visible()
            page.get_by_text("고급 네트워크 작업", exact=True).click()
            page.locator("form").filter(has=page.locator('input[aria-label="네트워크 프로파일 ID"]')).evaluate(
                "form => form.dispatchEvent(new Event('submit', {bubbles:true,cancelable:true}))"
            )
            page.locator("dialog.ui-confirm ui-button[kind=irreversible]").click()
            network = page.locator("section.ui-readback").filter(has_text="네트워크").first
            result = network.locator(".ui-readback > ui-status").last
            expect(result).to_contain_text("프로파일이 거부되었습니다")
            assert result.is_visible()
            assert page.evaluate("window.__calls.length") == 1

            page.evaluate("window.__result = {available:true,ok:true}")
            page.locator("form").filter(has=page.locator('input[aria-label="네트워크 프로파일 ID"]')).evaluate(
                "form => form.dispatchEvent(new Event('submit', {bubbles:true,cancelable:true}))"
            )
            page.locator("dialog.ui-confirm ui-button[kind=irreversible]").click()
            expect(result).to_contain_text("프로파일 적용을 요청했습니다")
            assert result.is_visible()
            assert page.evaluate("window.__calls.length") == 2

            page.evaluate("""() => {
              window.__result = {available:true,ok:false,detail:'이전 릴리스가 거부되었습니다.'};
              window.__callbacks['/api/v1/host/release'].onData({
                available:true,ok:true,evidence:{evidence:'fresh',age_s:0},data:{state:'IDLE',previous:'r1'}
              });
            }""")
            page.get_by_text("이전 릴리스로 복귀", exact=True).click()
            page.locator("dialog.ui-confirm ui-button[kind=irreversible]").click()
            release = page.locator("section.ui-readback").filter(has_text="릴리스").first
            release_result = release.locator("ui-status").nth(2)
            expect(release_result).to_contain_text("이전 릴리스가 거부되었습니다")
            assert release_result.is_visible()

            page.evaluate("""() => {
              window.confirm = () => false;
              document.querySelector('input[aria-label="Wi-Fi SSID"]').value = 'site';
              document.querySelector('input[aria-label="Wi-Fi 암호"]').value = 'password123';
            }""")
            page.locator("form").filter(has=page.locator('input[aria-label="Wi-Fi SSID"]')).evaluate(
                "form => form.dispatchEvent(new Event('submit', {bubbles:true,cancelable:true}))"
            )
            page.locator("dialog.ui-confirm ui-button[kind=quiet]").click()
            page.wait_for_timeout(100)
            assert page.evaluate("window.__calls.length") == 3
            assert errors == []
            page.evaluate("window.__unmount()")
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_host_actions_stay_locked_during_request_and_status_poll():
    server = ThreadingHTTPServer(("127.0.0.1", free_port()), _Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{server.server_port}/")
            page.evaluate("""async () => {
              await import('/common/ui.js');
              const {mount} = await import('/middleware/ui/robot/panels/host/operations.js');
              const root = document.createElement('main'); document.body.append(root);
              const callbacks = {}; window.__callbacks = callbacks;
              const store = {poll(path, _interval, onData, onError) {
                callbacks[path] = {onData, onError}; return () => {};
              }};
              window.__calls = []; window.__resolve = null;
              window.__unmount = mount(root, {role:'administrator', store,
                api: async (path, options) => {
                  window.__calls.push({path, method: options.method});
                  return await new Promise(resolve => {window.__resolve = resolve;});
                }});
              window.confirm = () => true;
              callbacks['/api/v1/host/network'].onData({available:true,ok:true,
                evidence:{evidence:'fresh',age_s:0},data:{mode:'SITE_STA'}});
              callbacks['/api/v1/host/release'].onData({available:true,ok:true,
                evidence:{evidence:'fresh',age_s:0},data:{state:'IDLE',previous:'r1'}});
            }""")
            page.get_by_text("고급 네트워크 작업", exact=True).click()
            page.get_by_text("사업장 Wi-Fi로 전환", exact=True).click()
            page.locator("dialog.ui-confirm ui-button[kind=irreversible]").click()
            page.evaluate("""() => {
              window.__callbacks['/api/v1/host/network'].onData({available:true,ok:true,
                evidence:{evidence:'fresh',age_s:0},data:{mode:'SITE_STA'}});
              [...document.querySelectorAll('ui-button')].find(x => x.textContent === '릴레이 AP 켜기').click();
            }""")
            assert page.evaluate("window.__calls.length") == 1
            assert page.evaluate("[...document.querySelectorAll('ui-button')].filter(x => ['사업장 Wi-Fi로 전환','릴레이 AP 켜기'].includes(x.textContent)).every(x => x.disabled)")
            page.evaluate("window.__resolve({available:true,ok:true})")
            page.wait_for_function("[...document.querySelectorAll('ui-button')].find(x => x.textContent === '릴레이 AP 켜기').disabled === false")

            page.get_by_text("이전 릴리스로 복귀", exact=True).click()
            page.locator("dialog.ui-confirm ui-button[kind=irreversible]").click()
            page.evaluate("""() => {
              window.__callbacks['/api/v1/host/release'].onData({available:true,ok:true,
                evidence:{evidence:'fresh',age_s:0},data:{state:'IDLE',previous:'r1'}});
              [...document.querySelectorAll('ui-button')].find(x => x.textContent === '이전 릴리스로 복귀').click();
            }""")
            assert page.evaluate("window.__calls.length") == 2
            assert page.evaluate("[...document.querySelectorAll('ui-button')].find(x => x.textContent === '이전 릴리스로 복귀').disabled")
            page.evaluate("window.__resolve({available:true,ok:true})")
            page.wait_for_function("[...document.querySelectorAll('ui-button')].find(x => x.textContent === '이전 릴리스로 복귀').disabled === false")
            assert errors == []
            page.evaluate("window.__unmount()")
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_host_status_cards_render_only_server_evidence_and_block_untrusted_actions():
    server = ThreadingHTTPServer(("127.0.0.1", free_port()), _Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{server.server_port}/")
            page.evaluate("""async () => {
              await import('/common/ui.js');
              const {mount} = await import('/middleware/ui/robot/panels/host/operations.js');
              const root = document.createElement('main'); document.body.append(root);
              const callbacks = {}; window.__callbacks = callbacks;
              const store = {poll(path, _interval, onData, onError) {
                callbacks[path] = {onData, onError}; return () => {};
              }};
              window.__unmount = mount(root, {role:'administrator', store,
                api: async () => {throw new Error('write not expected');}});
            }""")
            cases = [
                ("fresh", {"available": True, "ok": True, "evidence": {"evidence": "fresh", "age_s": 0},
                           "data": {"mode": "SITE_STA", "state": "IDLE", "previous": "r1"}}, True, "상태를 확인"),
                ("delayed", {"available": True, "ok": True, "evidence": {"evidence": "delayed", "age_s": 22},
                             "data": {"mode": "SITE_STA", "state": "IDLE", "previous": "r1"}}, False, "지연"),
                ("disconnected", {"available": False, "code": "HOST_AGENT_TIMEOUT",
                                  "evidence": {"evidence": "disconnected"}, "data": None}, False, "연결 끊김"),
                ("unavailable", {"available": True, "ok": True,
                                 "evidence": {"evidence": "unavailable"}, "data": None}, False, "정보 없음"),
            ]
            for _, payload, enabled, label in cases:
                page.evaluate("""payload => {
                  window.__callbacks['/api/v1/host/network'].onData(payload);
                  window.__callbacks['/api/v1/host/release'].onData(payload);
                }""", payload)
                for section, button in ((0, "사업장 Wi-Fi로 전환"), (1, "이전 릴리스로 복귀")):
                    result = page.evaluate("""([section, button]) => {
                      const card = document.querySelectorAll('section.ui-readback')[section];
                      return {status: card.querySelector('ui-status').textContent,
                        actionNote: card.querySelector('[id^="host-network-note"], [id^="host-release-note"]').textContent,
                        disabled: [...card.querySelectorAll('ui-button')].find(x => x.textContent.startsWith(button)).disabled};
                    }""", [section, button])
                    assert label in result["status"], result
                    assert result["disabled"] is not enabled, result
                    if label == "지연":
                        assert "지연" in result["actionNote"], result
            page.evaluate("""() => {
              const fresh = {available:true, ok:true, detail:'old detail', recovery:'old recovery',
                evidence:{evidence:'fresh', age_s:0}, data:{mode:'SITE_STA',ssid:'old-ssid',state:'IDLE',previous:'old-release'}};
              window.__callbacks['/api/v1/host/network'].onData(fresh);
              window.__callbacks['/api/v1/host/release'].onData(fresh);
              window.__callbacks['/api/v1/host/network'].onError({status:503,message:'read failed'});
              window.__callbacks['/api/v1/host/release'].onError({status:403,message:'forbidden'});
            }""")
            for section in page.locator("section.ui-readback").all()[:2]:
                assert "old-" not in section.inner_text()
                assert "확인할 수 없음" in section.locator("dl").text_content()
                assert section.locator("details").first.get_attribute("open") is None
                assert section.locator("details.surface-disclosure").nth(1).is_hidden()
                assert section.locator("details.surface-disclosure").nth(2).is_hidden()
            assert "호스트 에이전트 연결을 확인" in page.locator("section.ui-readback").nth(0).inner_text()
            assert "관리자 권한을 확인" in page.locator("section.ui-readback").nth(1).inner_text()
            assert errors == []
            page.evaluate("window.__unmount()")
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
