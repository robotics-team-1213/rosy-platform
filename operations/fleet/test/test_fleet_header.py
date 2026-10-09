"""D-540 2 — the four Rosy Fleet documents carry one header, letter for letter, driven by one module."""

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "fleet" / "server" / "web"
DOCS = {"index.html": "console.js", "install.html": "install.js",
        "site-map.html": "site-map.js", "cell/cell.html": "cell/cell.js"}


def _header(name):
    page = (WEB / name).read_text(encoding="utf-8")
    match = re.search(r"<ui-topbar>.*?</ui-topbar>", page, re.S)
    assert match, f"{name} has no ui-topbar"
    return page, match.group(0)


def test_four_documents_share_one_header():
    headers = {name: _header(name)[1] for name in DOCS}
    first = headers["index.html"]
    for name, header in headers.items():
        assert header == first, f"{name} header differs from the console header"


def test_header_ids_and_one_sheet():
    for name in DOCS:
        page, header = _header(name)
        for element_id in ("console-token", "token-save", "user-role", "password-login", "token-access",
                           "theme-choice", "development-badge", "online-pill", "clock", "topbar-more", "estop"):
            assert f'id="{element_id}"' in header, (name, element_id)
        # The old site-map/Cell identity row is gone; one id names one thing on every document.
        for retired in ('id="session"', 'id="credential"', 'id="connect"', "site-access", "cell-access"):
            assert retired not in page, (name, retired)
        assert page.count('id="estop"') == 1, name
        assert '/console/assets/fleet-header.css' in page, name


def test_estop_is_live_in_markup_and_one_module_gates_it():
    """No document ships a disabled E-stop: only fleet-header.js locks it, after a refused session."""
    _, header = _header("index.html")
    estop = re.search(r"<ui-button[^>]*id=\"estop\"[^>]*>", header).group(0)
    assert "disabled" not in estop and "reason=" not in estop and "data-always-live" in estop
    for entry in DOCS.values():
        source = (WEB / entry).read_text(encoding="utf-8")
        assert "/console/assets/fleet-header.js" in source, entry
        assert "bindEstop(" in source, entry
        assert "'/api/fleet/estop'" not in source and '"/api/fleet/estop"' not in source, entry
        assert "gate('estop'" not in source, entry
    for entry in ("console.js", "install.js"):
        assert "ui-button:not(#estop)" in (WEB / entry).read_text(encoding="utf-8"), entry


def test_document_sheets_do_not_paint_the_header():
    for sheet in ("shared/styles.css", "site-map.css", "cell/cell.css"):
        body = (WEB / sheet).read_text(encoding="utf-8")
        assert "ui-topbar" not in body and ".estop" not in body and "#topbar-more" not in body, sheet
