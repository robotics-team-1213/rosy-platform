from __future__ import annotations

from test_fleet_console_browser import (
    os, json, Path, console_url, urlparse, pytest, pytestmark, open_page, save_temp_screenshot,
    MAP_GRID, _robot, SNAPSHOT, FORMATION, API, _open_cards, _open_token_access,
    _open_console, CAMERA_FINGERPRINT, _camera_api, _camera_shot,
)


WARM_TEXT_CONTRAST = """() => {
  const cs = getComputedStyle(document.documentElement);
  const ctx = document.createElement('canvas').getContext('2d');
  const norm = (v) => { ctx.fillStyle = v.trim(); return ctx.fillStyle; };
  const warm = new Set([norm(cs.getPropertyValue('--status-warn')),
                        norm(cs.getPropertyValue('--status-crit'))]);
  const effBg = (el) => {
    let node = el;
    while (node && node !== document.documentElement) {
      const s = getComputedStyle(node);
      const m = s.backgroundColor.match(/rgba?\\(([^)]+)\\)/);
      if (m && (m[1].split(',').length < 4 || Number(m[1].split(',')[3]) === 1)) {
        return norm(s.backgroundColor);
      }
      node = node.parentElement;
    }
    return norm(cs.getPropertyValue('--ground'));
  };
  const lum = (c) => {
    let r, g, b;
    if (c[0] === '#') {
      const h = c.length === 4 ? c.replace(/[^#]/g, (x) => x + x) : c;
      r = parseInt(h.slice(1, 3), 16); g = parseInt(h.slice(3, 5), 16);
      b = parseInt(h.slice(5, 7), 16);
    } else {
      const m = c.match(/rgba?\\(([^)]+)\\)/);
      if (!m) return null;
      [r, g, b] = m[1].split(',').map(Number);
    }
    const f = (v) => { v /= 255;
      return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  const offenders = [];
  for (const el of document.querySelectorAll('*')) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    if (!(el.textContent.trim() && el.children.length === 0)) continue;
    const s = getComputedStyle(el);
    const color = norm(s.color);
    if (!warm.has(color)) continue;
    const la = lum(color), lb = lum(effBg(el));
    if (la === null || lb === null) continue;
    const ratio = (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
    if (ratio < 4.5) {
      offenders.push(`${el.tagName.toLowerCase()}.${(el.className || '').toString()}"
        ${ratio.toFixed(2)}:1 "${el.textContent.trim().slice(0, 16)}"`);
    }
  }
  return offenders;
}"""


def test_warm_coloured_text_stays_readable(console_url):
    """D-202 — crit 글자(2.24:1) 같은 읽히지 않는 경보를 금지한다."""
    from playwright.sync_api import sync_playwright

    api = {
        "/api/fleet/state": SNAPSHOT,
        "/api/fleet/map": MAP_GRID,
        "/api/fleet/formation": FORMATION,
    }
    with sync_playwright() as p:
        browser, page, errors = _open_console(p, api)
        page.goto(console_url, wait_until="networkidle")
        page.wait_for_function(
            "() => (window.__swarmOverlay?.slots || 0) === 2", timeout=8000
        )
        offenders = page.evaluate(WARM_TEXT_CONTRAST)
        assert not errors
        browser.close()

    assert offenders == [], (
        "따뜻한 색 글자가 4.5:1 미만이다 — 위험은 채움이다(D-202): "
        + "; ".join(offenders[:6])
    )


# --- D-214: 텍스트 대비의 바닥 — 색이 아니라 청중의 계약 ---------------------

TEXT_CONTRAST_FLOOR = """() => {
  const ctx = document.createElement('canvas').getContext('2d');
  const effBg = (el) => {
    let node = el;
    while (node && node !== document.documentElement) {
      const s = getComputedStyle(node);
      const m = s.backgroundColor.match(/rgba?\\(([^)]+)\\)/);
      if (m && (m[1].split(',').length < 4 || Number(m[1].split(',')[3]) === 1)) {
        return s.backgroundColor;
      }
      node = node.parentElement;
    }
    return getComputedStyle(document.documentElement).getPropertyValue('--ground');
  };
  const lum = (c) => {
    let r, g, b;
    if (c[0] === '#') {
      const h = c.length === 4 ? c.replace(/[^#]/g, (x) => x + x) : c;
      r = parseInt(h.slice(1, 3), 16); g = parseInt(h.slice(3, 5), 16);
      b = parseInt(h.slice(5, 7), 16);
    } else {
      const m = c.match(/rgba?\\(([^)]+)\\)/);
      if (!m) return null;
      [r, g, b] = m[1].split(',').map(Number);
    }
    const f = (v) => { v /= 255;
      return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  const offenders = [];
  for (const el of document.querySelectorAll('*')) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    if (!(el.textContent.trim() && el.children.length === 0)) continue;
    const s = getComputedStyle(el);
    const la = lum(s.color), lb = lum(effBg(el));
    if (la === null || lb === null) continue;
    const ratio = (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
    // 24px 이상의 디스플레이 값은 크기가 대비를 보상한다(D-214).
    const floor = parseFloat(s.fontSize) >= 24 ? 3.0 : 4.5;
    if (ratio < floor) {
      offenders.push(`${el.tagName.toLowerCase()}.${(el.className || '').toString()}`
        + ` ${ratio.toFixed(2)}:1 <${floor} "${el.textContent.trim().slice(0, 14)}"`);
    }
  }
  return offenders;
}"""


def test_visible_text_meets_the_contrast_floor(console_url):
    """D-214 — 보이는 모든 글자는 4.5:1(큰 값 3.0:1) 바닥 위에 있다.

    선택된 로봇 카드의 muted 라벨(4.11:1)이 이 게이트의 첫 적발이다.
    """
    from playwright.sync_api import sync_playwright

    api = {
        "/api/fleet/state": SNAPSHOT,
        "/api/fleet/map": MAP_GRID,
        "/api/fleet/formation": FORMATION,
    }
    with sync_playwright() as p:
        browser, page, errors = _open_console(p, api)
        page.goto(console_url, wait_until="networkidle")
        page.wait_for_function(
            "() => (window.__swarmOverlay?.slots || 0) === 2", timeout=8000
        )
        # 로스터의 선택 상태를 만든다 — 바닥 붕괴는 선택 카드에서 났다.
        # 선택은 카드가 아니라 '목표 지정' 버튼으로 일어난다(console.js).
        _open_cards(page)
        page.locator("#robot-workspace article ui-button", has_text="목표 지정").first.click()
        # 경합 하에서 기본 5초를 넘기는 것은 대기의 문제지 대비의 문제가 아니다
        # — 계약은 센서스가 지킨다(2026-09-25 재검증 노트의 플레이크와 같은 계열).
        page.wait_for_function(
            "() => document.querySelectorAll('.robot.selected').length === 1",
            timeout=20_000,
        )
        offenders = page.evaluate(TEXT_CONTRAST_FLOOR)
        assert not errors
        browser.close()

    assert offenders == [], (
        "바닥 아래 텍스트가 있다 — 선택도 읽기를 희생하지 않는다(D-214): "
        + "; ".join(offenders[:6])
    )


