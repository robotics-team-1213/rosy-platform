"""D-359 §5.1·§5.3 — 공용 필드 바닥과 비활성 사유를 Chromium에서 확인한다.

표면 파일은 가짜 호스트(`http://rosy.test`)로 그대로 서빙한다(test_theme_browser와 같다).
API는 없으므로 페이지 스크립트의 네트워크 오류는 무시하고 정적 DOM과 공용 부품만 본다.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fleet.server.static_routes import CONSOLE_ASSETS
from browser_harness import browser_tests_enabled

pytestmark = pytest.mark.skipif(
    not browser_tests_enabled(),
    reason="set ROSY_RUN_BROWSER_TESTS=1 to run the optional Chromium regression",
)

SRC = (Path(__file__).resolve().parents[3] / "src")
COMMON = SRC.parent / "shared" / "web"
DASHBOARD = SRC.parent / "middleware" / "ui" / "robot"
FLEET = SRC.parent / "operations" / "fleet" / "fleet" / "server" / "web"
HOST = "http://rosy.test"
TYPES = {".css": "text/css", ".js": "application/javascript", ".html": "text/html"}
BUTTON_PAGE = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<link rel="stylesheet" href="/common/tokens.css">
<link rel="stylesheet" href="/common/components.css">
<script type="module" src="/common/ui.js"></script></head>
<body><ui-button id="go" kind="primary" type="button" disabled
  reason="운용자 권한이 필요합니다">목표 보내기</ui-button>
<span id="other">다른 설명</span></body></html>"""
TRACKING_PAGE = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<link rel="stylesheet" href="/common/tokens.css">
<link rel="stylesheet" href="/common/components.css">
<script type="module" src="/common/ui.js"></script></head>
<body style="font-family: var(--body)"><ui-button id="seg" kind="segment" type="button">점유 지도</ui-button>
<ui-tag id="latin" status="neutral">RUNNING</ui-tag>
<ui-tag id="ko" status="neutral">대기</ui-tag>
<ui-brand><b>ROSY</b><small id="sub">작업 준비</small></ui-brand></body></html>"""
CHECK_PAGE = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<link rel="stylesheet" href="/common/tokens.css">
<link rel="stylesheet" href="/common/components.css"></head>
<body style="background: var(--ground); padding: 16px">
<label class="ui-check"><input id="on" class="ui-field" type="checkbox" checked>rosy_01</label>
<label class="ui-check"><input id="held" class="ui-field" type="checkbox" checked disabled>rosy_02</label>
<label class="ui-check"><input id="off" class="ui-field" type="checkbox" disabled>rosy_03</label>
<label class="ui-check"><input id="free" class="ui-field" type="checkbox">rosy_04</label>
</body></html>"""
TRACKING_PROBE = """(ids) => Object.fromEntries(ids.map((id) => {
  const el = document.getElementById(id);
  const style = getComputedStyle(el);
  return [id, {spacing: style.letterSpacing, size: parseFloat(style.fontSize)}];
}))"""

FIELD_PROBE = """() => {
  const floor = parseFloat(getComputedStyle(document.documentElement)
    .getPropertyValue('--target-secondary'));
  const bad = [];
  for (const field of document.querySelectorAll('input, select, textarea')) {
    if (field.type === 'hidden' || field.closest('ui-field')) continue;
    const name = field.id || field.name || field.getAttribute('aria-label') || field.outerHTML.slice(0, 60);
    if (!field.classList.contains('ui-field')) { bad.push(`${name}: no ui-field`); continue; }
    const box = field.type === 'checkbox' || field.type === 'radio' ? field.closest('label') : field;
    const minHeight = box ? parseFloat(getComputedStyle(box).minHeight) : 0;
    if (!(minHeight >= floor)) bad.push(`${name}: min-height ${minHeight}`);
  }
  return {floor, count: document.querySelectorAll('input, select, textarea').length, bad};
}"""


