"""concept 16 §7.1/§7.2 / D-77 — 운용 콘솔은 공간 문법, 점검은 절차 문법이다.

한 화면에 두 문법을 섞지 않는다(§4 L2). 이 시험은 그 분리를 구조로 지킨다.
CI에 브라우저가 없으므로 배치 자체는 잴 수 없다 — 대신 배치를 성립시키는
**구조와 규칙**을 단언한다. 실제 렌더 측정은 Playwright로 따로 했고, 그때
잡힌 결함들이 아래 각 단언의 이유다.
"""

from pathlib import Path
import re

WEB_ROOT = Path(__file__).resolve().parents[4] / "middleware" / "ui" / "robot"
INDEX = WEB_ROOT / "index.html"
STYLES = WEB_ROOT / "styles.css"
DETAIL = WEB_ROOT / "console-detail.css"
APP = WEB_ROOT / "app.js"


def html() -> str:
    return INDEX.read_text(encoding="utf-8")


def css() -> str:
    # D-362 P1 split the surface CSS; console-detail.css links after styles.css,
    # so the cascade these rules live in is both files together.
    return "\n".join(path.read_text(encoding="utf-8") for path in (STYLES, DETAIL))


def test_the_two_grammars_live_in_separate_containers():
    markup = html()
    assert 'id="view-operate-panel"' in markup and 'class="console"' in markup
    assert 'id="view-inspect-panel"' in markup and 'class="inspect"' in markup


def test_the_console_holds_the_three_regions_in_order():
    markup = html()
    order = [m for m in re.findall(r"region region-(sense|observe|act)", markup)]
    assert order == ["sense", "observe", "act"], f"영역 순서가 감지·관측·조작이 아니다: {order}"


def test_the_operator_panels_are_in_the_console_and_the_rest_in_inspect():
    markup = html()
    console = markup.split('id="view-operate-panel"')[1].split('id="view-inspect-panel"')[0]
    inspect = markup.split('id="view-inspect-panel"')[1]
    for panel in ("motion-panel", "field-map-panel", "control-panel", "capability-panel"):
        assert panel in console, f"{panel}이 운용 화면에 없다"
    for panel in ("system-panel", "host-panel", "ros-network-panel", "field-settings-panel"):
        assert panel in inspect, f"{panel}이 점검 화면에 없다"


def test_the_inspect_order_follows_bringup_order():
    """§7.2 — 절차는 기동 순서를 따른다: host OS·네트워크 → DDS 그래프 →
    릴리즈 → 커미셔닝. 릴리즈·커미셔닝이 그래프 앞(네트워크 패널 안)에 있던
    것이 D-153 회차10 F-10이다 — 이 순서는 게이트가 없어 표류했다."""
    markup = html()
    order = [
        markup.find(x)
        for x in (
            'id="host-panel"',
            'id="ros-network-panel"',
            'id="release-card"',
            'id="commissioning-card"',
            'id="field-settings-panel"',
        )
    ]
    assert -1 not in order
    assert all(a < b for a, b in zip(order, order[1:])), (
        f"점검 순서가 기동 순서(§7.2)가 아니다: {order}"
    )


def test_a_hidden_view_does_not_take_layout():
    """`display`를 지정한 요소에는 `[hidden]`의 display:none이 진다.

    그 버그로 숨긴 점검 뷰가 레이아웃을 차지해 페이지가 3582px 스크롤했고
    지도가 24px로 눌렸다. 측정으로 확인했고, 이 규칙이 그걸 막는다.
    """
    assert re.search(r"\[hidden\]\s*\{[^}]*display:\s*none\s*!important", css()), (
        "[hidden]을 display:none !important로 고정하는 규칙이 없다"
    )


def test_the_console_does_not_scroll():
    """위치가 기억이다. 콘솔이 스크롤하면 그 약속이 깨진다."""
    # D-359 §6.5: 고정 프레임은 넓고 충분히 높은 창에서만이다(그 밖은 흐르며 스크롤).
    # 그 조건 안의 .console이 뷰포트(dvh)에 묶이고 넘침을 숨겨야 한다.
    frame = re.search(
        r"@media\s*\(width >= 64rem\)\s*and\s*\(height >= 40rem\)\s*\{\s*\.console\s*\{([^}]*)\}",
        css())
    assert frame, "넓고 높은 창의 .console 고정 프레임 규칙이 없다"
    body = frame.group(1)
    assert "100dvh" in body and "--topbar-height" in body, "콘솔 높이가 뷰포트에 묶여 있지 않다"
    assert "overflow: hidden" in body
    # 꼬리말은 스크롤하는 점검 뷰의 것이다 — 운용에서 64px을 가져가면 그만큼
    # 지도가 줄어든다. 클래스 셀렉터여야 한다(`#page-footer`는 존재하지 않는다).
    assert 'body[data-view="operate"] .page-footer' in css()


def test_only_the_sense_region_may_scroll():
    """내용이 넘치면 감지만 스크롤하고 관측·조작은 고정된다(§7.1)."""
    observe = re.search(r"\.region-observe\s*\{([^}]*)\}", css())
    assert observe and "overflow-y: auto" not in observe.group(1)


def test_the_irreversible_control_comes_first_in_the_act_region():
    """비상정지가 teleop 뒤에 있으면 화면 밖으로 밀린다 — 실제로 y=832였다.
    자리도 탭 순서도 첫째여야 한다."""
    markup = html()
    control = markup.split('class="panel control-panel"')[1].split("</section>")[0]
    assert control.index("safety-actions") < control.index("teleop-commissioning")


def test_the_view_switch_is_wired_and_defaults_to_operate():
    app = APP.read_text(encoding="utf-8")
    assert 'showView("operate")' in app, "기본 뷰를 운용으로 두지 않는다"
    assert 'elements["view-inspect"].addEventListener' in app
    # D-362 P1: the renderer module owns writing the body's view state.
    telemetry = (WEB_ROOT / "telemetry.js").read_text(encoding="utf-8")
    assert 'document.body.dataset.view' in telemetry, "꼬리말 규칙이 기대는 페이지 상태가 없다"


def test_the_map_tools_stay_off_the_raster():
    """점유 격자가 도구에 가려지면 지도를 못 읽는다.

    도구는 제목 줄의 한 행이고 범례는 캔버스 아래 한 줄이다. 무대 안에
    절대 위치로 올리면 격자를 덮고, 두 줄로 쌓으면 높이를 다시 먹는다.
    """
    markup = html()
    panel = markup.split('id="field-map-panel"')[1].split("</section>")[0]
    stage = panel.split('class="map-stage"')[1].split("</div>")[0]
    assert panel.count('class="map-toolbar"') == 2, "지도 툴바가 둘이 아니다"
    assert "map-toolbar" not in stage, "툴바가 지도 무대 안에서 격자를 가린다"
    assert 'id="map-legend"' not in stage, "범례가 캔버스 위에 있다"
    assert panel.index('class="map-stage"') < panel.index('id="map-legend"')

    sheet = css()
    assert not re.search(r"\.map-controls\s*\{[^}]*position:\s*absolute", sheet)
    assert not re.search(r"\.map-legend\s*\{[^}]*position:\s*absolute", sheet)
    blocks = re.findall(r"([^{}]+)\{([^}]*)\}", sheet)
    tools = [body for selector, body in blocks if selector.strip() == ".map-tools"]
    assert tools, ".map-tools 규칙이 없다"
    assert "flex-direction: row" in tools[0]
    assert "flex-direction: column" not in tools[0]
