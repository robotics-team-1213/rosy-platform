"""D-501 — the four Rosy Fleet documents share one tab row; each marks only itself as current."""

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "fleet" / "server" / "web"
DOCS = {"index.html": "/console", "install.html": "/console/install",
        "site-map.html": "/console/site-map", "cell.html": "/console/cell"}
ORDER = ["/console", "/console/install", "/console/site-map", "/console/cell"]


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
    return page, re.findall(r'<a href="([^"]+)"( aria-current="page")?>', match.group(1))


def test_every_document_has_the_same_tabs_and_marks_itself():
    for name, current in DOCS.items():
        page, links = _tabs(name)
        assert [href for href, _ in links] == ORDER, name
        assert [href for href, cur in links if cur] == [current], name
        assert '/console/assets/doc-tabs.css' in page, name


def test_no_back_link_sentences_remain():
    for name in DOCS:
        page = _page(name).read_text(encoding="utf-8")
        assert "관제 화면으로 돌아가기" not in page and "install-nav" not in page and "topbar-link" not in page, name
