"""D-501 — the four Rosy Fleet documents share one tab row; each marks only itself as current."""

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[2] / "ui" / "console"
DOCS = {"index.html": "/console", "install.html": "/console/install",
        "site-map.html": "/console/site-map", "cell.html": "/console/cell"}
ORDER = ["/console", "/console/install", "/console/site-map", "/console?view=work", "/console/cell"]
ICONS = ["fleet", "install", "map", "history", "cell"]
# D-741 2·6: 아이콘 아래에 짧은 이름을 적는다. 긴 이름은 접근 이름에 남고 보이는 글을 품는다(WCAG 2.5.3).
LABELS = ["관제", "설치", "지도", "작업", "Cell"]
NAMES = [None, "설치·보정", "현장 지도", None, None]


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


def test_no_back_link_sentences_remain():
    for name in DOCS:
        page = _page(name).read_text(encoding="utf-8")
        assert "관제 화면으로 돌아가기" not in page and "install-nav" not in page and "topbar-link" not in page, name