@pytest.mark.parametrize("width,height", [(1366, 768), (390, 844), (320, 568)])
def test_map_label_chips_never_cover_each_other(console_url, width, height):
    """D-359 US-008 capture: near rosy_03 the tracking-error chip ("0.88m") and the mediation
    chip ("경로 충돌") were drawn on the same spot and neither read. Chips step aside."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser, page, errors = _open_console(p, dict(API))
        page.set_viewport_size({"width": width, "height": height})
        page.goto(console_url, wait_until="networkidle")
        page.wait_for_function("() => (window.__swarmOverlay?.mediation || 0) >= 1"
                               " && (window.__mapChips || []).length >= 3", timeout=8000)
        chips = page.evaluate("() => window.__mapChips.map((r) => ({...r}))")
        assert not errors
        browser.close()

    texts = [chip["text"] for chip in chips]
    assert "경로 충돌" in texts and "0.88m" in texts, texts
    hits = [
        (a["text"], b["text"])
        for i, a in enumerate(chips) for b in chips[i + 1:]
        if a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"]
        and a["y"] < b["y"] + b["h"] and b["y"] < a["y"] + a["h"]
    ]
    assert hits == [], hits


def test_phone_map_raster_stays_close_to_display_size(console_url):
    """Downsampling a 400px map into a 236px phone box makes labels unreadable."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser, page, errors = _open_console(p, API)
        page.set_viewport_size({"width": 320, "height": 568})
        page.goto(console_url, wait_until="networkidle")
        ratio = page.evaluate("""() => {
          const canvas = document.getElementById('map-canvas');
          const box = canvas.getBoundingClientRect();
          return Math.max(canvas.width / box.width, canvas.height / box.height);
        }""")
        assert not errors
        browser.close()

    assert ratio <= 1.2, ratio


@pytest.mark.parametrize("width,height", [(1920, 1080), (320, 568)])
def test_robot_direction_marker_keeps_a_screen_sized_footprint(console_url, width, height):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser, page, errors = _open_console(p, API)
        page.set_viewport_size({"width": width, "height": height})
        page.goto(console_url, wait_until="networkidle")
        page.wait_for_function("() => (window.__mapMarkers || []).length > 0")
        marker_sizes = page.evaluate("""() => {
          const canvas = document.querySelector('#map-canvas');
          const box = canvas.getBoundingClientRect();
          return window.__mapMarkers.map(m => Math.max(
            Math.abs(m.w) * box.width / canvas.width,
            Math.abs(m.h) * box.height / canvas.height));
        }""")
        assert not errors
        save_temp_screenshot(page, f"fleet_marker_{width}x{height}.png")
        page.locator("#map-stage").screenshot(path=str(Path(os.environ.get("TEMP", "/tmp")) / f"fleet_marker_map_{width}x{height}.png"))
        browser.close()

    assert max(marker_sizes) <= 42, marker_sizes


@pytest.mark.parametrize("width,height", [(320, 568), (390, 844), (1366, 768)])
def test_wordmark_stays_on_one_line(console_url, width, height):
    """D-359 US-008 capture: at 320px "ROSY FLEET" broke into two lines (brand column 83px,
    text 119px). The wordmark is one line, not clipped, and does not run under the next item."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser, page, errors = _open_console(p, API)
        page.set_viewport_size({"width": width, "height": height})
        page.goto(console_url, wait_until="networkidle")
        mark = page.evaluate("""() => {
          const b = document.querySelector('ui-brand b');
          const range = document.createRange(); range.selectNodeContents(b);
          const lines = new Set([...range.getClientRects()].map((r) => Math.round(r.top))).size;
          const text = range.getBoundingClientRect();
          const more = document.getElementById('topbar-more');
          const next = more.getClientRects().length ? more.getBoundingClientRect() : null;
          return {lines, textRight: text.right, boxRight: b.getBoundingClientRect().right,
                  nextLeft: next && Math.abs(next.top - text.top) < text.height ? next.left : null,
                  wordWidth: document.querySelector('.fleet-wordmark').getBoundingClientRect().width,
                  brandWidth: document.querySelector('ui-brand').getBoundingClientRect().width,
                  name: document.querySelector('ui-brand a').getAttribute('aria-label')};
        }""")
        browser.close()

    assert errors == []
    if width < 480:
        # D-741 5: below 30rem the wordmark text folds to the R mark; the link keeps its name.
        assert mark["wordWidth"] <= 1 and mark["brandWidth"] > 0, mark
        assert mark["name"] == "Rosy Fleet 관제 홈", mark
        return
    assert mark["lines"] == 1, mark
    assert mark["textRight"] <= mark["boxRight"] + 0.5, mark
    if mark["nextLeft"] is not None:
        assert mark["textRight"] <= mark["nextLeft"], mark


@pytest.mark.parametrize("width,height", [(1920, 1080), (1366, 768), (390, 844)])
def test_member_label_sits_beside_the_first_checkbox_row(console_url, width, height):
    """D-359 US-008 capture: the member label (now "팔로워") sat below the checkbox row (centred on a wrapped list at
    1366/390; at wide widths it could flow into the previous row). The label shares the first
    row of the member list and stands to its left."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser, page, errors = _open_console(p, API)
        page.set_viewport_size({"width": width, "height": height})
        page.goto(console_url, wait_until="networkidle")
        page.locator('[data-context-tab="tools"]').click()
        page.locator(".formation-form-wrap > summary").click()
        page.locator("#formation-members").wait_for(state="visible")
        # Follower boxes leave the leader out: three robots, two boxes.
        page.wait_for_function("() => document.querySelectorAll('#formation-members label').length === 2")
        boxes = page.evaluate("""() => {
          const r = (n) => n.getBoundingClientRect().toJSON();
          return {label: r(document.querySelector('.member-label')),
                  first: r(document.querySelector('#formation-members label')),
                  list: r(document.getElementById('formation-members')),
                  named: document.getElementById('formation-members').getAttribute('aria-labelledby')};
        }""")
        browser.close()

    assert errors == []
    label, first, members = boxes["label"], boxes["first"], boxes["list"]
    centre = lambda box: box["y"] + box["height"] / 2  # noqa: E731
    assert abs(centre(label) - centre(first)) <= 2, boxes
    assert label["right"] <= members["x"], boxes
    assert boxes["named"] == "formation-members-label", boxes


