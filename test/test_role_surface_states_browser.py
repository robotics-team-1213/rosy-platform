"""Regression coverage for role-aware map and Host Agent states (D-279)."""

from __future__ import annotations

from pathlib import Path

import pytest

from browser_harness import open_page


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src" / "hmi" / "dashboard"


def _module_page(playwright, modules: dict[str, Path], width: int = 390):
    browser, page, errors = open_page(playwright, width, 844)
    page.route(
        "http://rosy.test/panel-test",
        lambda route: route.fulfill(
            status=200,
            content_type="text/html",
            body="<!doctype html><html><head></head><body></body></html>",
        ),
    )
    for url, path in modules.items():
        page.route(
            f"http://rosy.test{url}",
            lambda route, _request, path=path: route.fulfill(
                status=200,
                content_type="application/javascript",
                body=path.read_text(encoding="utf-8"),
            ),
        )
    page.goto("http://rosy.test/panel-test", wait_until="domcontentloaded", timeout=5_000)
    return browser, page, errors


def test_shared_components_apply_button_size_palette_and_status_contracts():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    shared = ROOT / "src" / "hmi" / "web"
    with sync_playwright() as playwright:
        try:
            browser, page, errors = _module_page(playwright, {
                "/assets/ui.js": shared / "ui.js",
            })
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        page.add_style_tag(content=(shared / "tokens.css").read_text(encoding="utf-8"))
        page.add_style_tag(content=(shared / "components.css").read_text(encoding="utf-8"))
        page.evaluate("""async () => {
          await import('/assets/ui.js');
          const make = (kind, size) => {
            const button = document.createElement('ui-button');
            button.setAttribute('kind', kind);
            if (size) button.setAttribute('size', size);
            document.body.append(button);
            return button;
          };
          const secondary = make('quiet');
          const primary = make('quiet', 'primary');
          const irreversible = make('irreversible');
          const segment = make('segment');
          segment.setAttribute('aria-pressed', 'true');
          const status = document.createElement('ui-status');
          status.setAttribute('state', 'warning');
          status.textContent = 'Host Agent unavailable';
          document.body.append(status);
          const actions = document.createElement('ui-actions');
          document.body.append(actions);
          status.hidden = true;
          window.__sharedContract = {
            sizes: [secondary, primary, irreversible].map(node => getComputedStyle(node).minHeight),
            activeSegment: getComputedStyle(segment).backgroundColor,
            defaultRole: status.getAttribute('role'),
            live: status.getAttribute('aria-live'),
            state: status.dataset.state,
            hiddenDisplay: getComputedStyle(status).display,
            warningColor: getComputedStyle(status).color,
            actionDisplay: getComputedStyle(actions).display,
            scrollbar: getComputedStyle(document.documentElement).scrollbarColor,
          };
        }""")
        assert page.evaluate("window.__sharedContract") == {
            "sizes": ["44px", "48px", "58px"],
            "activeSegment": "rgb(53, 56, 60)",
            "defaultRole": "status",
            "live": "polite",
            "state": "warning",
            "hiddenDisplay": "none",
            "warningColor": "rgb(254, 180, 50)",
            "actionDisplay": "flex",
            "scrollbar": "rgb(53, 56, 60) rgb(16, 18, 20)",
        }
        assert errors == []
        browser.close()


def test_dashboard_api_preserves_structured_http_errors_and_network_failures():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        try:
            browser, page, errors = _module_page(playwright, {
                "/assets/client.js": WEB / "client.js",
                "/assets/dom.js": WEB / "dom.js",
            })
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")

        page.evaluate("""async () => {
          sessionStorage.setItem('rosy.dashboard.token', 'browser-test-token');
          const {api, apiMaybe} = await import('/assets/client.js');
          const originalFetch = window.fetch;
          const capture = async (response) => {
            window.fetch = async () => response;
            try { await api('/api/v1/map'); return null; }
            catch (error) { return {status: error.status ?? null, code: error.code ?? null, message: error.message}; }
          };
          window.__apiErrors = [];
          window.__apiErrors.push(await capture(new Response(
            JSON.stringify({error:{code:'NOT_FOUND',message:'map absent'}}),
            {status:404,headers:{'Content-Type':'application/json'}})));
          window.__apiErrors.push(await capture(new Response(
            JSON.stringify({error:{code:'FORBIDDEN',message:'role denied'}}),
            {status:403,headers:{'Content-Type':'application/json'}})));
          window.fetch = async () => { throw new TypeError('network disconnected'); };
          try { await api('/api/v1/map'); }
          catch (error) { window.__apiErrors.push({status:error.status ?? null,code:error.code ?? null,message:error.message}); }
          window.fetch = async () => new Response(
            JSON.stringify({error:{code:'NOT_FOUND',message:'map absent'}}),
            {status:404,headers:{'Content-Type':'application/json'}});
          window.__apiMaybe = await apiMaybe('/api/v1/map');
          window.fetch = async () => new Response(
            JSON.stringify({detail:'route absent'}),
            {status:404,headers:{'Content-Type':'application/json'}});
          try { await apiMaybe('/api/v1/unknown'); }
          catch (error) { window.__apiErrors.push({status:error.status ?? null,code:error.code ?? null,message:error.message}); }
          window.fetch = originalFetch;
        }""")

        assert page.evaluate("window.__apiErrors") == [
            {"status": 404, "code": "NOT_FOUND", "message": "map absent"},
            {"status": 403, "code": "FORBIDDEN", "message": "role denied"},
            {"status": None, "code": None, "message": "network disconnected"},
            {"status": 404, "code": None, "message": "route absent"},
        ]
        assert page.evaluate("window.__apiMaybe") is None
        assert errors == []
        browser.close()