def _serve(route):
    path = route.request.url.removeprefix(HOST).split("?", 1)[0]
    if path.startswith("/common/"):
        target = COMMON / path.removeprefix("/common/")
    elif path.startswith("/console/assets/"):
        entry = CONSOLE_ASSETS.get(path.removeprefix("/console/assets/"))
        if entry is None:
            return route.fulfill(status=404, body="")
        target = FLEET / entry[0]
    elif path.startswith("/dashboard/assets/"):
        target = DASHBOARD / path.removeprefix("/dashboard/assets/")
    elif path == "/console":
        target = FLEET / "index.html"
    elif path == "/dashboard":
        target = DASHBOARD / "index.html"
    elif path == "/button":
        return route.fulfill(status=200, content_type="text/html", body=BUTTON_PAGE)
    elif path == "/check":
        return route.fulfill(status=200, content_type="text/html", body=CHECK_PAGE)
    elif path == "/tracking":
        return route.fulfill(status=200, content_type="text/html", body=TRACKING_PAGE)
    else:
        return route.fulfill(status=404, body="")
    if not target.is_file():
        return route.fulfill(status=404, body="")
    return route.fulfill(status=200, content_type=TYPES.get(target.suffix, "text/plain"),
                         body=target.read_text(encoding="utf-8"))


@pytest.fixture()
def page():
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True)
        except Exception as error:  # pragma: no cover - host without Chromium
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        context = browser.new_context(viewport={"width": 1366, "height": 768})
        context.route(f"{HOST}/**", _serve)
        yield context.new_page()
        browser.close()


def test_closed_dialog_handle_cannot_close_a_new_owner(page):
    page.goto(f"{HOST}/button")
    page.evaluate("""async () => {
      const {openLiveDialog}=await import('/common/ui.js');
      const opener=document.createElement('button');opener.id='opener';opener.textContent='open';
      const dialog=document.createElement('dialog');dialog.innerHTML='<button id="close-owner">close</button>';
      document.body.append(opener,dialog);window.closedA=0;window.closedB=0;
      const closeA=openLiveDialog(dialog,{opener,onClose:()=>window.closedA++});
      closeA('cancel');
      window.closeB=openLiveDialog(dialog,{opener,onClose:()=>window.closedB++});
      closeA('confirm');
      document.querySelector('#close-owner').addEventListener('click',()=>dialog.close('cancel'));
      window.frames=0;requestAnimationFrame(()=>requestAnimationFrame(()=>window.frames=2));
    }""")
    page.wait_for_function('window.frames===2')
    assert page.locator('dialog[open]').count() == 1
    assert page.locator('.ui-confirm-scrim').count() == 1
    assert page.locator('#opener').evaluate('(node)=>node.inert')
    assert page.evaluate('[window.closedA,window.closedB]') == [1, 0]
    page.locator('#close-owner').click()
    page.wait_for_function('window.closedB===1')
    assert page.locator('dialog[open]').count() == 0
    assert page.locator('.ui-confirm-scrim').count() == 0
    assert not page.locator('#opener').evaluate('(node)=>node.inert')
    assert page.evaluate('document.activeElement.id') == 'opener'
    assert page.evaluate('[window.closedA,window.closedB]') == [1, 1]