def test_roster_mode_tag_speaks_korean_and_keeps_the_enum_in_title(console_url):
    """D-359 US-009 — the card's mode tag reads the shared MODE_LABEL."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, API)
        page.goto(console_url, wait_until="networkidle")
        _open_cards(page)
        first_tag = page.locator("#robot-workspace article").first.locator(".robot-head ui-tag").first
        assert first_tag.inner_text() == "내비게이션"
        assert first_tag.get_attribute("title") == "NAVIGATION"
        assert "NAVIGATION" not in page.inner_text("#roster")
        assert not errors
        browser.close()


@pytest.mark.parametrize("width,height", [(390, 844), (320, 568)])
def test_single_column_tier_puts_exceptions_and_robot_context_before_the_map(console_url, width, height):
    """D-892: intervention/context/map order and mounted owners survive resizing."""
    from playwright.sync_api import sync_playwright

    panels = ['.queues-panel', '.console-context', '[aria-labelledby="map-heading"]']
    with sync_playwright() as p:
        browser, page, errors = _open_console(p, API)
        page.set_viewport_size({"width": width, "height": height})
        page.goto(console_url, wait_until="networkidle")
        page.wait_for_function("() => document.querySelectorAll('#roster article').length > 0")
        assert page.locator('#context-status').is_visible()
        assert page.locator('#context-tools').is_hidden()
        layout = page.evaluate("""selectors => {
          const nodes = selectors.map(sel => document.querySelector(sel));
          return {top: nodes.map(node => node.getBoundingClientRect().top + scrollY),
            domOrder: nodes.slice(1).every((node, i) => Boolean(nodes[i].compareDocumentPosition(node) & Node.DOCUMENT_POSITION_FOLLOWING)),
            parents: nodes.map(node => node.parentElement.id)};
        }""", panels)
        assert layout['top'] == sorted(layout['top']), layout
        assert layout['domOrder'] and layout['parents'] == ['fleet-main'] * 3, layout
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.evaluate("""selectors => {
          window.retainedPanels = selectors.map(sel => document.querySelector(sel));
          window.retainedOwners = ['#roster', '#context-status', '#context-tools', '#context-evidence', '#context-inbox'].map(sel => document.querySelector(sel));
        }""", panels)
        page.locator('[data-context-tab="inbox"]').click()
        assert page.locator('#context-inbox').is_visible()
        assert page.locator('.queues-panel').is_visible() and page.locator('#map-stage').is_visible()
        page.locator('[data-context-tab="tools"]').click()
        page.locator('.formation-form-wrap > summary').click()
        page.locator('#formation-spacing').fill('1.7')
        page.locator('#formation-spacing').focus()
        page.set_viewport_size({"width": 1366, "height": 768})
        page.wait_for_function("() => document.querySelector('.console-primary').contains(document.querySelector('#map-stage'))")
        assert page.evaluate("selectors => selectors.every((sel, i) => document.querySelector(sel) === window.retainedPanels[i])", panels)
        assert page.locator('#context-tools').is_visible()
        assert page.locator('#formation-spacing').evaluate('(node) => node === document.activeElement')
        assert page.locator('#formation-spacing').input_value() == '1.7'
        assert page.locator('.console-primary').bounding_box()['x'] < page.locator('.console-context').bounding_box()['x']
        page.set_viewport_size({"width": width, "height": height})
        page.wait_for_function("() => document.querySelector('.console-context').parentElement.id === 'fleet-main'")
        assert page.evaluate("""selectors => {
          const nodes = selectors.map(sel => document.querySelector(sel));
          return nodes.every((node, i) => node === window.retainedPanels[i])
            && nodes.slice(1).every((node, i) => Boolean(nodes[i].compareDocumentPosition(node) & Node.DOCUMENT_POSITION_FOLLOWING))
            && ['#roster', '#context-status', '#context-tools', '#context-evidence', '#context-inbox'].every((sel, i) => document.querySelector(sel) === window.retainedOwners[i]);
        }""", panels)
        assert page.locator('#formation-spacing').input_value() == '1.7'
        assert page.locator('#formation-spacing').evaluate('(node) => node === document.activeElement')
        assert page.locator('[data-context-tab="tools"]').get_attribute('aria-selected') == 'true'
        page.locator('[data-context-tab="status"]').click()
        assert page.locator('#roster').is_visible() and page.locator('#context-tools').is_hidden()
        assert not errors
        browser.close()


PAINT_LOG = """
(() => {
  const log = [];
  window.__paintLog = log;
  const proto = CanvasRenderingContext2D.prototype;
  for (const name of ["drawImage", "stroke", "fillText"]) {
    const original = proto[name];
    proto[name] = function (...args) {
      if (this.canvas.id === "map-canvas") log.push(name === "fillText" ? `text:${args[0]}` : name);
      return original.apply(this, args);
    };
  }
})();
"""


def test_map_chips_paint_after_lines_and_clear_robot_markers(console_url):
    """D-359 US-008 leftovers — chips are painted after formation/mediation lines, so no line
    crosses chip text, and chips are placed off the robot marker boxes."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser, page, errors = _open_console(p, API, init_script=PAINT_LOG)
        page.goto(console_url, wait_until="networkidle")
        page.wait_for_function("() => (window.__swarmOverlay?.slots || 0) === 2", timeout=8000)
        page.wait_for_function("() => (window.__swarmOverlay?.mediation || 0) > 0")
        log = page.evaluate("window.__paintLog")
        last = log[max(i for i, op in enumerate(log) if op == "drawImage"):]  # the latest full draw
        texts = [i for i, op in enumerate(last) if op.startswith("text:")]
        strokes = [i for i, op in enumerate(last) if op == "stroke"]
        assert texts and strokes, last
        assert max(strokes) < min(texts), last
        chips = page.evaluate("window.__mapChips")
        markers = page.evaluate("window.__mapMarkers")
        assert len(markers) == 3
        overlap = [(c["text"], m["robot"]) for c in chips for m in markers
                   if c["x"] < m["x"] + m["w"] and m["x"] < c["x"] + c["w"]
                   and c["y"] < m["y"] + m["h"] and m["y"] < c["y"] + c["h"]]
        assert overlap == [], (overlap, chips, markers)
        assert not errors
        browser.close()


# --- D-341 카메라 연결 승인 (기기 연결 패널) ---------------------------------------