def test_console_map_distinguishes_empty_forbidden_error_and_ready_by_role():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        try:
            browser, page, errors = _module_page(playwright, {
                "/assets/panels/console/map.js": WEB / "panels" / "console" / "map.js",
                "/assets/map.js": WEB / "map.js",
                "/assets/ui.js": ROOT / "src" / "hmi" / "web" / "ui.js",
            })
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")

        page.evaluate("""async () => {
          await import('/assets/ui.js');
          const {mount} = await import('/assets/panels/console/map.js');
          window.__mountMap = mount;
          const root = document.createElement('main'); document.body.append(root);
          const callbacks = {};
          window.__callbacks = callbacks;
          const store = {poll(path, _interval, onData, onError) {
            callbacks[path] = {onData, onError}; return () => {};
          }};
          window.__scenario = 'missing';
          window.__api = async (path) => {
            if (path === '/api/v1/map') {
                  if (window.__scenario === 'missing') throw Object.assign(new Error('no occupancy map received yet'), {status:404,code:'NOT_FOUND'});
                  if (window.__scenario === 'other404') throw Object.assign(new Error('route missing'), {status:404,code:'ROUTE_NOT_FOUND'});
              if (window.__scenario === 'forbidden') throw Object.assign(new Error('denied'), {status:403,code:'FORBIDDEN'});
              if (window.__scenario === 'error') throw new TypeError('network disconnected');
              return {map_id:'map-a',width:2,height:2,resolution:1,origin:{x:0,y:0},data:[0,0,0,0]};
            }
            return path.includes('/navigation/path') ? {poses:[]} : null;
          };
          window.__mapApi = window.__api;
          window.__mapStore = store;
          window.__refresh = null;
          window.setInterval = (fn) => { window.__refresh = fn; return 1; };
          window.__unmount = mount(root, {role:'viewer',surfaces:[{id:'console'}],api:window.__api,
            store});
          window.__loadingCopy = root.querySelector('[role="status"]').textContent;
          await window.__refresh();
        }""")

        assert page.evaluate("window.__loadingCopy") == "지도를 불러오는 중…"
        assert "지도 데이터가 아직 없습니다" in page.locator("ui-empty").inner_text()
        assert page.locator('a[href="/setup"]').is_visible() is False
        assert "지도가 아직 없습니다" in page.locator("#map-status").inner_text()
        assert page.locator("ui-status[state=pending]").evaluate("node => node.hidden")

        page.evaluate("window.__scenario = 'other404'; window.__refresh()")
        page.wait_for_function("document.querySelector('#map-status')?.textContent.includes('최신 지도')")
        assert page.locator("ui-empty").is_visible() is False

        page.evaluate("window.__scenario = 'forbidden'; window.__refresh()")
        page.wait_for_function("document.querySelector('#map-status')?.textContent.includes('권한')")
        assert page.locator('a[href="/setup"]').is_visible() is False

        page.evaluate("window.__scenario = 'error'; window.__refresh()")
        page.wait_for_function("document.querySelector('#map-status')?.textContent.includes('최신 지도')")
        assert page.locator("ui-empty").is_visible() is False

        page.evaluate("window.__scenario = 'ready'; window.__refresh()")
        page.wait_for_function("document.querySelector('#map-status')?.textContent.includes('2×2')")
        assert page.locator("ui-empty").evaluate("node => node.hidden")

        page.evaluate("window.__unmount()")
        assert errors == []
        browser.close()


