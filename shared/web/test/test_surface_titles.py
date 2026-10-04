"""브라우저 제목 규칙.

- 앱(`surfaces.yaml`에 `app_name`이 있는 행): D-377 — 제목은 표시 이름 `Rosy <Word>`이고,
  한 앱 안의 여러 화면은 `Rosy <Word> — <화면 이름>`이다.
- 그 밖의 표면: D-339 §4 — `Rosy <범위> — <화면 이름>`. 범위는 `surface` 값에서 온다.

등록된 표면의 페이지(HTML 파일 하나, 또는 폴더 안의 `index.html`·`surface.html`)마다
`<title>`을 대조한다. 라이브러리(`web-common`)는 화면이 아니므로 뺀다.
"""

import re

import surface_registry as registry

SCOPE = {"robot": "로봇", "site": "사이트", "sim": "시뮬", "dev": "개발"}
LIBRARY = {"web-common"}
PAGES = ("index.html", "surface.html", "learning.html", "pixels.html", "catalog.html")
TITLE = re.compile(r"<title>(.*?)</title>", re.S | re.I)


def _pages(row):
    path = registry.REPO / row["path"]
    if path.suffix == ".html":
        return [path]
    return [path / name for name in PAGES if (path / name).is_file()]


def test_every_registered_surface_title_names_its_scope():
    checked, wrong = 0, []
    for row in registry.load():
        if row.get("id") in LIBRARY:
            continue
        scope = SCOPE.get(row.get("surface"))
        for page in _pages(row):
            checked += 1
            match = TITLE.search(page.read_text(encoding="utf-8"))
            title = match.group(1).strip() if match else None
            app = row.get("app_name")
            if app:
                prefix = f"{app} — "
                ok = title is not None and (title == app or title.startswith(prefix))
            else:
                prefix = f"Rosy {scope} — "
                ok = scope is not None and title is not None and title.startswith(prefix)
            if not ok:
                wrong.append(f"{page.relative_to(registry.REPO).as_posix()}: {title!r} (want {prefix!r})")
    assert checked, "등록된 표면 페이지가 없다"
    assert wrong == [], wrong
