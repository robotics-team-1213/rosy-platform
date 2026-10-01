"""D-371 — a list row never carries the danger fill.

A list row (a repeated item in a `li`, `tr` or `[role=row]`) starts an
irreversible action with a quiet `삭제…`. The danger fill lives only on the
execute button of the shared confirm dialog (`confirmIrreversible` in ui.js).

Structural signal:
* HTML: no `ui-button kind="irreversible"` has a `li`, `tr`, `[role=row]`,
  `ul`, `ol` or `table` ancestor.
* JS: rows are built in script, so script may not mint an irreversible kind at
  all — only `confirmIrreversible` in ui.js does. Static E-stops and
  single-target commands are HTML (`index.html`, `surface.html`, Fleet, games).
* JS: a row delete is labelled `삭제…` (the ellipsis promises the dialog), never
  a bare `"삭제"`. The same holds for every verb in `IRREVERSIBLE_VERBS` (Fleet
  `등록 해제…` revokes the site token). The bare verb is allowed only as the
  `action:` of a `confirmIrreversible` call — that is the execute button.
* The dialog opens non-modal through `openLiveDialog` (ui.js).
"""

from html.parser import HTMLParser
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[3]
COMMON = ROOT / "hmi" / "web_common"
UI = COMMON / "ui.js"
WEB_ROOTS = (
    ROOT / "hmi" / "dashboard",
    COMMON,
    ROOT / "site" / "fleet" / "fleet" / "server" / "web",
    ROOT / "site" / "games" / "games" / "web",
)
ROW_TAGS = {"li", "tr", "ul", "ol", "table"}
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
SCRIPT_IRREVERSIBLE = re.compile(
    r"""setAttribute\(\s*["']kind["']\s*,\s*["']irreversible["']\s*\)"""
    r"""|kind\s*=\s*\\?["']irreversible|kind\s*:\s*["']irreversible["']|\.kind\s*=\s*["']irreversible["']"""
)
#: Row actions that cannot be undone from the same row. Add a verb here when a new one ships.
IRREVERSIBLE_VERBS = ("삭제", "등록 해제", "폐기", "초기화", "거절")
BARE_VERB = re.compile(
    r"""(?<!action:\s)(?<!action:)(["'`])(?:""" + "|".join(map(re.escape, IRREVERSIBLE_VERBS)) + r""")\1""")


def web_files(suffix):
    for base in WEB_ROOTS:
        for path in sorted(base.rglob(f"*{suffix}")):
            if "test" in path.relative_to(base).parts or "node_modules" in path.parts:
                continue
            yield path


class RowScan(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack = []
        self.hits = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "ui-button" and attrs.get("kind") == "irreversible":
            if any(name in ROW_TAGS or role == "row" for name, role in self.stack):
                self.hits.append(self.getpos()[0])
        if tag not in VOID:
            self.stack.append((tag, attrs.get("role")))

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break


def row_irreversible_in_html(text):
    scan = RowScan()
    scan.feed(text)
    return scan.hits


def test_no_irreversible_button_inside_a_list_row_in_html():
    offenders = []
    for path in web_files(".html"):
        offenders += [f"{path.relative_to(ROOT)}:{line}" for line in row_irreversible_in_html(path.read_text(encoding="utf-8"))]
    assert offenders == [], f"D-371: 목록 행 안의 위험 채움 버튼: {offenders}"


def test_only_the_shared_confirm_dialog_mints_an_irreversible_button_in_script():
    offenders = []
    for path in web_files(".js"):
        if path == UI:
            continue
        for match in SCRIPT_IRREVERSIBLE.finditer(path.read_text(encoding="utf-8")):
            offenders.append(f"{path.relative_to(ROOT)}: {match.group(0)}")
    assert offenders == [], (
        "D-371: 스크립트가 만든 행의 되돌릴 수 없는 버튼은 조용한 `삭제…`이고, 위험 채움은 "
        f"ui.js confirmIrreversible의 실행 버튼뿐이다: {offenders}"
    )
    source = UI.read_text(encoding="utf-8")
    body = source.split("export function confirmIrreversible", 1)[1].split("\n}\n", 1)[0]
    assert len(SCRIPT_IRREVERSIBLE.findall(body)) == 1, "확인 대화상자의 위험 채움은 실행 버튼 하나다"
    assert 'setAttribute("kind", "quiet")' in body, "취소는 조용한 버튼이다"
    assert "openLiveDialog(dialog" in body, "확인 대화상자도 공용 비모달 열기를 지난다"
    live = source.split("export function openLiveDialog", 1)[1].split("\n}\n", 1)[0]
    assert "showModal(" not in live and "dialog.show()" in live, (
        "비모달로 연다 — showModal()은 비상정지까지 inert로 만든다(2026-09-30 US-010 측정)")


def test_row_delete_buttons_promise_the_dialog_with_an_ellipsis():
    offenders = []
    for path in web_files(".js"):
        text = path.read_text(encoding="utf-8")
        offenders += [f"{path.relative_to(ROOT)}:{text.count(chr(10), 0, m.start()) + 1}" for m in BARE_VERB.finditer(text)]
    assert offenders == [], f"D-371: 되돌릴 수 없는 행 행동은 `삭제…`·`등록 해제…`로 다음 단계를 알린다: {offenders}"


def test_every_confirm_irreversible_call_names_its_target_and_asks():
    calls = 0
    for path in web_files(".js"):
        if path == UI:
            continue
        for message in re.findall(r"confirmIrreversible\(\{\s*message:\s*`([^`]*)`", path.read_text(encoding="utf-8")):
            calls += 1
            assert '"${' in message, f"{path.name}: 대상 이름을 따옴표로 말한다: {message}"
            assert "까요" in message, f"{path.name}: D-218 — 결과를 묻는다: {message}"
    assert calls >= 5, "토큰·도크(/device 두 패널, 옛 /dashboard 셋) 삭제가 모두 대화상자를 지난다"


def test_the_structural_scans_catch_what_they_forbid():
    """Mutation proof kept in the suite: each scan fires on a planted violation."""
    assert row_irreversible_in_html('<ul><li>x <ui-button kind="irreversible">삭제</ui-button></li></ul>') == [1]
    assert row_irreversible_in_html('<div role="row"><ui-button kind="irreversible">x</ui-button></div>') == [1]
    assert row_irreversible_in_html('<ui-topbar><ui-button kind="irreversible">비상 정지</ui-button></ui-topbar>') == []
    assert SCRIPT_IRREVERSIBLE.search('remove.setAttribute("kind", "irreversible");')
    assert SCRIPT_IRREVERSIBLE.search('row.innerHTML = `<ui-button kind="irreversible">`')
    for verb in IRREVERSIBLE_VERBS:
        assert BARE_VERB.search(f'el("ui-button", "", "{verb}")'), verb
        assert BARE_VERB.search(f'button(a ? "옮기기" : "{verb}", run)'), verb
        assert not BARE_VERB.search(f'el("ui-button", "", "{verb}…")'), verb
        assert not BARE_VERB.search(f'confirmIrreversible({{message: m, action: "{verb}"}})'), verb
    # the real regression: Fleet enrollment's quiet row button loses its ellipsis
    fleet = (ROOT / "site" / "fleet" / "fleet" / "server" / "web" / "enrollment.js").read_text(encoding="utf-8")
    assert '"등록 해제…"' in fleet and not BARE_VERB.search(fleet)
    assert BARE_VERB.search(fleet.replace('"등록 해제…"', '"등록 해제"', 1))
