"""브라우저 제목 규칙.

- 앱(`surfaces.yaml`에 `app_name`이 있는 행): D-377 — 제목은 표시 이름 `Rosy <Word>`이고,
  한 앱 안의 여러 화면은 `Rosy <Word> — <화면 이름>`이다.
- 웹 전용 앱: D-806의 `title_prefix`를 쓴다. 런처·패키지 신원을 등록하지 않는다.
- 그 밖의 표면: D-339 §4 — `Rosy <범위> — <화면 이름>`. 범위는 `surface` 값에서 온다.

등록된 표면의 페이지(HTML 파일 하나, 또는 폴더 안의 `index.html`·`surface.html`)마다
`<title>`을 대조한다. 라이브러리(`web-common`)는 화면이 아니므로 뺀다.
"""

import re
from pathlib import Path

import pytest

import surface_registry as registry

SCOPE = {"robot": "로봇", "site": "사이트", "sim": "시뮬", "dev": "개발"}
LIBRARY = {"web-common"}
PAGES = (
    "index.html", "surface.html", "learning.html", "pixels.html", "catalog.html",
    "camera.html", "accounts.html", "login.html", "profile.html", "install.html",
    "site-map.html", "cell/cell.html", "work/policy.html",
)
TITLE = re.compile(r"<title>(.*?)</title>", re.S | re.I)


def _pages(row, root):
    path = root / row["path"]
    if path.suffix == ".html":
        return [path]
    return [path / name for name in PAGES if (path / name).is_file()]


def title_problems(rows=None, root=None):
    root = registry.REPO if root is None else Path(root)
    rows = registry.load(root) if rows is None else rows
    checked, wrong = 0, []
    pages = {page for row in rows if row.get('id') not in LIBRARY for page in _pages(row, root)}
    for page in sorted(pages):
        row = registry.owner_for_page(page, root, rows)
        scope = SCOPE.get(row.get("surface"))
        checked += 1
        match = TITLE.search(page.read_text(encoding="utf-8"))
        title = match.group(1).strip() if match else None
        app = row.get("app_name") or row.get("title_prefix")
        if app:
            prefix = f"{app} — "
            ok = title is not None and (title == app or title.startswith(prefix))
        else:
            prefix = f"Rosy {scope} — "
            ok = scope is not None and title is not None and title.startswith(prefix)
        if not ok:
            wrong.append(f"{page.relative_to(root).as_posix()}: {title!r} (want {prefix!r})")
    return checked, wrong


def test_every_registered_surface_title_names_its_scope():
    checked, wrong = title_problems()
    assert checked, "등록된 표면 페이지가 없다"
    assert wrong == [], wrong


def test_exact_account_surface_keeps_both_account_and_fleet_title_checks_strict(tmp_path):
    folder = tmp_path / 'web'
    folder.mkdir()
    business, identity = folder / 'index.html', folder / 'login.html'
    business.write_text('<title>Rosy Fleet — Work</title>', encoding='utf-8')
    identity.write_text('<title>Rosy Account — Login</title>', encoding='utf-8')
    rows = [{'id': 'fleet', 'path': 'web', 'app_name': 'Rosy Fleet'},
            {'id': 'account', 'path': 'web/login.html', 'title_prefix': 'Rosy Account'}]
    assert title_problems(rows, tmp_path) == (2, [])
    for page, incorrect in ((identity, 'Rosy Fleet — Login'), (business, 'Rosy Account — Work')):
        original = page.read_text(encoding='utf-8')
        page.write_text('<title>' + incorrect + '</title>', encoding='utf-8')
        checked, wrong = title_problems(rows, tmp_path)
        assert checked == 2 and len(wrong) == 1 and page.name in wrong[0]
        page.write_text(original, encoding='utf-8')
    with pytest.raises(ValueError, match='most-specific'):
        registry.owner_for_page(tmp_path / 'web-other/index.html', tmp_path, rows)
    with pytest.raises(ValueError, match='most-specific'):
        registry.owner_for_page(identity, tmp_path, [*rows, {**rows[-1], 'id': 'ambiguous'}])


def test_web_app_titles_do_not_register_launcher_identities():
    rows = {row["id"]: row for row in registry.load()}
    for ident, name in {"pinky-review": "Rosy Learning", "game-board": "Rosy Games",
                        "account-login": "Rosy Account", "account-profile": "Rosy Account",
                        "account-administration": "Rosy Account"}.items():
        assert rows[ident].get("title_prefix") == name
        assert "app_name" not in rows[ident]


def test_identity_documents_have_exact_account_ownership():
    rows = registry.load()
    for filename, ident in (("login.html", "account-login"), ("profile.html", "account-profile"),
                            ("accounts.html", "account-administration")):
        row = registry.owner_for_page(Path("applications/fleet/web") / filename, rows=rows)
        assert row["id"] == ident and row["api_owners"] == ["Account"]
        assert not {"app_name", "app_name_en", "short_name", "package", "icon"} & row.keys()
    owners = [row["id"] for row in rows if "account-management" in row.get("owns", [])]
    assert owners == ["account-administration"]
    assert registry.owner_for_page(Path("applications/fleet/web/index.html"), rows=rows)["id"] == "console"
