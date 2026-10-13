"""D-501 / D-741 2·6 — the four Rosy Fleet documents share one rail of five areas; each marks only its own area."""

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[2] / 'site_ui' / 'console'
DOCS = {"index.html": "/console", "install.html": "/console/install",
        "site-map.html": "/console/site-map", "cell.html": "/console?view=work"}  # D-741 7: Cell은 작업 영역이다
ORDER = ["/console", "/console?view=work", "/console?view=records", "/console/site-map", "/console/install"]
ICONS = ["fleet", "list", "history", "map", "install"]
# D-741 2·6: 아이콘 아래에 짧은 이름을 적는다. 긴 이름은 접근 이름에 남고 보이는 글을 품는다(WCAG 2.5.3).
LABELS = ["관제", "작업", "기록", "지도", "설치"]
NAMES = [None, None, None, "현장 지도", "설치·보정"]
# D-741 6: 화면 안 이동은 공용 하위 탐색 자리에 선다. 가로 앵커 줄은 없다.
SUBNAV = {"site-map.html": ("현장 지도 작업", ["map", "survey", "profile", "trip", "run", "edit", "teach"]),
          "cell.html": ("Cell 작업 단계", ["recipe", "cell", "preview", "proposal", "mission", "saved"])}


def _page(name):
    for folder in ("cell",):
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
        page = _page(name).read_text(encoding="utf-8")
        seat = re.search(r'</nav>\s*<div class="ui-subnav"><nav class="ui-subnav-nav" aria-label="%s">(.*?)</nav></div>\s*'
                         r'<div class="fleet-workspace">' % label, page, re.S)
        assert seat, f"{name}: the sub-nav seat stands between the rail and the workspace"
        assert re.findall(r'<a class="ui-subnav-item" href="#([\w-]+)-heading">', seat.group(1)) == targets, name
        assert all(f'id="{target}-heading"' in page for target in targets), name
        assert "task-nav" not in page and '<link rel="stylesheet" href="/common/app-shell.css">' in page, name
    sheet = (WEB / "shared/doc-tabs.css").read_text(encoding="utf-8")
    assert "task-nav" not in sheet and "var(--rail-track) var(--subnav-track) minmax(0, 1fr)" in sheet


def test_no_back_link_sentences_remain():
    for name in DOCS:
        page = _page(name).read_text(encoding="utf-8")
        assert "관제 화면으로 돌아가기" not in page and "install-nav" not in page and "topbar-link" not in page, name