def test_reason_renders_visible_text_linked_by_describedby(page):
    page.goto(f"{HOST}/button")
    page.wait_for_function("() => customElements.get('ui-button') && document.querySelector('#go small')")
    first = page.evaluate("""() => {
      const button = document.getElementById('go');
      const note = button.querySelector('small[data-reason]');
      const box = note.getBoundingClientRect();
      return {
        text: note.textContent,
        described: button.getAttribute('aria-describedby'),
        id: note.id,
        hidden: note.getAttribute('aria-hidden'),
        visible: box.width > 0 && box.height > 0 && getComputedStyle(note).visibility === 'visible',
        colour: getComputedStyle(note).color,
        quiet: (() => { const p = document.createElement('i'); p.style.color = 'var(--ink-quiet)';
          document.body.append(p); const c = getComputedStyle(p).color; p.remove(); return c; })(),
        opacity: getComputedStyle(button).opacity,
      };
    }""")
    assert first["text"] == "운용자 권한이 필요합니다"
    assert first["visible"], first
    assert first["id"] and first["id"] in first["described"].split()
    assert first["hidden"] == "true"  # 이름이 아니라 설명으로 읽힌다
    assert first["colour"] == first["quiet"]
    assert first["opacity"] == "1", "사유가 있는 비활성은 사유 글자까지 흐리지 않는다"
    name = page.get_by_role("button", name="목표 보내기", exact=True)
    assert name.count() == 1

    # 다른 설명과 함께 살고, 바뀌면 따라 바뀌고, 글자를 갈아도 다시 붙고, 지우면 사라진다.
    page.evaluate("""() => {
      const button = document.getElementById('go');
      button.setAttribute('aria-describedby', 'other ' + button.getAttribute('aria-describedby'));
      button.setAttribute('reason', '지도 없음');
      button.textContent = '목표';
    }""")
    page.wait_for_function("() => document.querySelector('#go small[data-reason]')?.textContent === '지도 없음'")
    updated = page.evaluate("""() => {
      const button = document.getElementById('go');
      return {described: button.getAttribute('aria-describedby'),
              count: button.querySelectorAll('small[data-reason]').length};
    }""")
    assert updated["count"] == 1
    assert "other" in updated["described"].split()
    page.evaluate("() => { const b = document.getElementById('go'); b.reason = ''; b.disabled = false; }")
    cleared = page.evaluate("""() => {
      const button = document.getElementById('go');
      return {note: button.querySelector('small[data-reason]'),
              described: button.getAttribute('aria-describedby'),
              opacity: getComputedStyle(button).opacity};
    }""")
    assert cleared["note"] is None
    assert cleared["described"] == "other"


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_a_reason_reads_quiet_on_every_kind_and_theme(page, theme):
    """US-007 light /device capture: `ui-button[kind="irreversible"] small` (ink-on-crit, for the
    danger fill) out-ranked the reason colour, so a disabled irreversible reason drew light ink
    on the unfilled light ground and vanished. The reason is always quiet ink."""
    page.goto(f"{HOST}/button")
    page.wait_for_function("() => customElements.get('ui-button') && document.querySelector('#go small')")
    colours = page.evaluate("""(theme) => {
      document.documentElement.setAttribute('data-theme', theme);
      const quiet = (() => { const p = document.createElement('i'); p.style.color = 'var(--ink-quiet)';
        document.body.append(p); const c = getComputedStyle(p).color; p.remove(); return c; })();
      const out = {};
      for (const kind of ['primary', 'quiet', 'irreversible', 'segment', 'toggle']) {
        const b = document.createElement('ui-button');
        b.setAttribute('kind', kind); b.disabled = true; b.setAttribute('reason', '지금 쓰는 토큰');
        b.innerHTML = '<span>삭제</span>';
        document.body.append(b);
        out[kind] = getComputedStyle(b.querySelector('small[data-reason]')).color;
      }
      return {quiet, out};
    }""", theme)
    assert {kind: colour for kind, colour in colours["out"].items() if colour != colours["quiet"]} == {}


@pytest.mark.parametrize("path", ["/console", "/dashboard"])
def test_every_product_field_clears_the_secondary_target(page, path):
    page.goto(f"{HOST}{path}")
    page.wait_for_function("() => customElements.get('ui-button')")
    probe = page.evaluate(FIELD_PROBE)
    assert probe["floor"] == 44
    assert probe["count"] > 0
    assert not probe["bad"], probe["bad"]


def _spacing_px(value):
    return 0.0 if value == "normal" else float(value.removesuffix("px"))


def test_hangul_labels_drop_the_latin_tracking(page):
    """US-008: the tracking tokens are for Latin uppercase labels. Hangul in a tracked label read
    as "점유  지도"; an element whose own text has Hangul renders with 0 tracking, a Latin tag keeps
    the token, and the rule follows text that changes at run time."""
    page.goto(f"{HOST}/tracking")
    page.wait_for_function("() => customElements.get('ui-tag') && document.getElementById('seg').hasAttribute('data-hangul')")
    probe = page.evaluate(TRACKING_PROBE, ["seg", "latin", "ko", "sub"])
    track_state = float(page.evaluate(
        "() => getComputedStyle(document.documentElement).getPropertyValue('--track-state')").removesuffix("em"))
    assert track_state > 0
    assert _spacing_px(probe["latin"]["spacing"]) == pytest.approx(track_state * probe["latin"]["size"], abs=0.05)
    for key in ("seg", "ko", "sub"):
        assert _spacing_px(probe[key]["spacing"]) == 0, (key, probe[key])
    # 등폭 칸의 띄어쓰기도 한글을 띄운다 — 한글 라벨은 본문 가족, 라틴 태그는 등폭 그대로다.
    families = page.evaluate("""() => ({
      body: getComputedStyle(document.body).fontFamily,
      latin: getComputedStyle(document.getElementById('latin')).fontFamily,
      ko: getComputedStyle(document.getElementById('ko')).fontFamily,
      mono: getComputedStyle(document.documentElement).getPropertyValue('--mono').trim()})""")
    assert families["ko"] == families["body"], families
    assert families["latin"] != families["body"], families

    page.evaluate("""() => {
      document.getElementById('latin').textContent = '정지';
      document.getElementById('ko').firstChild.data = 'IDLE';
    }""")
    page.wait_for_function("() => document.getElementById('latin').hasAttribute('data-hangul')"
                           " && !document.getElementById('ko').hasAttribute('data-hangul')")
    swapped = page.evaluate(TRACKING_PROBE, ["latin", "ko"])
    assert _spacing_px(swapped["latin"]["spacing"]) == 0
    assert _spacing_px(swapped["ko"]["spacing"]) > 0


