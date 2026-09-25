"""tools/dashboard_drive.py against the dashboard browser-test fixtures (no robot).

The page is the local tree's dashboard with the mocked API of
test_dashboard_browser.py. Skips when Playwright or its Chromium is missing.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import dashboard_drive  # noqa: E402


def test_token_init_script_quotes_the_token():
    script = dashboard_drive.token_init_script("a'b\"c")
    assert script == "sessionStorage.setItem(\"rosy.dashboard.token\", \"a'b\\\"c\");"


def test_parser_requires_a_direction_and_bounds_the_hold(tmp_path, capsys):
    parser = dashboard_drive.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--base-url", "http://x", "--token-file", "t", "teleop", "--seconds", "1"])
    token = tmp_path / "token"
    token.write_text("t\n", encoding="utf-8")
    code = dashboard_drive.main(["--base-url", "http://x", "--token-file", str(token),
                                 "teleop", "--direction", "forward", "--seconds", "9"])
    assert code == 2
    assert "--seconds" in capsys.readouterr().err


@pytest.fixture
def page():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright
    from test_dashboard_browser import _launch_page

    with sync_playwright() as playwright:
        try:
            browser, launched = _launch_page(
                playwright, extra_init=dashboard_drive.token_init_script("agent-token"),
                width=1366, height=900)
        except Exception as error:  # Chromium not installed
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        launched.goto("http://rosy.test/dashboard", wait_until="load")
        launched.wait_for_function("document.getElementById('robot-mode')?.textContent === 'MANUAL'")
        yield launched
        browser.close()


def test_status_reads_the_apis_with_the_injected_token(page):
    assert page.evaluate("sessionStorage.getItem('rosy.dashboard.token')") == "agent-token"
    result = dashboard_drive.status(page)
    assert result["robot_mode_shown"] == "MANUAL"
    assert result["/api/v1/robot/state"]["body"]["mode"] == "MANUAL"
    assert result["/api/v1/safety/state"]["status"] == 200
    assert result["/api/v1/host/hardware"]["body"]["available"] is False
    json.dumps(result)


def test_mode_accepts_the_confirm_and_reports_whether_the_robot_followed(page):
    missed = dashboard_drive.set_mode(page, "IDLE", timeout_s=0.5)
    calls = page.evaluate("window.__apiCalls.filter((c) => c.path === '/api/v1/mode')")
    assert calls and calls[-1]["body"] == {"mode": "IDLE"}
    assert missed == {"requested": "IDLE", "mode": "MANUAL", "reached": False}
    page.evaluate("window.__rosyStateOverrides = {robot_state: {mode: 'IDLE'}}; null")
    assert dashboard_drive.set_mode(page, "IDLE", timeout_s=2.0)["reached"] is True


def test_teleop_holds_then_releases_to_zero(page):
    result = dashboard_drive.teleop(page, "forward", 0.8)
    page.wait_for_function("window.__teleopCommands.length >= 2")
    commands = page.evaluate("window.__teleopCommands")
    assert commands[0] == {"linear": 0.05, "angular": 0}
    assert commands[-1] == {"linear": 0, "angular": 0}
    assert result["samples"] and result["stop_latency_s"] is not None
    assert page.locator("#bench-safety-confirmed").is_checked()


def test_screenshot_of_the_inspect_view(page, tmp_path):
    out = dashboard_drive.screenshot(page, tmp_path / "inspect.png", "inspect")
    assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert page.locator("#hardware-card").is_visible()
