import pytest
from browser_harness import browser_tests_enabled
from console_browser_site import console_url  # noqa: F401
from test_fleet_console_browser import MAP_GRID, SNAPSHOT, _open_console

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="probe")


def test_probe(console_url):
    from playwright.sync_api import sync_playwright
    api = {"/api/fleet/state": SNAPSHOT, "/api/fleet/map": MAP_GRID, "/api/fleet/formation": {"active": False, "state": "IDLE"}}
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, api)
        page.set_viewport_size({"width": 320, "height": 844})
        page.goto(console_url, wait_until="networkidle")
        page.locator("#roster article").first.wait_for()
        page.locator('#robot-choice').select_option('rosy_01')
        page.locator('#robot-workspace article').wait_for()
        out = page.evaluate("""() => { const ws = document.getElementById('robot-workspace'); const rows = []; 
          const all = [...document.querySelectorAll('body *')].filter(n => { const r = n.getBoundingClientRect(); return r.height > 0 && r.bottom <= ws.getBoundingClientRect().top + 1 && r.height < 400 && !n.querySelector('*:not(option)') });
          for (const n of all) { const r = n.getBoundingClientRect(); rows.push([Math.round(r.top), Math.round(r.height), n.tagName.toLowerCase() + (n.id ? '#' + n.id : '') + '.' + String(n.className).slice(0, 30), (n.textContent || '').trim().slice(0, 24)]); }
          rows.sort((a, b) => a[0] - b[0]); return rows.map(r => r.join('|')).join('\n') }""")
        browser.close()
        assert False, "PROBE\n" + out