@pytest.mark.parametrize("path", ["/console", "/dashboard"])
def test_no_hangul_text_on_a_surface_is_tracked(page, path):
    page.goto(f"{HOST}{path}")
    page.wait_for_function("() => customElements.get('ui-button')")
    page.wait_for_timeout(300)
    tracked = page.evaluate("""() => {
      const hangul = /[㄰-㆏가-힯]/;
      const bad = [];
      for (const el of document.body.querySelectorAll('*')) {
        const own = [...el.childNodes].filter((n) => n.nodeType === 3).map((n) => n.data).join('');
        if (!hangul.test(own)) continue;
        const spacing = getComputedStyle(el).letterSpacing;
        if (spacing !== 'normal' && parseFloat(spacing) !== 0) bad.push(`${own.trim().slice(0, 20)}: ${spacing}`);
      }
      return bad;
    }""")
    assert tracked == []


def _luminance(rgb):
    def channel(value):
        value /= 255
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4
    return 0.2126 * channel(rgb[0]) + 0.7152 * channel(rgb[1]) + 0.0722 * channel(rgb[2])


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_checked_checkboxes_hold_three_to_one_even_when_disabled(page, theme):
    """US-008 light Fleet capture: formation members (checked, disabled while RUNNING) drew
    Chromium's fixed grey disabled checkbox at --disabled-opacity: 1.2:1 on light, 1.8:1 on dark.
    The drawn pixels of every checkbox reach 3:1 against the ground (WCAG 1.4.11)."""
    image = pytest.importorskip("PIL.Image")
    import io

    page.goto(f"{HOST}/check")
    page.evaluate("(theme) => document.documentElement.setAttribute('data-theme', theme)", theme)
    ground = image.open(io.BytesIO(page.screenshot(clip={"x": 0, "y": 0, "width": 4, "height": 4}))
                        ).convert("RGB").getpixel((1, 1))
    lg = _luminance(ground)
    ratios = {}
    for box in ("on", "held", "off", "free"):
        pixels = image.open(io.BytesIO(page.locator(f"#{box}").screenshot())).convert("RGB")
        ratios[box] = round(max((max(_luminance(p), lg) + 0.05) / (min(_luminance(p), lg) + 0.05)
                                for _, p in pixels.getcolors(1 << 16)), 2)
    assert {box: ratio for box, ratio in ratios.items() if ratio < 3.0} == {}, (ground, ratios)


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_a_disabled_unchecked_box_does_not_look_like_an_enabled_one(page, theme):
    """US-009 (US-008 leftover) — disabled and enabled empty boxes drew the same solid frame.
    Disabled is a dashed frame of the same ink (so 3:1 holds, see above) and is not faded."""
    page.goto(f"{HOST}/check")
    page.evaluate("(theme) => document.documentElement.setAttribute('data-theme', theme)", theme)
    style = page.evaluate("""() => Object.fromEntries(['off', 'free', 'held'].map((id) => {
      const s = getComputedStyle(document.getElementById(id));
      return [id, {border: s.borderTopStyle, opacity: s.opacity}];
    }))""")
    assert style["free"]["border"] == "solid"
    assert style["off"]["border"] == "dashed" and style["held"]["border"] == "dashed"
    assert style["off"]["opacity"] == "1"
    assert page.locator("#off").screenshot() != page.locator("#free").screenshot()
