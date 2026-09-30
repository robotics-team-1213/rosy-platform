"""D-371 / D-280 원칙 2 — 정지 컨트롤은 확인 대화상자 위에서도 살아 있다.

`confirmIrreversible`(ui.js)은 비모달로 열고 `[data-always-live]`와 대화상자 밖을
inert로 만든다. 그러니 ui.js를 싣는 모든 페이지는 마크업의 정지 컨트롤(위험 채움
`ui-button kind="irreversible"` 중 이름에 `정지`가 든 것)에 `data-always-live`를 단다.
빠지면 그 페이지에서 대화상자가 열리는 순간 정지가 막힌다.
"""

from html.parser import HTMLParser
from pathlib import Path

SRC = Path(__file__).resolve().parents[3]
UI_SCRIPT = 'src="/common/ui.js"'


class StopScan(HTMLParser):
    """Static irreversible ui-buttons named `…정지…`: (line, has data-always-live)."""

    def __init__(self):
        super().__init__()
        self.open = None
        self.stops = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "ui-button" and attrs.get("kind") == "irreversible" and self.open is None:
            self.open = [self.getpos()[0], "data-always-live" in attrs, attrs.get("aria-label") or ""]

    def handle_data(self, data):
        if self.open is not None:
            self.open[2] += data

    def handle_endtag(self, tag):
        if tag == "ui-button" and self.open is not None:
            line, live, name = self.open
            if "정지" in name:
                self.stops.append((line, live))
            self.open = None


def stops_in(text):
    scan = StopScan()
    scan.feed(text)
    return scan.stops


def ui_pages():
    for path in sorted(SRC.rglob("*.html")):
        parts = path.relative_to(SRC).parts
        if "test" in parts or "node_modules" in parts or {"build", "install"} & set(parts):
            continue
        text = path.read_text(encoding="utf-8")
        if UI_SCRIPT in text:
            yield path, text


def test_every_stop_on_a_ui_js_page_is_always_live():
    pages = list(ui_pages())
    offenders, stops = [], 0
    for path, text in pages:
        for line, live in stops_in(text):
            stops += 1
            if not live:
                offenders.append(f"{path.relative_to(SRC)}:{line}")
    assert offenders == [], f"정지 컨트롤에 data-always-live가 없다(대화상자가 열리면 막힌다): {offenders}"
    names = {path.relative_to(SRC).as_posix() for path, _ in pages}
    for page in ("hmi/dashboard/surface.html", "hmi/dashboard/index.html", "site/fleet/fleet/server/web/index.html"):
        assert page in names, f"스캔이 {page}를 놓쳤다"
    assert stops >= 6, "셸·옛 대시보드·Fleet·게임·진단 정지를 모두 센다"


def test_the_scan_fires_when_the_attribute_is_removed():
    """Mutation proof on the real shell markup."""
    shell = (SRC / "hmi" / "dashboard" / "surface.html").read_text(encoding="utf-8")
    assert stops_in(shell) == [(25, True)]
    stripped = shell.replace(" data-always-live", "")
    assert stops_in(stripped) == [(25, False)]
    assert stops_in('<ui-button kind="irreversible">도크 삭제</ui-button>') == []
    assert stops_in('<ui-button kind="irreversible" aria-label="전체 로봇 정지"><span>전체</span></ui-button>') == [(1, False)]
