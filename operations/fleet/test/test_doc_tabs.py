"""D-501 / D-741 2·6 — the four Rosy Fleet documents share one rail of five areas; each marks only its own area."""

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[3] / 'applications/fleet/web'
DOCS = {"index.html": "/console", "install.html": "/console/install",
        "site-map.html": "/console/site-map", "cell.html": "/console?view=work",  # D-741 7: Cell은 작업 영역이다
        "policy.html": "/console?view=work"}  # D-926 2: 학습 정책 승인도 작업 영역이다
ORDER = ["/console", "/console?view=work", "/console?view=records", "/console/site-map", "/console/install"]
ICONS = ["fleet", "list", "history", "map", "install"]
# D-741 2·6: 아이콘 아래에 짧은 이름을 적는다. 긴 이름은 접근 이름에 남고 보이는 글을 품는다(WCAG 2.5.3).
LABELS = ["관제", "작업", "기록", "지도", "설치"]
NAMES = [None, None, None, "현장 지도", "설치·보정"]
# D-741 6: 화면 안 이동은 공용 하위 탐색 자리에 선다. 가로 앵커 줄은 없다.
SUBNAV = {"site-map.html": ("현장 지도 작업", ["map", "survey", "profile", "trip", "run", "edit", "teach"]),
          "cell.html": ("작업 화면", ["saved", "recipe", "cell", "preview", "proposal", "mission"])}


def _page(name):
    for folder in ("cell", "installation", "sitemap", "work"):
        path = WEB / folder / name
        if path.is_file():
            return path
    return WEB / name


def _tabs(name):
    page = _page(name).read_text(encoding="utf-8")
    match = re.search(r'<nav class="doc-tabs" aria-label="Rosy Fleet 문서">(.*?)</nav>', page, re.S)
    assert match, f"{name} has no doc-tabs row"
    links = [dict(re.findall(r'([\w-]+)="([^"]*)"', attributes), text=text)
             for attributes, text in re.findall(r'<a\b([^>]*)>(.*?)</a>', match.group(1))]
    return page, links


def test_every_document_has_the_same_tabs_and_marks_itself():
    for name, current in DOCS.items():
        page, links = _tabs(name)
        assert [link["href"] for link in links] == ORDER, name
        assert [link["href"] for link in links if link.get("aria-current") == "page"] == [current], name
        assert [link.get("data-action-icon") for link in links] == ICONS, name
        assert all("data-icon-only" not in link for link in links), name
        assert [link["text"] for link in links] == LABELS, name
        assert [link.get("aria-label") for link in links] == NAMES, name
        assert all(label in (link.get("aria-label") or label) for link, label in zip(links, LABELS)), name
        assert '/console/assets/doc-tabs.css' in page, name


def test_in_page_anchors_sit_in_the_shared_subnav_seat():
    for name, (label, targets) in SUBNAV.items():
        page = re.sub(r'<!--.*?-->', '', _page(name).read_text(encoding="utf-8"), flags=re.S)
        seat = re.search(r'</nav>\s*<div class="ui-subnav"><nav class="ui-subnav-nav" aria-label="%s">(.*?)</nav></div>\s*'
                         r'<div class="fleet-workspace">' % label, page, re.S)
        assert seat, f"{name}: the sub-nav seat stands between the rail and the workspace"
        assert re.findall(r'<a class="ui-subnav-item" href="#([\w-]+)-heading">', seat.group(1)) == targets, name
        assert all(f'id="{target}-heading"' in page for target in targets), name
        assert "task-nav" not in page and '<link rel="stylesheet" href="/common/app-shell.css">' in page, name
    sheet = (WEB / "shared/doc-tabs.css").read_text(encoding="utf-8")
    assert "task-nav" not in sheet and "var(--rail-track) var(--subnav-track) minmax(0, 1fr)" in sheet


