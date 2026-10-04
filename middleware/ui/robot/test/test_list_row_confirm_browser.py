"""D-371 on the real /device shell (FastAPI + Chromium, LOCAL evidence).

1. The first viewport holds at most one danger fill besides the E-stop.
2. The token row starts with a quiet `삭제…`; the confirm dialog names the
   token; Esc and cancel send nothing and give focus back to the row button;
   execute sends exactly one DELETE for that token.
3. The dialog is non-modal: the shell E-stop stays live (not inert, not under
   the scrim, in the Tab ring) and pressing it stops and cancels the delete.
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1",
    reason="set ROSY_RUN_BROWSER_TESTS=1 for LOCAL Chromium checks",
)

# Resolved colour of --status-crit and every element in the first viewport whose
# own background paints it, the shell E-stop (and its children) excluded.
DANGER_FILLS = """() => {
  const probe = document.createElement('span');
  probe.style.background = 'var(--status-crit)';
  document.body.append(probe);
  const crit = getComputedStyle(probe).backgroundColor;
  probe.remove();
  const stop = document.querySelector('#shell-estop');
  return [...document.querySelectorAll('body *')].filter((node) => {
    if (stop && (node === stop || stop.contains(node))) return false;
    if (getComputedStyle(node).backgroundColor !== crit) return false;
    const box = node.getBoundingClientRect();
    return box.width > 0 && box.height > 0 && box.bottom > 0 && box.top < innerHeight
      && box.right > 0 && box.left < innerWidth;
  }).map((node) => `${node.tagName}.${node.className}:${(node.textContent || '').trim().slice(0, 20)}`);
}"""


def _open_device(playwright, tmp_path, width, height, theme, deletes):
    from test_role_g2_browser import TOKENS, _core_client, _response

    client = _core_client(tmp_path)
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": width, "height": height})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.add_init_script(f"sessionStorage.setItem('rosy.dashboard.token', {TOKENS['administrator']!r});"
                         f"localStorage.setItem('rosy.theme', {theme!r});")

    def serve(route):
        request = route.request
        path = urlsplit(request.url).path
        if request.method != "GET":
            deletes.append((request.method, path))
            route.fulfill(status=200, content_type="application/json", body='{"deleted": true}')
            return
        response = _response(client, path, TOKENS["administrator"], "normal", "device")
        route.fulfill(status=response.status_code, headers={
            "content-type": response.headers.get("content-type", "application/octet-stream"),
            "cache-control": "no-store",
        }, body=response.content if hasattr(response, "content") else response.body)

    page.route("**/*", serve)
    page.goto("http://rosy.test/device", wait_until="domcontentloaded")
    page.wait_for_function("document.querySelectorAll('li[data-token-id] ui-button').length >= 2", timeout=15_000)
    page.wait_for_timeout(300)
    return browser, page, errors


@pytest.mark.parametrize("theme", ["dark", "light"])
@pytest.mark.parametrize("size", [(1366, 768), (390, 844)])
def test_device_first_viewport_spends_at_most_one_danger_fill_besides_the_estop(tmp_path, theme, size):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser, page, errors = _open_device(playwright, tmp_path, *size, theme, [])
        fills = page.evaluate(DANGER_FILLS)
        assert len(fills) <= 1, f"D-371 §3: 비상정지 외 위험 채움 {fills}"
        rows = page.locator("li[data-token-id] ui-button")
        assert rows.evaluate_all("nodes => nodes.every(n => n.getAttribute('kind') === 'quiet')")
        assert rows.evaluate_all("nodes => nodes.every(n => n.textContent.startsWith('삭제…'))")
        assert errors == []
        browser.close()


def test_device_token_delete_goes_through_a_dialog_that_names_the_token(tmp_path):
    from playwright.sync_api import sync_playwright
    from test_role_g2_browser import _select_task

    deletes = []
    with sync_playwright() as playwright:
        browser, page, errors = _open_device(playwright, tmp_path, 1366, 768, "dark", deletes)
        _select_task(page, "system.security")
        current = page.locator("li[data-token-id] ui-button[disabled]")
        assert current.count() == 1 and "지금 쓰는 토큰" in current.inner_text()

        row = page.locator("li[data-token-id]").filter(has=page.locator("ui-button:not([disabled])")).first
        token_id = row.get_attribute("data-token-id")
        name = row.locator("span").first.inner_text().split(" · ")[0]
        button = row.locator("ui-button")
        is_row_button_focused = (
            f"document.activeElement?.closest('li')?.dataset.tokenId === {token_id!r}"
            " && document.activeElement.tagName === 'UI-BUTTON'"
        )
        dialog = page.locator("dialog.ui-confirm")

        button.click()
        assert dialog.is_visible()
        assert f'"{name}"' in dialog.locator("p").inner_text()
        execute = dialog.locator("ui-button[kind=irreversible]")
        assert execute.count() == 1 and execute.inner_text() == "토큰 삭제"
        assert dialog.locator("ui-button[kind=quiet]").inner_text() == "취소"
        crit = page.evaluate("""() => { const p = document.createElement('span');
          p.style.background = 'var(--status-crit)'; document.body.append(p);
          const c = getComputedStyle(p).backgroundColor; p.remove(); return c; }""")
        assert execute.evaluate("n => getComputedStyle(n).backgroundColor") == crit
        page.keyboard.press("Escape")
        page.wait_for_function("!document.querySelector('dialog.ui-confirm')")
        assert page.evaluate(is_row_button_focused)

        row.locator("ui-button").click()
        dialog.locator("ui-button[kind=quiet]").click()
        page.wait_for_function("!document.querySelector('dialog.ui-confirm')")
        assert page.evaluate(is_row_button_focused)
        page.wait_for_timeout(100)
        assert deletes == []

        row.locator("ui-button").click()
        dialog.locator("ui-button[kind=irreversible]").click()
        page.wait_for_function("document.body.textContent.includes('토큰을 삭제했습니다')", timeout=5_000)
        assert deletes == [("DELETE", f"/api/v1/system/tokens/{token_id}")]
        assert errors == []
        browser.close()


# Every control a user could reach on the page, dialog and live stops aside.
STOP_STATE = """() => {
  const stop = document.querySelector('#shell-estop');
  const box = stop.getBoundingClientRect();
  const hit = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
  const outside = [...document.querySelectorAll('ui-button, button, a[href], input, select, nav')]
    .filter((n) => !n.closest('dialog.ui-confirm') && !n.closest('[data-always-live]'));
  return {
    stopInert: stop.closest('[inert]') !== null,
    hitIsStop: hit !== null && stop.contains(hit),
    live: outside.filter((n) => !n.closest('[inert]')).map((n) => n.outerHTML.slice(0, 80)),
    outside: outside.length,
  };
}"""


def test_device_estop_stays_live_over_the_delete_dialog(tmp_path):
    from playwright.sync_api import sync_playwright
    from test_role_g2_browser import _select_task

    requests = []
    with sync_playwright() as playwright:
        browser, page, errors = _open_device(playwright, tmp_path, 1366, 768, "dark", requests)
        _select_task(page, "system.security")
        row = page.locator("li[data-token-id]").filter(has=page.locator("ui-button:not([disabled])")).first
        dialog = page.locator("dialog.ui-confirm")
        stop = page.locator("#shell-estop")
        assert stop.get_attribute("data-always-live") is not None
        assert page.evaluate("document.querySelectorAll('[inert]').length") == 0

        row.locator("ui-button").click()
        assert dialog.is_visible()
        state = page.evaluate(STOP_STATE)
        assert not state["stopInert"], "D-280 원칙 2: 대화상자가 비상정지를 inert로 만들었다"
        assert state["hitIsStop"], "스크림이 비상정지를 덮었다"
        assert state["outside"] > 5 and state["live"] == [], f"대화상자 밖이 살아 있다: {state['live']}"

        # Polling re-renders while open: the robot state poll runs every second,
        # and a node appended later is sealed too.
        page.wait_for_timeout(1_500)
        page.evaluate("document.body.append(Object.assign(document.createElement('button'), {id: 'late'}))")
        page.wait_for_function("document.getElementById('late')?.closest('[inert]') !== null")
        state = page.evaluate(STOP_STATE)
        assert not state["stopInert"] and state["hitIsStop"] and state["live"] == []

        # Tab ring: cancel -> execute -> E-stop -> cancel; Shift+Tab walks back.
        focused = "document.activeElement?.id || document.activeElement?.textContent"
        assert page.evaluate(focused) == "취소"
        page.keyboard.press("Tab")
        assert page.evaluate(focused) == "토큰 삭제"
        page.keyboard.press("Tab")
        assert page.evaluate(focused) == "shell-estop"
        page.keyboard.press("Tab")
        assert page.evaluate(focused) == "취소"
        page.keyboard.press("Shift+Tab")
        assert page.evaluate(focused) == "shell-estop"

        stop.click()
        page.wait_for_function("!document.querySelector('dialog.ui-confirm')")
        page.wait_for_function("document.getElementById('shell-notice').textContent.includes('비상 정지')")
        assert ("POST", "/api/v1/safety/stop") in requests
        assert not any(method == "DELETE" for method, _ in requests)
        assert page.evaluate("[...document.querySelectorAll('[inert]')].filter((n) => n.id !== 'late').length") == 0
        assert page.evaluate("document.querySelector('.ui-confirm-scrim')") is None

        # The Esc path still cancels after the stop path.
        row.locator("ui-button").click()
        page.keyboard.press("Escape")
        page.wait_for_function("!document.querySelector('dialog.ui-confirm')")
        assert not any(method == "DELETE" for method, _ in requests)
        assert errors == []
        browser.close()
