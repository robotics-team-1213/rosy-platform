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
                                 "teleop", "--direction", "forward", "--seconds", "2.1"])
    assert code == 2
    assert "--seconds" in capsys.readouterr().err


def test_stationary_encoder_noise_does_not_report_motion():
    assert dashboard_drive._moving({"velocity": {"linear": 0.0006, "angular": 0.0135}}) is False
    assert dashboard_drive._moving({"velocity": {"linear": 0.02, "angular": 0.0}}) is True
    assert dashboard_drive._moving({"velocity": {"linear": 0.0, "angular": 0.08}}) is True


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
        launched.goto("http://rosy.test/dashboard#compatibility", wait_until="load")
        launched.wait_for_function("document.getElementById('robot-mode')?.textContent === '수동'")
        yield launched
        browser.close()


def test_status_reads_the_apis_with_the_injected_token(page):
    assert page.evaluate("sessionStorage.getItem('rosy.dashboard.token')") == "agent-token"
    result = dashboard_drive.status(page)
    assert result["robot_mode_shown"] == "수동"
    assert result["/api/v1/robot/state"]["body"]["mode"] == "MANUAL"
    assert result["/api/v1/safety/state"]["status"] == 200
    assert result["/api/v1/host/hardware"]["body"]["available"] is False
    json.dumps(result)


def test_mode_accepts_the_confirm_and_reports_whether_the_robot_followed(page, monkeypatch):
    # The shipped dialog must gate the request, and its actual Cancel control
    # must leave the fixture robot untouched before the tool requests a mode.
    page.locator('.mode-control [data-mode="IDLE"]').click()
    confirmation = page.locator("dialog.ui-confirm[open]")
    confirmation.wait_for(state="visible")
    assert page.evaluate("window.__apiCalls.filter((c) => c.path === '/api/v1/mode')") == []
    with pytest.raises(RuntimeError, match="existing confirmation"):
        dashboard_drive.set_mode(page, "IDLE", timeout_s=0.5)
    confirmation.locator('ui-button[kind="quiet"]').click()
    confirmation.wait_for(state="hidden")
    assert page.evaluate("window.__apiCalls.filter((c) => c.path === '/api/v1/mode')") == []
    missed = dashboard_drive.set_mode(page, "IDLE", timeout_s=0.5)
    calls = page.evaluate("window.__apiCalls.filter((c) => c.path === '/api/v1/mode')")
    assert calls and calls[-1]["body"] == {"mode": "IDLE"}
    assert missed == {"requested": "IDLE", "mode": "MANUAL", "reached": False}
    page.evaluate("window.__rosyStateOverrides = {robot_state: {mode: 'IDLE'}}; null")
    assert dashboard_drive.set_mode(page, "IDLE", timeout_s=2.0)["reached"] is True
    # Replace the mode dialog when its prompt is inspected. A live locator
    # would approve the replacement's unrelated command; an owned element
    # must fail closed even though the replacement uses the same CSS classes.
    before = len(page.evaluate("window.__apiCalls.filter((c) => c.path === '/api/v1/mode')"))
    from playwright.sync_api import ElementHandle
    original_read = ElementHandle.inner_text
    page.evaluate("window.__unrelatedApprovals = 0")

    def replace_after_inspection(element, *args, **kwargs):
        text = original_read(element, *args, **kwargs)
        if element.evaluate("el => el.matches('dialog.ui-confirm[open] > p')"):
            # Schedule a real DOM replacement at the inspection boundary,
            # without substituting any result or invoking application handlers.
            page.evaluate("""() => {
          const dialog = document.querySelector('dialog.ui-confirm[open]');
          dialog.close('cancel'); dialog.remove();
          const other = document.createElement('dialog'); other.className = 'ui-confirm';
          const description = document.createElement('p'); description.textContent = 'Unrelated action';
          const action = document.createElement('ui-button'); action.setAttribute('kind', 'irreversible'); action.textContent = 'Unrelated action';
          action.addEventListener('click', () => {
            window.__unrelatedApprovals += 1;
            fetch('/api/v1/mode', {method: 'POST', body: JSON.stringify({mode: 'NAVIGATION'})});
          });
          other.append(description, action); document.body.append(other); other.show();
            }""")
        return text

    monkeypatch.setattr(ElementHandle, "inner_text", replace_after_inspection)
    with pytest.raises(RuntimeError, match="closed or replaced"):
        dashboard_drive.set_mode(page, "MANUAL", timeout_s=0.5)
    assert page.evaluate("window.__unrelatedApprovals") == 0
    assert len(page.evaluate("window.__apiCalls.filter((c) => c.path === '/api/v1/mode')")) == before


def test_teleop_holds_then_releases_to_zero(page):
    result = dashboard_drive.teleop(page, "forward", 0.8)
    page.wait_for_function("window.__teleopCommands.length >= 2")
    commands = page.evaluate("window.__teleopCommands")
    assert commands[0] == {"linear": 0.03, "angular": 0}
    assert commands[-1] == {"linear": 0, "angular": 0}
    assert result["samples"] and result["stop_latency_s"] is not None
    assert page.locator("#bench-safety-confirmed").count() == 0


def test_screenshot_of_the_inspect_view(page, tmp_path):
    out = dashboard_drive.screenshot(page, tmp_path / "inspect.png", "inspect")
    assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert page.locator("#hardware-card").is_visible()