def test_camera_approval_takes_the_phone_code_and_shows_the_mutual_check(console_url):
    """D-341 3–4: approve = free paired source + the phone's six digits; the console never shows a code."""
    import re

    from playwright.sync_api import sync_playwright

    bodies = []
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, _camera_api())

        def approve(route):
            bodies.append(route.request.post_data_json)
            if len(bodies) == 1:
                route.fulfill(status=409, json={"detail": {
                    "code": "CODE_MISMATCH", "message": "code does not match the phone", "attempts_left": 2}})
                return
            route.fulfill(status=200, json={
                "request_id": "req-7f3a", "credential_id": "cred-9d0c11aa22bb", "source_id": "ceiling_south",
                "site_ca_fingerprint": CAMERA_FINGERPRINT, "expires_at": "2027-03-30T09:00:00+00:00",
                "confirm_within_s": 120})

        page.route("**/api/fleet/pairing/v1/requests/req-7f3a/approve", approve)
        page.goto(console_url.rsplit("/", 1)[0] + "/install.html", wait_until="networkidle")
        page.get_by_role("tab", name="카메라 연결 승인", exact=True).click()
        page.get_by_role("heading", name="카메라 연결 승인", exact=True).wait_for()
        ready = page.locator('#camera-requests li[data-request-id="req-7f3a"] ui-button[data-action="approve"]')
        ready.wait_for()
        assert ready.inner_text() == "승인…"
        waiting = page.locator('#camera-requests li[data-request-id="req-81bc"] ui-button[data-action="approve"]')
        assert waiting.get_attribute("reason") == "폰에 아직 코드가 없습니다"
        assert page.evaluate("document.getElementById('camera-requests').textContent").count("남은 시간") == 2
        assert "한도로 거절된 요청 2건" in page.locator("#camera-queue-health").inner_text()
        assert page.locator("#camera-site-fingerprint").inner_text() == CAMERA_FINGERPRINT
        _camera_shot(page, "01-pending-operator-1920.png")

        ready.click()
        page.wait_for_function("document.getElementById('camera-approve-dialog').open")
        assert page.evaluate("document.activeElement?.id") == "camera-approve-code"
        assert page.evaluate(
            "[...document.querySelectorAll('#camera-approve-source option')].map(o => o.value)") == ["ceiling_south"]
        assert page.evaluate("""() => { const s = document.getElementById('estop');
          for (let n = s; n; n = n.parentElement) if (n.inert) return false; return true; }""")
        page.locator("#camera-approve-code").fill("12345")
        page.locator("#camera-approve-submit").click()
        assert "숫자 6자리" in page.locator("#camera-approve-error").inner_text()
        assert bodies == []
        page.locator("#camera-approve-code").fill("123 456")
        page.locator("#camera-approve-submit").click()
        page.wait_for_function(
            "document.getElementById('camera-approve-error').textContent.includes('남은 입력 2회')")
        assert bodies == [{"code": "123456", "source_id": "ceiling_south"}]
        assert page.evaluate("document.getElementById('camera-approve-dialog').open")
        _camera_shot(page, "02-approve-dialog-mismatch-1920.png", "#camera-approve-dialog")
        page.locator("#camera-approve-code").fill("654321")
        page.locator("#camera-approve-submit").click()
        page.wait_for_function("!document.getElementById('camera-confirm').hidden")
        confirm = page.locator("#camera-confirm").inner_text()
        assert "폰 화면과 이 지문·자격 ID가 같은지 확인하세요" in confirm
        assert page.locator("#camera-confirm-fingerprint").inner_text() == CAMERA_FINGERPRINT
        assert page.locator("#camera-confirm-credential").inner_text() == "cred-9d0c11aa22bb"
        assert re.search(r"남은 시간 (2:00|1:5\d)", page.locator("#camera-confirm-clock").inner_text())
        mono = page.evaluate(
            "getComputedStyle(document.getElementById('camera-confirm-fingerprint')).fontFamily")
        assert "mono" in mono.lower() or "consolas" in mono.lower(), mono
        body = page.inner_text("body")
        assert "654321" not in body and "123456" not in body
        _camera_shot(page, "03-mutual-check-1920.png")
        page.set_viewport_size({"width": 1366, "height": 768})
        _camera_shot(page, "04-mutual-check-1366.png")
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        _camera_shot(page, "05-mutual-check-390.png")
        page.set_viewport_size({"width": 320, "height": 568})
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        _camera_shot(page, "06-mutual-check-320.png")
        assert not errors
        browser.close()


def test_camera_reject_and_revoke_are_quiet_row_actions_confirmed_by_name(console_url):
    """D-371: 거절…/폐기… open confirmIrreversible naming the target; danger fill only there."""
    from playwright.sync_api import sync_playwright

    posts = []

    def answer(body):
        def handle(route):
            posts.append((route.request.method, urlparse(route.request.url).path))
            route.fulfill(status=200, json=body)
        return handle

    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, _camera_api())
        page.route("**/api/fleet/pairing/v1/requests/req-81bc/reject",
                   answer({"request_id": "req-81bc", "state": "rejected"}))
        page.route("**/api/fleet/pairing/v1/credentials/cred-4be1a09c3d2f/revoke",
                   answer({"credential_id": "cred-4be1a09c3d2f", "state": "revoked"}))
        page.goto(console_url.rsplit("/", 1)[0] + "/install.html", wait_until="networkidle")
        page.get_by_role("tab", name="카메라 연결 승인", exact=True).click()
        revoke = page.locator('#camera-credentials li[data-credential-id="cred-4be1a09c3d2f"] '
                              'ui-button[data-action="revoke"]')
        revoke.wait_for()
        assert revoke.inner_text() == "폐기…" and revoke.get_attribute("kind") == "quiet"
        text = page.locator("#camera-credentials").inner_text()
        assert "사용 중" in text and "alice" in text and "2027-03-30" in text
        revoke.click()
        dialog = page.locator("dialog.ui-confirm")
        dialog.wait_for()
        assert '"cred-4be1a09c3d2f"' in dialog.locator("p").inner_text()
        assert dialog.locator('ui-button[kind="irreversible"]').inner_text() == "폐기"
        _camera_shot(page, "07-revoke-confirm-1920.png", "dialog.ui-confirm")
        page.keyboard.press("Escape")
        page.wait_for_function("!document.querySelector('dialog.ui-confirm')")
        assert page.evaluate("document.activeElement?.dataset.action") == "revoke"
        revoke_path = "/api/fleet/pairing/v1/credentials/cred-4be1a09c3d2f/revoke"
        assert ("POST", revoke_path) not in posts
        revoke.click()
        page.locator('dialog.ui-confirm ui-button[kind="irreversible"]').click()
        page.wait_for_function("document.getElementById('camera-result').textContent.includes('폐기했습니다')")

        reject = page.locator('#camera-requests li[data-request-id="req-81bc"] ui-button[data-action="reject"]')
        assert reject.inner_text() == "거절…"
        reject.click()
        page.locator("dialog.ui-confirm").wait_for()
        assert '"Pixel 7"' in page.locator("dialog.ui-confirm p").inner_text()
        page.locator('dialog.ui-confirm ui-button[kind="irreversible"]').click()
        page.wait_for_function("document.getElementById('camera-result').textContent.includes('거절했습니다')")
        assert ("POST", revoke_path) in posts
        assert ("POST", "/api/fleet/pairing/v1/requests/req-81bc/reject") in posts
        assert not errors
        browser.close()


