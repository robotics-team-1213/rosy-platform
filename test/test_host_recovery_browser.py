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


def test_every_reported_pc_shows_its_update_channels_and_a_viewer_sees_only_the_summary(console_url):
    # D-871: a fourth PC (one control PC per OMX cell) and update rows; reasons only for operators
    from playwright.sync_api import sync_playwright, expect

    now = time.time()
    report = {"schema": "rosy.update-report/1", "time": int(now), "gate": "frozen", "updaters": [
        {"unit": "rosy-omx-devices-autoupdate.service", "timer": "enabled", "healthy_at": now - 60,
         "last": {"step": "deferred", "release": "d0d7f7367b4d", "reason": "follower_torque_not_off", "at": now}},
        {"unit": "rosy-learning-center-update.service", "timer": "disabled", "healthy_at": None, "last": None}]}
    hosts = {"hosts": [{"host": name, "units": []} for name in ("site", "ai", "model")],
             "drift": None, "guard": {"cell-b": {"time": int(now), "state": "ok", "updates": report},
                                      "robot-a": {"time": int(now), "state": "ok"}}}
    summary = {"hosts": [{"host": "cell-b", "state": "frozen", "gate": "frozen", "channels": [
        {"unit": "rosy-omx-devices-autoupdate.service", "state": "ok", "release": "d0d7f7367b4d", "at": now}]}]}
    with sync_playwright() as p:
        browser, page, errors = _open_console(p, API)
        page.goto(console_url, wait_until="networkidle")
        page.evaluate("""async ([hosts, summary]) => {
            const {createHostServices} = await import('/console/assets/host-services.js');
            for (const [id, role] of [['as-operator', 'operator'], ['as-viewer', 'viewer']]) {
                const root = document.createElement('section');
                root.id = id;
                root.innerHTML = '<p id="host-services-status"></p><div id="host-services-report"></div>' +
                    '<div id="host-services-commands"></div><p id="host-services-note"></p>';
                document.body.append(root);
                const call = async path => {
                    if (path === '/api/fleet/hosts' && role === 'viewer') {
                        throw Object.assign(new Error('forbidden'), {status: 403});
                    }
                    return path === '/api/fleet/updates' ? summary : hosts;
                };
                await createHostServices({root, call, confirmIrreversible: async () => false}).refresh();
            }
        }""", [hosts, summary])
        operator = page.locator("#as-operator #host-services-report")
        cell = operator.locator('[data-host="cell-b"]')
        expect(cell).to_contain_text("업데이트 동결")
        expect(cell).to_contain_text("omx-devices · 정상 · d0d7f7367b4d · deferred (follower_torque_not_off)")
        expect(cell).to_contain_text("learning-center · 꺼짐")
        expect(operator).to_contain_text("PC 4대")
        expect(operator.locator('[data-host="robot-a"]')).to_have_count(0)  # robots are not PCs
        viewer = page.locator("#as-viewer #host-services-report")
        expect(viewer.locator('[data-host="cell-b"]')).to_contain_text("omx-devices · 정상 · d0d7f7367b4d")
        expect(viewer).not_to_contain_text("follower_torque_not_off")
        assert not errors
        browser.close()
