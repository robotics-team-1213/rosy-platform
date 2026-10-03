"""D-371 / D-280 원칙 2 — 정지 컨트롤은 확인 대화상자 위에서도 살아 있다.

`confirmIrreversible`(ui.js)은 비모달로 열고 `[data-always-live]`와 대화상자 밖을
inert로 만든다. 그러니 ui.js를 싣는 모든 페이지는 마크업의 정지 컨트롤(위험 채움
`ui-button kind="irreversible"` 중 이름에 `정지`가 든 것)에 `data-always-live`를 단다.
빠지면 그 페이지에서 대화상자가 열리는 순간 정지가 막힌다.
"""

from html.parser import HTMLParser
import os
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]  # repository root (D-427: keys are repo-relative)
#: D-427: product pages live under these part roots while src/ empties.
PAGE_ROOTS = tuple(REPO / name for name in ("src", "operations", "middleware", "shared") if (REPO / name).is_dir())


def _rel(path: Path) -> str:
    return Path(os.path.relpath(path, REPO)).as_posix()
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
    for path in sorted(path for root in PAGE_ROOTS for path in root.rglob("*.html")):
        parts = Path(_rel(path)).parts
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
                offenders.append(f"{_rel(path)}:{line}")
    assert offenders == [], f"정지 컨트롤에 data-always-live가 없다(대화상자가 열리면 막힌다): {offenders}"
    names = {_rel(path) for path, _ in pages}
    for page in ("src/hmi/dashboard/surface.html", "src/hmi/dashboard/index.html", "operations/fleet/fleet/server/web/index.html"):
        assert page in names, f"스캔이 {page}를 놓쳤다"
    assert stops >= 6, "셸·옛 대시보드·Fleet·게임·진단 정지를 모두 센다"


def test_the_scan_fires_when_the_attribute_is_removed():
    """Mutation proof on the real shell markup."""
    shell = (REPO / "src" / "hmi" / "dashboard" / "surface.html").read_text(encoding="utf-8")
    assert stops_in(shell) == [(25, True)]
    stripped = shell.replace(" data-always-live", "")
    assert stops_in(stripped) == [(25, False)]
    assert stops_in('<ui-button kind="irreversible">도크 삭제</ui-button>') == []
    assert stops_in('<ui-button kind="irreversible" aria-label="전체 로봇 정지"><span>전체</span></ui-button>') == [(1, False)]


# D-280 원칙 2 — `showModal()`은 대화상자 밖 문서 전체를 inert로 만들어 정지까지 막는다
# (2026-09-30 US-010, 2026-10-01 Fleet 등록 대화상자). 대화상자는 ui.js openLiveDialog로 연다.
SHOW_MODAL = re.compile(r"""\.\s*showModal\s*\(|\[\s*["']showModal["']\s*\]""")
WEB_SCRIPT_ROOTS = (
    REPO / "src" / "hmi" / "dashboard",
    REPO / "src" / "hmi" / "web_common",
    REPO / "src" / "hmi" / "pilot",
    REPO / "operations" / "fleet" / "fleet" / "server" / "web",
    REPO / "operations" / "apps" / "games" / "games" / "web",
)


def surface_scripts():
    for base in WEB_SCRIPT_ROOTS:
        for path in sorted(base.rglob("*.js")):
            parts = path.relative_to(base).parts
            if "test" in parts or "node_modules" in parts:
                continue
            yield path


def test_no_surface_script_opens_a_modal_dialog():
    scripts = list(surface_scripts())
    offenders = [f"{_rel(path)}:{text.count(chr(10), 0, match.start()) + 1}"
                 for path in scripts
                 for text in [path.read_text(encoding="utf-8")]
                 for match in SHOW_MODAL.finditer(text)]
    assert offenders == [], f"showModal()은 정지를 inert로 만든다 — ui.js openLiveDialog를 쓴다: {offenders}"
    names = {_rel(path) for path in scripts}
    for script in ("operations/fleet/fleet/server/web/enrollment.js", "operations/fleet/fleet/server/web/camera-pairing.js",
                   "src/hmi/web_common/ui.js", "src/hmi/pilot/app.js",
                   "src/hmi/dashboard/settings.js", "operations/apps/games/games/web/board.js"):
        assert script in names, f"스캔이 {script}를 놓쳤다"


def test_the_modal_scan_fires_on_the_old_enrollment_call():
    """Mutation proof: the 2026-10-01 Fleet enrollment call and its variants are caught."""
    for planted in ("if (dialog?.showModal) dialog.showModal();", "el('d')?.showModal()", "dialog['showModal']()"):
        assert SHOW_MODAL.search(planted), planted
    assert not SHOW_MODAL.search("// showModal()은 정지까지 inert로 만든다")
    assert not SHOW_MODAL.search("openLiveDialog(dialog, { initialFocus })")