@pytest.mark.parametrize("principal,role", [("vic", "viewer"), ("site-console", "operator")])
def test_camera_lists_without_actions_for_viewers_and_the_shared_token(console_url, principal, role):
    """D-341 5: viewers and a single console-token site see the lists, never an action button."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, _camera_api(principal, role))
        page.goto(console_url.rsplit("/", 1)[0] + "/install.html", wait_until="networkidle")
        page.get_by_role("tab", name="카메라 연결 승인", exact=True).click()
        page.locator('#camera-requests li[data-request-id="req-7f3a"]').wait_for()
        page.locator('#camera-credentials li[data-credential-id="cred-4be1a09c3d2f"]').wait_for()
        assert page.locator("#camera-requests ui-button, #camera-credentials ui-button").count() == 0
        if role == "viewer":
            assert page.locator("#camera-role-lock").is_visible()
            assert page.locator("#camera-role-lock").inner_text() == "운영자 권한이 필요합니다"
            assert page.locator("#camera-identity-note").is_hidden()
        else:
            note = page.locator("#camera-identity-note")
            assert note.is_visible() and "site-users.yaml" in note.inner_text()
        _camera_shot(page, f"08-lists-{role}-{principal}-1920.png")
        assert not errors
        browser.close()


def test_camera_section_is_calm_when_fleet_has_no_pairing(console_url):
    """Routes absent (plain 404): one calm sentence, and the panel stops asking."""
    from playwright.sync_api import sync_playwright

    api = {key: value for key, value in _camera_api().items() if "/pairing/" not in key}
    posts = []
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, api, posts)
        page.goto(console_url.rsplit("/", 1)[0] + "/install.html", wait_until="networkidle")
        page.get_by_role("tab", name="카메라 연결 승인", exact=True).click()
        calm = page.locator("#camera-link-unavailable")
        calm.wait_for()
        assert calm.inner_text() == "이 Fleet에는 카메라 연결 승인이 설정되지 않았습니다."
        assert page.locator("#camera-link-controls").is_hidden()
        page.wait_for_timeout(6000)
        asked = [p for p in posts if p[1] == "/api/fleet/pairing/v1/pending"]
        assert len(asked) == 1, asked
        _camera_shot(page, "09-no-pairing-1920.png")
        assert not errors
        browser.close()


ADDRESS_SHOTS = os.environ.get("ROSY_ADDRESS_SCREENSHOT_DIR")


def _address_api():
    offline = {"code": "CONNECT_ERROR", "reachable": False}
    snapshot = {"fleet": {"name": "site", "online": 0, "total": 3}, "ts": 0.0, "robots": [
        _robot(rid, {"x": 0.5 + i, "y": 1.0, "yaw": 0.0}, online=False, error=offline)
        for i, rid in enumerate(("rosy_01", "rosy_09", "rosy_10"))]}

    def entry(rid, origin, pinned, status, seen=(), movable=False, is_name=False):
        return {"robot_id": rid, "origin": origin, "pinned": pinned, "pinned_is_name": is_name,
                "status": status, "in_subnet": None if is_name else False,
                "seen_addresses": list(seen), "movable": movable}

    addresses = {"scanner_state": "online", "all_outside": True, "robots": [
        entry("rosy_01", "static", "192.0.2.10:8443", "outside_scanned_subnets"),
        entry("rosy_09", "enrolled", "192.0.2.20:8080", "seen_at_other_address",
              ["10.16.36.20:8080"], True),
        entry("rosy_10", "enrolled", "192.0.2.21:8080", "seen_at_other_address",
              ["10.16.36.21:8080"], True),
    ]}
    rows = [{"robot_id": rid, "hostname": rid, "address": pinned, "state": "address_changed",
             "legacy_lifetime": False, "origin": "enrolled", "hold": "address_changed",
             "expires_at": "2026-12-01T00:00:00+00:00"}
            for rid, pinned in (("rosy_09", "192.0.2.20:8080"), ("rosy_10", "192.0.2.21:8080"))]
    listing = {"available": True, "unavailable_reason": None, "static_robot_ids": ["rosy_01"],
               "robots": rows, "alarms": []}
    api = {**_enrollment_api(listing), "/api/fleet/state": snapshot,
           "/api/fleet/discovery/addresses": addresses,
           "/api/fleet/discovery": {"scanner_online": True, "scanner_state": "online",
                                    "scanner_age_s": 3, "devices": []}}
    return api


def _shot(page, name):
    if ADDRESS_SHOTS:
        Path(ADDRESS_SHOTS).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(ADDRESS_SHOTS) / name), full_page=True)


def test_offline_robots_say_why_and_each_move_asks_for_the_screen_code(console_url):
    """점검 2026-10-01 #2/#3/#5 + 리뷰: 경보는 옮길 로봇을 나열하고, 옮기기는 로봇마다 화면 코드."""
    from playwright.sync_api import sync_playwright

    moves = []
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, _address_api())

        def move(route):
            moves.append((urlparse(route.request.url).path, route.request.post_data_json))
            route.fulfill(status=200, json={"robot_id": "rosy_09", "address": "10.16.36.20:8080",
                                            "state": "active", "old_token_revoked": False})

        page.route("**/api/fleet/enrollment/robots/*/move-address", move)
        page.goto(console_url, wait_until="networkidle")
        banner = page.locator("#address-banner")
        banner.wait_for()
        assert banner.inner_text().startswith("사이트 망 주소가 바뀌었을 수 있습니다")
        page.wait_for_function(
            "() => document.querySelectorAll('#roster [data-address-reason]').length === 3")
        listed = page.locator("#address-movable li")
        assert listed.count() == 2
        assert "rosy_09 → 10.16.36.20:8080" in listed.nth(0).inner_text()
        card = page.locator('#roster article[data-robot-id="rosy_09"]')
        assert "같은 로봇이 10.16.36.20:8080에 보입니다 — 새 주소로 옮기기…" in card.inner_text()
        static = page.locator('#roster article[data-robot-id="rosy_01"]').inner_text()
        assert "고정 주소 192.0.2.10:8443이(가) 지금 망에 없을 수 있습니다" in static
        # Cards retain readable reasons; address actions belong to the install owner.
        assert page.evaluate("""() => [...document.querySelectorAll('#roster article')]
            .every((card) => card.scrollHeight <= card.clientHeight + 1)""")
        assert page.evaluate("""() => {
            const reason = document.querySelector('#roster article[data-robot-id="rosy_10"] .robot-summary-evidence');
            reason.scrollIntoView({block: 'nearest'});
            const r = reason.getBoundingClientRect();
            const box = document.querySelector('#roster').getBoundingClientRect();
            return r.top >= box.top - 1 && r.bottom <= box.bottom + 1; }""")
        assert page.locator('#roster ui-button[data-move-robot-id]').count() == 0
        assert page.locator('.doc-tabs a[href="/console/install"]').is_visible()
        page.evaluate("document.querySelector('#roster').scrollTop = 0")
        _shot(page, "roster-renumbered-1920.png")
        assert not page.locator("text=(전체)").count()

        page.goto(console_url.rsplit("/", 1)[0] + "/install.html", wait_until="networkidle")
        page.get_by_role("tab", name="로봇 등록", exact=True).click()
        page.wait_for_function("() => document.querySelectorAll('#enrolled-list ui-button[data-action=move]').length === 2")
        page.locator('#enrolled-list li[data-robot-id="rosy_09"] ui-button[data-action="move"]').click()
        dialog = page.locator("#enroll-dialog")
        dialog.wait_for()
        assert "rosy_09 → 10.16.36.20:8080" in page.locator("#enroll-target").inner_text()
        assert page.locator("#enroll-submit").inner_text() == "옮기기"
        check = page.locator("#enroll-move-check")
        assert check.is_visible()
        assert page.locator("#enroll-move-address").inner_text() == "10.16.36.20:8080"
        assert "로봇 화면에 보이는 IP와 같은지 확인하세요" in check.inner_text()
        assert page.locator("#estop").is_enabled()
        page.locator("#enroll-code").fill("7kxm" + "p3q")
        page.locator("#enroll-submit").click()
        assert moves == []  # format refused before anything is sent
        page.locator("#enroll-code").fill("7kxm" + "p3qa")
        _shot(page, "move-code-dialog-1920.png")
        page.locator("#enroll-submit").click()
        page.wait_for_function("() => document.querySelector('#enroll-result')?.textContent.includes('옮김')")
        assert moves == [("/api/fleet/enrollment/robots/rosy_09/move-address", {"code": "7KXM-" + "P3QA"})]
        result = page.locator("#enroll-result").inner_text()
        assert "로봇 대시보드에서 회수하거나 만료되게 두세요" in result

        # The enrolled-list action opens the same code dialog (no window.confirm).
        row_move = page.locator('#enrolled-list li[data-robot-id="rosy_10"] ui-button[data-action="move"]')
        assert row_move.inner_text() == "새 주소로 옮기기…"
        row_move.click()
        page.locator("#enroll-dialog").wait_for()
        assert "rosy_10" in page.locator("#enroll-target").inner_text()
        page.locator("#enroll-cancel").click()
        assert len(moves) == 1
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(300)
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        _shot(page, "roster-renumbered-390.png")
        assert not errors
        browser.close()