def test_operator_sees_setup_recovery_only_when_manifest_allows_it():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        try:
            browser, page, errors = _module_page(playwright, {
                "/assets/panels/console/map.js": WEB / "panels" / "console" / "map.js",
                "/assets/map.js": WEB / "map.js",
                "/assets/ui.js": ROOT / "src" / "hmi" / "web" / "ui.js",
            })
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")

        page.evaluate("""async () => {
          await import('/assets/ui.js');
          const {mount} = await import('/assets/panels/console/map.js');
          const root = document.createElement('main'); document.body.append(root);
          const store = {poll() { return () => {}; }};
          const api = async (path) => {
            if (path === '/api/v1/map') throw Object.assign(new Error('map absent'), {status:404,code:'NOT_FOUND'});
            return path.includes('/navigation/path') ? {poses:[]} : null;
          };
          window.setInterval = (fn) => { window.__refresh = fn; return 1; };
          window.__unmount = mount(root, {role:'operator',surfaces:[{id:'console'},{id:'setup'}],api,store});
          window.__withoutSetup = async () => {
            window.__unmount();
            root.replaceChildren();
            window.__unmount = mount(root, {role:'operator',surfaces:[{id:'console'}],api,store});
            await window.__refresh();
          };
        }""")
        page.wait_for_function("document.querySelector('a[href=\"/setup\"]')?.hidden === false")
        assert page.locator('a[href="/setup"]').inner_text() == "작업 준비에서 지도 확인"
        page.evaluate("window.__withoutSetup()")
        assert page.locator('a[href="/setup"]').is_visible() is False
        assert errors == []
        page.evaluate("window.__unmount()")
        browser.close()


def test_host_agent_recovery_is_text_only_and_unavailable_controls_stay_blocked():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        try:
            browser, page, errors = _module_page(playwright, {
                "/assets/panels/host/operations.js": WEB / "panels" / "host" / "operations.js",
                "/assets/ui.js": ROOT / "src" / "hmi" / "web" / "ui.js",
            })
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")

        page.evaluate("""async () => {
          await import('/assets/ui.js');
          const {mount} = await import('/assets/panels/host/operations.js');
          const root = document.createElement('main'); document.body.append(root);
          const callbacks = {};
          window.__callbacks = callbacks;
          const store = {poll(path, _interval, onData, onError) {
            callbacks[path] = {onData,onError}; return () => {};
          }};
          window.__calls = [];
          window.__unmount = mount(root, {role:'administrator',api:async (path) => window.__calls.push(path),store});
          callbacks['/api/v1/host/network'].onData({available:false,code:'HOST_AGENT_UNAVAILABLE',
            detail:'cannot reach host agent on this development host',recovery:'Check rosy-host-agent.service <img src=x>'});
          callbacks['/api/v1/host/release'].onData({available:false,code:'HOST_AGENT_TIMEOUT',detail:'agent timed out'});
          window.confirm = () => true;
        }""")

        assert page.locator("details").filter(has_text="Check rosy-host-agent.service").count() == 1
        assert page.locator("details").filter(has_text="<img src=x>").count() == 1
        assert page.locator("img").count() == 0
        assert page.locator("ui-button").evaluate_all("nodes => nodes.every(node => node.disabled)")
        page.locator("ui-button").evaluate_all("nodes => nodes.forEach(node => node.click())")
        page.locator("form").evaluate_all("nodes => nodes.forEach(node => node.dispatchEvent(new Event('submit', {bubbles:true,cancelable:true})))")
        assert page.evaluate("window.__calls") == []

        page.evaluate("""() => {
          window.__callbacks['/api/v1/host/network'].onData({available:true,ok:true,data:{mode:'SITE_STA'}});
          window.__callbacks['/api/v1/host/release'].onData({available:true,ok:true,data:{previous:'r1'}});
        }""")
        assert page.locator("ui-button").evaluate_all("nodes => nodes.some(node => !node.disabled)")
        page.evaluate("""() => window.__callbacks['/api/v1/host/release'].onData({
          available:true,ok:false,code:'RECOVERY_HELD',detail:'release requires operator review',
          data:{previous:'r1'}
        })""")
        release_status = page.locator("section.surface-readback").filter(has_text="릴리스").locator("[role=status]").first
        assert "확인이 필요한 상태" in release_status.inner_text()
        assert page.locator("details").filter(has_text="release requires operator review").count() == 1

        page.evaluate("""() => {
          window.__callbacks['/api/v1/host/network'].onError({status:403,message:'role denied'});
        }""")
        assert "볼 권한이 없습니다" in page.locator("[role=status]").all_inner_texts()[0]
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.evaluate("window.__unmount()")
        assert errors == []
        browser.close()
