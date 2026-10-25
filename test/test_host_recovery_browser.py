"""Per-PC recovery monitoring uses live evidence and never treats stale data as healthy."""
import copy
import time

import pytest
from browser_harness import browser_tests_enabled
from test_fleet_console_browser import API, _open_console, console_url  # noqa: F401

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="optional Chromium regression")


@pytest.mark.parametrize("width", [390, 1366])
def test_each_pc_has_its_own_recovery_report_and_stale_data_is_not_healthy(console_url, width):
    from playwright.sync_api import sync_playwright, expect

    now = int(time.time())
    recovery = {
        "time": now, "state": "ok", "issues": [],
        "watchdog": {"state": "ok", "timeout_s": 30},
        "kernel": {"state": "ok", "panic_s": 10, "softlockup_panic": 1},
        "ssh": {"state": "ok"},
        "swap": {"state": "ok", "total_bytes": 32 * 1024**3, "used_bytes": 0},
        "resources": {"avail_pct": 72, "swap_pct": 0, "load": 1.2, "cores": 8, "uptime_s": 900},
    }
    stale = copy.deepcopy(recovery)
    stale["time"] = now - 7200
    body = {
        "hosts": [{"host": name, "units": []} for name in ("site", "ai", "model")],
        "drift": {"time": now, "recovery": recovery},
        "guard": {
            "ai": {"time": now, "state": "ok", "recovery": stale},
            "model": {"time": now, "state": "unreachable", "recovery": None},
        },
    }
    with sync_playwright() as p:
        browser, page, errors = _open_console(p, API)
        page.set_viewport_size({"width": width, "height": 844})
        page.goto(console_url, wait_until="networkidle")
        page.evaluate("""async body => {
            const {createHostServices} = await import('/console/assets/host-services.js');
            const root = document.createElement('section');
            root.id = 'recovery-test';
            root.innerHTML = '<p id="host-services-status"></p><div id="host-services-report"></div>' +
                '<div id="host-services-commands"></div><p id="host-services-note"></p>';
            document.body.append(root);
            let response = body;
            const view = createHostServices({root, call: async () => {
                if (response === null) throw new Error('offline');
                return response;
            },
                confirmIrreversible: async () => false});
            await view.refresh();
            window.updateRecoveryTest = async next => {response = next; await view.refresh();};
        }""", body)
        report = page.locator("#recovery-test #host-services-report")
        site = report.locator('[data-host="site"]')
        expect(site).to_contain_text("관제 PC")
        expect(site).to_contain_text("워치독")
        expect(site).to_contain_text("30초")
        expect(site).to_contain_text("32.0 GiB")
        expect(report.locator('[data-host="ai"]')).to_contain_text("점검 지연")
        expect(report.locator('[data-host="model"]')).to_contain_text("응답 없음")
        malformed = copy.deepcopy(body)
        malformed["guard"]["ai"] = {"time": now, "state": "ok", "recovery": {"time": now, "state": "ok"}}
        page.evaluate("body => window.updateRecoveryTest(body)", malformed)
        expect(report.locator('[data-host="ai"]')).to_contain_text("복구 설정 확인 필요")
        page.evaluate("window.updateRecoveryTest(null).catch(() => {})")
        expect(report).to_contain_text("연결 실패")
        expect(report.locator('[data-state="ok"]')).to_have_count(0)
        assert not errors
        browser.close()


def test_a_lab_pc_offers_storage_cleaning_and_shows_its_headroom(console_url):
    """D-883: the button sends the confirmed Service Control action; the site gets no button."""
    from playwright.sync_api import sync_playwright, expect

    now = int(time.time())
    resources = {"avail_pct": 8, "swap_pct": 0, "load": 1.2, "cores": 24, "uptime_s": 900, "down": [],
                 "disk": {"test_free_gb": 2.6, "test_use_pct": 100, "root_free_gb": 2.6, "root_use_pct": 100},
                 "disk_low": True, "gpu": {"used_mib": 10248, "total_mib": 16303, "util_pct": 3, "temp_c": 42},
                 "memory": {"total_gb": 30.8, "avail_gb": 2.5}, "memory_low": True,
                 "cpu": {"busy_pct": 12, "temp_c": 56}}
    body = {
        "hosts": [{"host": "site", "actions": ["reboot", "cancel-reboot", "restart-unit"], "units": []},
                  {"host": "ai", "actions": ["reboot", "cancel-reboot", "clean-storage"], "units": []}],
        "guard": {"ai": {"time": now, "state": "disk-low", "resources": resources, "recovery": {
            "time": now, "state": "ok", "issues": [], "watchdog": {"state": "ok", "timeout_s": 30},
            "kernel": {"state": "ok", "panic_s": 10, "softlockup_panic": 1}, "ssh": {"state": "ok"},
            "swap": {"state": "ok", "total_bytes": 0, "used_bytes": 0}}}},
    }
    with sync_playwright() as p:
        browser, page, errors = _open_console(p, API)
        page.goto(console_url, wait_until="networkidle")
        page.evaluate("""async body => {
            const {createHostServices} = await import('/console/assets/host-services.js');
            const root = document.createElement('section');
            root.id = 'clean-test';
            root.innerHTML = '<p id="host-services-status"></p><div id="host-services-report"></div>' +
                '<div id="host-services-commands"></div><p id="host-services-note"></p>';
            document.body.append(root);
            window.cleanCalls = [];
            window.cleanPrompts = [];
            const view = createHostServices({root, call: async (url, options) => {
                if (options) { window.cleanCalls.push({url, ...options}); return {code: 'ACCEPTED'}; }
                return body;
            }, confirmIrreversible: async prompt => { window.cleanPrompts.push(prompt.message); return true; }});
            await view.refresh();
        }""", body)
        root = page.locator("#clean-test")
        ai = root.locator('#host-services-report [data-host="ai"]')
        expect(ai).to_contain_text("디스크 부족")
        expect(ai).to_contain_text("시험 디스크 여유 2.6GB(100%)")
        expect(ai).to_contain_text("메모리 여유 2.5/30.8GB(8%)")
        expect(ai).to_contain_text("CPU 온도 56°C")
        buttons = root.locator("#host-services-commands ui-button", has_text="시험 저장소 정리")
        expect(buttons).to_have_count(1)  # the site PC has no such action in its catalogue
        buttons.first.click()
        expect(root.locator("#host-services-note")).to_contain_text("clean-storage 접수 (ACCEPTED)")
        calls = page.evaluate("window.cleanCalls")
        assert calls == [{"url": "/api/fleet/hosts/ai/control", "method": "POST",
                          "body": {"action": "clean-storage", "unit": None, "operator_confirmed": True}}]
        assert "모델·데이터·사용 중 환경은 지우지 않으며" in page.evaluate("window.cleanPrompts[0]")
        assert not errors
        browser.close()