def test_move_candidate_timeout_and_pagehide_keep_server_code_flow_owned(console_url):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        api = _address_api()
        api['/api/fleet/discovery/addresses']['robots'][1]['seen_addresses'].append('10.16.36.99:8080')
        browser, page, errors = _open_console(playwright, api)
        held = []
        page.goto(console_url.rsplit('/', 1)[0] + '/install.html', wait_until='networkidle')
        page.get_by_role("tab", name="로봇 등록", exact=True).click()
        move = page.locator('#enrolled-list li[data-robot-id="rosy_09"] ui-button[data-action="move"]')
        move.wait_for()
        move.click()
        page.locator('#enroll-dialog').wait_for()
        assert page.locator('#enroll-move-address').inner_text() == '새 주소 미확인'
        page.locator('#enroll-cancel').click()
        page.route('**/api/fleet/discovery/addresses', lambda route: held.append(route))
        move.click()
        page.wait_for_function('() => document.querySelector("#enroll-result").textContent.includes("확인")')
        move.click()
        assert len(held) == 1
        assert page.locator('#estop').is_enabled()
        page.locator('#enroll-dialog').wait_for(timeout=15000)
        assert page.locator('#enroll-move-address').inner_text() == '새 주소 미확인'
        assert page.locator('#enroll-submit').is_enabled()
        page.locator('#enroll-cancel').click()
        move.click()
        page.wait_for_timeout(100)
        assert len(held) == 2
        page.locator('#enroll-address').fill('10.16.36.88:8080')
        page.locator('#enroll-address-add').click()
        page.locator('#enroll-code').fill('7KXM-' + 'P3QA')
        held[-1].fulfill(status=200, json=_address_api()['/api/fleet/discovery/addresses'])
        page.wait_for_timeout(100)
        assert page.locator('#enroll-target').inner_text() == '10.16.36.88:8080'
        assert page.locator('#enroll-code').input_value() == '7KXM-' + 'P3QA'
        page.locator('#enroll-cancel').click()
        move.click()
        page.wait_for_timeout(100)
        assert len(held) == 3
        page.locator('#enroll-address-add').click()
        page.locator('#enroll-cancel').click()
        move.click()
        page.wait_for_timeout(100)
        assert len(held) == 4
        held[-2].fulfill(status=200, json=_address_api()['/api/fleet/discovery/addresses'])
        page.wait_for_timeout(100)
        move.click()
        assert len(held) == 4  # An old finally cannot release the newer lookup.
        _open_token_access(page)
        page.locator('#console-token').fill('replacement-fixture-token')
        page.locator('#token-save').click()
        page.wait_for_function('() => !document.querySelector("#enroll-address-add").disabled')
        held[-1].fulfill(status=200, json=_address_api()['/api/fleet/discovery/addresses'])
        page.wait_for_timeout(100)
        assert page.locator('#enroll-dialog').is_hidden()
        move.click()
        page.wait_for_timeout(100)
        assert len(held) == 5
        page.evaluate('() => dispatchEvent(new PageTransitionEvent("pagehide"))')
        held[-1].fulfill(status=200, json=_address_api()['/api/fleet/discovery/addresses'])
        page.wait_for_timeout(100)
        assert page.locator('#enroll-dialog').is_hidden()
        assert not errors
        browser.close()


def test_viewer_sees_reasons_but_no_live_move_buttons(console_url):
    from playwright.sync_api import sync_playwright

    api = {**_address_api(), "/api/fleet/session": {"principal_id": "vic", "role": "viewer"}}
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, api)
        page.goto(console_url, wait_until="networkidle")
        page.locator("#address-banner").wait_for()
        page.wait_for_function(
            "() => document.querySelectorAll('#roster [data-address-reason]').length === 3")
        assert page.locator('#roster ui-button[data-move-robot-id]').count() == 0
        page.goto(console_url.rsplit("/", 1)[0] + "/install.html", wait_until="networkidle")
        page.wait_for_function("() => document.querySelectorAll('#enrolled-list li[data-robot-id]').length > 0")
        assert page.locator('#enrolled-list ui-button[data-action="move"]').count() == 0
        button = page.locator('#enroll-address-add')
        assert button.is_disabled()
        assert button.get_attribute("reason") == "운영자 권한이 필요합니다"
        assert not errors
        browser.close()


def test_login_unlocks_operator_controls_before_a_slow_state_gather(console_url):
    """A robot that times out makes /api/fleet/state slow; login must not wait for it.

    Found in the 2026-10-01 live pairing run: with one unreachable robot the state gather
    took 5.1 s and the console kept "토큰 필요" and locked operator buttons until it returned.
    """
    from playwright.sync_api import sync_playwright

    held_state = """(() => {
      const originalFetch = window.fetch.bind(window);
      window.__holdState = true;
      window.fetch = (input, options) => {
        const url = new URL(String(input), location.origin).pathname;
        const auth = new Headers(options?.headers).get('Authorization');
        if (url === '/api/fleet/session' && !auth) {
          return Promise.resolve(new Response(JSON.stringify({detail: {code: 'TOKEN_REQUIRED'}}),
            {status: 401, headers: {'Content-Type': 'application/json'}}));
        }
        if (url === '/api/fleet/state' && window.__holdState) {
          return new Promise(() => {});   // a gather stuck on an unreachable robot
        }
        return originalFetch(input, options);
      };
    })();"""
    api = {
        "/api/fleet/state": SNAPSHOT,
        "/api/fleet/map": MAP_GRID,
        "/api/fleet/formation": {"active": False, "state": "IDLE"},
    }
    with sync_playwright() as p:
        browser, page, errors = _open_console(p, api, init_script=held_state)
        page.goto(console_url, wait_until="domcontentloaded")
        _open_token_access(page)
        page.fill("#console-token", "operator-token")
        page.locator("#token-save").click()
        page.wait_for_function(
            "() => document.querySelector('#user-role')?.textContent.includes('운영자')", timeout=3000)
        page.wait_for_timeout(500)
        assert "접속 전" not in page.inner_text("#online-pill")
        assert page.locator("#token-save").is_enabled()
        assert not errors
        browser.close()