def test_work_area_screens_are_the_same_subnav_in_the_console_and_cell():
    """D-741 7 / D-763 9 — 전체 작업·승인 대기·끝난 작업·새 작업. 새 작업은 종류 목록이고 Cell 문서는 그 아래에 놓인다."""
    screens = [("/console?view=work", "전체 작업"), ("/console?view=work&amp;show=pending", "승인 대기"),
               ("/console?view=work&amp;show=done", "끝난 작업"), ("/console?view=work&amp;show=new", "새 작업"),
               ("/console/learning", "학습")]
    for name, opening, current in (("index.html", '<div class="ui-subnav" data-area="work" hidden>', []),
                                   ("cell.html", '<div class="ui-subnav">', ["/console?view=work&amp;show=new"]),
                                   ("policy.html", '<div class="ui-subnav">', ["/console/learning"])):
        page = _page(name).read_text(encoding="utf-8")
        seat = re.search(re.escape(opening) + r'<nav class="ui-subnav-nav" aria-label="작업 화면">(.*?)</nav></div>', page, re.S)
        assert seat, name
        links = re.findall(r'<a class="ui-subnav-item" href="(/console[^"#]*)"( aria-current="page")?>(.*?)</a>', seat.group(1))
        assert [(href, text) for href, _, text in links] == screens, name
        assert [href for href, mark, _ in links if mark] == current, name
    # D-763 9: 종류는 실행할 수 있을 때만 선다. 이동은 꺼진 단추가 아니라 숨은 항목이고, Cell 적재는 /console/cell이다.
    kinds = re.search(r'<ul class="work-list" aria-label="새 작업 종류">(.*?)</ul>', _page("index.html").read_text(encoding="utf-8"), re.S)
    assert kinds and '<li id="work-new-move-item" hidden><ui-button kind="toggle" id="work-new-move"' in kinds.group(1)
    assert re.findall(r'<a [^>]*href="([^"]+)">(.*?)</a>', kinds.group(1)) == [("/console/cell", "Cell 적재")]
    assert "disabled" not in kinds.group(1) and 'id="work-kind"' not in _page("cell.html").read_text(encoding="utf-8")
    work_view = (WEB / "work" / "work-view.js").read_text(encoding="utf-8")
    assert 'pending: ["approval_pending"]' in work_view and "doc-tabs" not in work_view


def test_records_area_screens_and_the_judgment_seat():
    """D-741 8 — 사건 셋, AI 상황 사실, 관제 기록. 연 사건의 원인과 조치는 오른쪽 칸의 자리에 선다."""
    page = _page("index.html").read_text(encoding="utf-8")
    seat = re.search(r'<div class="ui-subnav" data-area="records" hidden><nav class="ui-subnav-nav" aria-label="기록 화면">'
                     r'(.*?)</nav></div>', page, re.S)
    assert seat, "the records sub-nav is hidden until the address picks the area"
    assert re.findall(r'<(?:a class="ui-subnav-item" href="(/console\?view=records[^"]*)"|span class="ui-subnav-head")>(.*?)</', seat.group(1)) == [
        ("", "사건"), ("/console?view=records", "검토할 사건"), ("/console?view=records&amp;show=open", "열린 사건"),
        ("/console?view=records&amp;show=closed", "닫힌 사건"), ("", "AI 판단"),
        ("/console?view=records&amp;show=facts", "AI 상황 사실"), ("/console?view=records&amp;show=log", "관제 기록")]
    evidence = page[page.index('id="context-evidence"'):]
    assert evidence.index('class="panel incident-panel"') < evidence.index('id="incident-side"') < evidence.index('id="incident-judgment"')
    view = (WEB / "incident-view.js").read_text(encoding="utf-8")
    assert "/api/fleet/incidents?limit=${records ? 100 : 10}" in view, "the records area reads the same incident API"
    assert "details name" not in view and "detail.name" not in view, "one open fold is kept in script, not by <details name>"
    assert 'querySelectorAll(".incident-row > details[open]")) if (other !== detail) other.open = false;' in view


def test_no_back_link_sentences_remain():
    for name in DOCS:
        page = _page(name).read_text(encoding="utf-8")
        assert "관제 화면으로 돌아가기" not in page and "install-nav" not in page and "topbar-link" not in page, name
