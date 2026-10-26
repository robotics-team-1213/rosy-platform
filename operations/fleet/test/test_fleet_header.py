"""D-540 2 — the four Rosy Fleet documents carry one header, letter for letter, driven by one module."""

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[3] / 'applications/fleet/web'
DOCS = {"index.html": "console.js", "installation/install.html": "installation/install.js",
        "sitemap/site-map.html": "sitemap/site-map.js", "cell/cell.html": "cell/cell.js"}


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
                           "fleet-theme", "development-badge", "topbar-more", "topbar-extra", "estop",
                           "clock", "link-state", "fleet-inbox", "header-unread", "fleet-login",
                           "fleet-account", "fleet-account-identity", "fleet-profile", "fleet-name"):
            assert f'id="{element_id}"' in header, (name, element_id)
        # D-741 3: 로봇 연결 수는 앱 바가 아니라 관제 화면의 내용이다.
        assert 'id="online-pill"' not in header, name
        assert page.count('id="online-pill"') == (1 if name == "index.html" else 0), name
        # The old site-map/Cell identity row is gone; one id names one thing on every document.
        for retired in ('id="session"', 'id="credential"', 'id="connect"', "site-access", "cell-access"):
            assert retired not in page, (name, retired)
        assert page.count('id="estop"') == 1, name
        assert 'class="fleet-shell"' in page and 'class="fleet-workspace"' in page, name
        # D-741 3: 푸터는 없다. 시계는 앱 바의 연결 자리에 있고, 푸터의 알림 링크는 머리의 알림 단추가 대신한다.
        assert "<footer" not in page and "fleet-footer" not in page and "관제 알림" not in page, name
        status = header.split('data-header-region="status"', 1)[1].split('data-header-region="actions"', 1)[0]
        assert status.index('id="link-state"') < status.index('id="clock"'), name
        assert '/console/assets/fleet-header.css' in page, name


def test_header_regions_keep_identity_status_actions_and_safety_separate():
    _, header = _header("index.html")
    assert re.findall(r'data-header-region="([^"]+)"', header) == [
        "identity", "status", "actions", "safety"]
    assert 'id="fleet-header-actions"' in header
    # D-741 3: 연결 자리에는 조작이 없다. 알림, 로그인, 나(계정 단추) 순서로 정지 앞에 선다.
    status = header.split('data-header-region="status"', 1)[1].split('data-header-region="actions"', 1)[0]
    assert 'id="link-state"' in status and 'id="clock"' in status and "<ui-button" not in status
    actions = header.split('data-header-region="actions"', 1)[1].split('data-header-region="safety"', 1)[0]
    assert actions.index('id="fleet-inbox"') < actions.index('id="fleet-login"') < actions.index('id="topbar-more"')
    inbox = re.search(r'<ui-button[^>]*id="fleet-inbox".*?</ui-button>', header, re.S).group(0)
    assert 'id="header-unread"' in inbox and 'data-action-icon="notification"' in inbox
    entry = re.search(r'<ui-button[^>]*id="topbar-more".*?</ui-button>', header, re.S).group(0)
    for element_id in ("user-role", "development-badge"):
        assert f'id="{element_id}"' in entry
    assert entry.count("<ui-button") == 1 and 'data-action-icon="account"' in entry
    assert 'aria-controls="topbar-extra"' in entry
    assert header.index('data-header-region="safety"') < header.index('id="topbar-extra"')
    menu = header.split('id="topbar-extra"', 1)[1]
    for element_id in ("fleet-account", "password-login", "fleet-theme", "token-access", "console-token", "token-save"):
        assert f'id="{element_id}"' in menu, element_id
    assert "<details id=\"fleet-account\"" not in header, "계정 정보는 계정 단추 하나 아래에 있다"
    controller = (WEB / "shared/fleet-header.js").read_text(encoding="utf-8")
    assert "createElement(\"ui-button\")" not in controller, "알림 단추는 정적 마크업이다(D-658 5항)"


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
    for entry in ("console.js", "installation/install.js"):
        assert "ui-button:not(#estop)" in (WEB / entry).read_text(encoding="utf-8"), entry


def test_document_sheets_do_not_paint_the_header():
    header_sheet = (WEB / "shared/fleet-header.css").read_text(encoding="utf-8")
    assert "body { margin: 0; }" in header_sheet
    assert ".fleet-header { position: sticky; top: 0;" in header_sheet
    for sheet in ("shared/styles.css", "sitemap/site-map.css", "cell/cell.css"):
        body = (WEB / sheet).read_text(encoding="utf-8")
        assert "ui-topbar" not in body and ".estop" not in body and "#topbar-more" not in body, sheet
    assert ".fleet-footer" not in (WEB / "shared/doc-tabs.css").read_text(encoding="utf-8")


def test_app_bar_folds_by_the_shell_container_not_the_viewport():
    """D-741 5 / D-359 §6.3 — 접힘은 셸 칸의 폭에 답한다. 앱 바 높이는 공용 자리 토큰이다."""
    header_sheet = (WEB / "shared/fleet-header.css").read_text(encoding="utf-8")
    tabs_sheet = (WEB / "shared/doc-tabs.css").read_text(encoding="utf-8")
    assert "@media" not in header_sheet
    assert set(re.findall(r"@container \(([^)]+)\)", header_sheet)) == {
        "width < 64rem", "width < 48rem", "width < 30rem"}
    assert "container-type" not in header_sheet, "칸은 셸 하나다"
    assert ".fleet-shell { container-type: inline-size;" in tabs_sheet
    assert tabs_sheet.count("container-type") == 1
    assert re.findall(r"@media ([^{]+?)\s*\{", tabs_sheet) == ["(width >= 64rem) and (height >= 40rem)"]
    # The shared ui-topbar carries the D-741 app bar height; Fleet does not restate it.
    shared = (WEB.parents[2] / "shared/web/components.css").read_text(encoding="utf-8")
    assert "min-height: var(--appbar-height);" in shared.split("ui-topbar {", 1)[1].split("}", 1)[0]
    assert "min-height" not in header_sheet.split("ui-topbar {", 1)[1].split("}", 1)[0]
    assert "var(--rail-track)" in tabs_sheet