def test_the_install_document_owns_enrollment_and_calibration(console_url):
    """D-410 — 설치·보정 문서 렌더 계약.

    /console/install 은 기기 등록·카메라 연결 승인·경기장/맵 보정을 소유하고
    운용 표면(로스터·지도·대형·신호등)을 갖지 않는다. 전체 정지는 설치 문서의
    첫 화면에도 산다(D-280). mutation-proven: install.js의 enrollment 배선이나
    install.html의 아이디를 지우면 이 시험은 적색이어야 한다.
    """
    from playwright.sync_api import sync_playwright

    install_url = console_url.rsplit("/", 1)[0] + "/install.html"
    errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.on("pageerror", lambda exc: errors.append(str(exc)))

        def serve_api(route):
            path = urlparse(route.request.url).path
            body = {
                "/api/fleet/session": {"principal_id": "test-operator", "role": "operator"},
                "/api/fleet/discovery": {"scanner_online": True, "scanner_state": "ok",
                                         "devices": [{"name": "rosy_04", "address": "192.168.0.4",
                                                      "port": 8080, "status": "seen"}]},
                "/api/fleet/enrollment/robots": {
                    "available": True, "static_robot_ids": ["rosy_01"],
                    "robots": [{"robot_id": "rosy_02", "address": "192.168.0.2",
                                "online": False}],
                    "alarms": [],
                },
            }.get(path)
            if body is None:
                route.fulfill(status=404, json={"detail": "no such api"})
                return
            route.fulfill(status=200, json=body)

        page.route("**/api/**", serve_api)
        page.goto(install_url, wait_until="networkidle")
        # 세션 모형을 받으면 설치 문서도 운영자로 풀린다(토큰 게이트).
        page.wait_for_function(
            "() => document.getElementById('user-role').textContent.includes('운영자')", timeout=8000)
        # 등록 패널이 목록 모형을 그린다.
        page.wait_for_function(
            "() => document.getElementById('enrolled-list')?.innerText.includes('rosy_02')", timeout=8000)

        shell = page.locator("ui-shell")
        assert shell.get_attribute("grammar") == "procedure"
        assert "설치·보정" in page.title()
        # 설치 문서의 소유물.
        for needle in ("#robot-enrollment", "#camera-link", "#vision-adjustments", "#field-detect"):
            assert page.locator(needle).count() == 1, needle
        # 운용 표면은 없다 — 그 문서는 /console 이다.
        for absent in ("#roster", "#map-canvas", "#formation-heading", "#signals-heading"):
            assert page.locator(absent).count() == 0, absent
        # 전체 정지는 두 문서 모두 첫 화면에 있다(D-280).
        assert page.locator("#estop").is_visible()
        assert page.locator('a[href="/console"]').count() >= 1
        assert not errors
        save_temp_screenshot(page, "fleet_install_procedure.png")
        browser.close()


def _stuck_robot(**stuck_extra) -> dict:
    robot = _robot("rosy_01", {"x": 1.0, "y": 1.0, "yaw": 0.0})
    robot["line_stuck"] = {
        "robot_id": "rosy_01", "stuck_id": "stuck-abc", "cause": "obstacle_ahead",
        "phase": "ASKING", "held_s": 4.0, "attempts": 0, "max_attempts": 2,
        "local_enabled": False, "ask_remaining_s": 11.0, "last_answer": None,
        "decisions": ["WAIT", "RESUME", "BACK_AND_RETRY", "MANUAL", "ABORT"],
        "front_clearance_m": 0.12, "rear_clearance_m": 0.31, "turn_clearance_m": 0.09,
        "rear_blind_m": 0.05, "preview_seq": 812, "opened_event": True,
        "robot_online": True, "observed_age_s": 0.0, "fleet_answer": None, **stuck_extra,
    }
    return robot


def test_line_stuck_panel_confirms_resume_and_shows_cores_refusal_verbatim(console_url):
    """D-407: the panel lists the stuck, RESUME needs a confirm step, BACK_AND_RETRY is off
    while local recovery is disabled, and CORE's 409 reaches the operator unchanged."""
    from playwright.sync_api import sync_playwright

    snapshot = {"fleet": {"name": "site", "online": 1, "total": 1},
                "robots": [_stuck_robot()], "ts": 0.0}
    api = {"/api/fleet/state": snapshot, "/api/fleet/map": MAP_GRID,
           "/api/fleet/formation": {"active": False, "state": "IDLE"}}
    bodies = []
    order = []
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, api)

        def claim(route):
            order.append("claim")
            route.fulfill(status=200, json={"ok": True})

        def decision(route):
            order.append("decision")
            bodies.append(json.loads(route.request.post_data or "{}"))
            route.fulfill(status=409, json={"detail": {
                "code": "STUCK_DECISION_REFUSED", "robot_id": "rosy_01", "robot_status": 409,
                "message": "RESUME refused: object_within_stop_distance"}})

        page.route("**/api/fleet/robots/rosy_01/line-stuck/claim", claim)
        page.route("**/api/fleet/robots/rosy_01/line-stuck/decision", decision)
        page.goto(console_url, wait_until="networkidle")
        panel = page.locator("#critical-list")  # D-540 3: the answers open in the queue row
        panel.wait_for(state="visible")
        item = panel.locator('.stuck-item[data-robot-id="rosy_01"]')
        assert "앞 물체로 멈춤" in item.text_content()
        assert "0.12 m" in item.text_content() and "#812" in item.text_content()
        assert "판단 요청" in page.locator("#critical-list").text_content()
        back = item.locator('ui-button[data-decision="BACK_AND_RETRY"]')
        assert back.get_attribute("aria-disabled") == "true"
        assert "로컬 복구가 꺼져" in back.get_attribute("reason")

        # Escape cancels the confirm step without a request.
        item.locator('ui-button[data-decision="RESUME"]').click()
        confirm = item.locator(".stuck-confirm")
        confirm.wait_for(state="visible")
        page.keyboard.press("Escape")
        confirm.wait_for(state="detached")
        assert bodies == []
        assert order == ["claim"]   # D-438: the click claims; cancelling sends no decision

        # Keyboard: open the confirm step, survive a poll, then send.
        item.locator('ui-button[data-decision="RESUME"]').focus()
        page.keyboard.press("Enter")
        yes = item.locator('ui-button[data-focus-key="confirm-yes"]')
        yes.wait_for(state="visible")
        page.wait_for_function(
            "() => document.activeElement?.dataset?.focusKey === 'confirm-yes'")
        page.wait_for_timeout(1300)   # one state poll re-renders the panel
        assert yes.is_visible()
        page.keyboard.press("Enter")
        result = item.locator(".stuck-result")
        result.wait_for(state="visible")
        text = result.text_content()
        assert bodies == [{"stuck_id": "stuck-abc", "decision": "RESUME"}]
        assert order == ["claim", "claim", "decision"]   # claim always precedes the decision
        assert "정지 거리 안에 아직 물체가 있습니다" in text
        assert "STUCK_DECISION_REFUSED: RESUME refused: object_within_stop_distance" in text
        assert result.get_attribute("data-kind") == "bad"
        assert page.locator("#critical-list [style]").count() == 0
        assert not errors
        save_temp_screenshot(page, "fleet_line_stuck_panel.png")
        browser.close()


def _stuck_api(**stuck_extra) -> dict:
    return {"/api/fleet/state": {"fleet": {"name": "site", "online": 1, "total": 1},
                                 "robots": [_stuck_robot(**stuck_extra)], "ts": 0.0},
            "/api/fleet/map": MAP_GRID, "/api/fleet/formation": {"active": False, "state": "IDLE"}}


def test_line_stuck_answer_in_flight_blocks_a_second_submit_then_shows_success(console_url):
    """D-407 review L6: one answer per robot in flight; the accepted outcome is shown."""
    from playwright.sync_api import sync_playwright

    bodies, held = [], []
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, _stuck_api())

        def decision(route):
            bodies.append(json.loads(route.request.post_data or "{}"))
            held.append(route)   # answered below, after the in-flight checks

        page.route("**/api/fleet/robots/rosy_01/line-stuck/decision", decision)
        page.goto(console_url, wait_until="networkidle")
        item = page.locator('#critical-list .stuck-item[data-robot-id="rosy_01"]')
        wait = item.locator('ui-button[data-decision="WAIT"]')
        wait.click()
        page.wait_for_function("() => document.querySelector("
                               "'#critical-list ui-button[data-decision=\"WAIT\"]')"
                               "?.getAttribute('aria-disabled') === 'true'")
        assert "답을 보내는 중" in wait.get_attribute("reason")
        wait.click(force=True)
        item.locator('ui-button[data-decision="ABORT"]').click(force=True)
        page.wait_for_timeout(300)
        assert len(bodies) == 1 and len(held) == 1
        held[0].fulfill(status=200, json={"robot_id": "rosy_01", "actor_id": "op",
                                          "answer": {}, "result": {"outcome": "hold"}})
        result = item.locator(".stuck-result")
        result.wait_for(state="visible")
        assert result.get_attribute("data-kind") == "good"
        assert "rosy_01 대기: 대기로 답했습니다" in result.text_content()
        assert bodies == [{"stuck_id": "stuck-abc", "decision": "WAIT"}]
        assert wait.get_attribute("aria-disabled") == "false"
        assert not errors
        browser.close()


def test_line_stuck_confirm_follows_the_live_stuck_and_an_offline_robot(console_url):
    """D-407 review L2/L3/L6: a replaced stuck drops the confirm step; an unreachable robot
    disables every answer and the pending confirm's send button with the same reason."""
    from playwright.sync_api import sync_playwright

    api = _stuck_api(local_enabled=True)
    posts = []
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, api, posts=posts)
        page.goto(console_url, wait_until="networkidle")
        item = page.locator('#critical-list .stuck-item[data-robot-id="rosy_01"]')
        resume = item.locator('ui-button[data-decision="RESUME"]')
        resume.click()
        item.locator(".stuck-confirm").wait_for(state="visible")
        assert resume.get_attribute("aria-expanded") == "true"

        # CORE closed that stuck and opened another: the confirm step must not carry over.
        api["/api/fleet/state"] = _stuck_api(local_enabled=True, stuck_id="stuck-new")[
            "/api/fleet/state"]
        page.locator('.stuck-item[data-stuck-id="stuck-new"]').wait_for(state="attached")
        assert page.locator("#critical-list .stuck-confirm").count() == 0
        assert page.locator('#critical-list ui-button[data-decision="RESUME"]').get_attribute(
            "aria-expanded") == "false"

        # Open the confirm step again, then the robot drops off: send is blocked too.
        page.locator('#critical-list ui-button[data-decision="BACK_AND_RETRY"]').click()
        yes = page.locator('#critical-list ui-button[data-focus-key="confirm-yes"]')
        yes.wait_for(state="visible")
        assert yes.get_attribute("aria-disabled") == "false"
        api["/api/fleet/state"] = _stuck_api(local_enabled=True, stuck_id="stuck-new",
                                             robot_online=False)["/api/fleet/state"]
        page.locator("#critical-list .stuck-item.offline").wait_for(state="attached")
        buttons = page.locator("#critical-list .stuck-actions ui-button")
        assert buttons.count() == 5
        for index in range(5):
            assert buttons.nth(index).get_attribute("aria-disabled") == "true"
            assert "로봇 연결이 끊겼습니다" in buttons.nth(index).get_attribute("reason")
        assert yes.get_attribute("aria-disabled") == "true"
        assert "로봇 연결이 끊겼습니다" in yes.get_attribute("reason")
        yes.click(force=True)
        page.wait_for_timeout(300)
        assert not [p for p in posts if p[0] == "POST" and p[1].endswith("/line-stuck/decision")]
        assert not errors
        browser.close()


def test_paired_console_keeps_the_token_field_and_never_asks_for_a_session(console_url):
    from playwright.sync_api import sync_playwright

    posts: list[str] = []

    def serve_api(route):
        path = urlparse(route.request.url).path
        if route.request.method == "POST":
            posts.append(path)
        if path == "/api/fleet/auth/connection":
            route.fulfill(status=200, json={"mode": "paired"})
        else:
            route.fulfill(status=401, json={"detail": {"code": "UNAUTHORIZED"}})

    with sync_playwright() as p:
        browser, page, errors = open_page(p, 1920, 1080)
        page.route("**/api/**", serve_api)
        page.goto(console_url, wait_until="networkidle")
        page.wait_for_function("() => document.getElementById('online-pill').textContent === '접속 전'",
                               timeout=8000)
        assert page.is_hidden("#development-badge")
        _open_token_access(page)
        assert page.is_visible("#console-token")
        assert posts == []
        assert not errors, f"페이지 오류: {errors}"
        browser.close()


def test_shared_token_operator_sees_why_motion_is_locked_but_can_still_stop(console_url):
    """D-540 9: site-console may stop but not move; moving controls say why, stops stay usable."""
    from playwright.sync_api import sync_playwright

    named = "이름 있는 운영자 로그인이 필요합니다"
    api = {"/api/fleet/state": SNAPSHOT, "/api/fleet/map": MAP_GRID,
           "/api/fleet/formation": {"active": True, "state": "RUNNING"},
           "/api/fleet/session": {"principal_id": "site-console", "role": "operator"},
           "/api/fleet/dispatch-control": {"generation": 7, "dispatch_enabled": False,
                                           "rearm_available": True, "queued_tasks": 2,
                                           "unresolved_actions": 0}}
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, api)
        page.goto(console_url, wait_until="networkidle")
        # Rearm reopens dispatch (queued tasks move), so it is locked with the same reason.
        page.wait_for_function(f'() => document.querySelector("#dispatch-rearm")?.getAttribute("reason") === "{named}"')
        assert page.locator("#dispatch-rearm").get_attribute("disabled") is not None
        _open_cards(page)
        goal = page.locator('#robot-workspace ui-button[data-goal-robot-id]').first
        goal.wait_for()
        page.locator('[data-context-tab="tools"]').click()
        # D-540 6: the block says the cause once; every button it holds says "위 사유".
        page.wait_for_function(f'() => document.querySelector("#formation-why")?.textContent.includes("{named}")')
        assert page.locator("#formation-reform").get_attribute("reason") == "위 사유"
        assert goal.get_attribute("reason") == named
        assert page.locator("#formation-stop").get_attribute("reason") != named
        assert page.locator("#formation-stop").get_attribute("disabled") is None
        assert page.locator("#estop").get_attribute("disabled") is None
        page.locator('[data-context-tab="status"]').click()
        cancel = page.locator("#robot-workspace .robot-actions ui-button", has_text="취소").first
        assert cancel.get_attribute("reason") != named
        assert not errors
        browser.close()
