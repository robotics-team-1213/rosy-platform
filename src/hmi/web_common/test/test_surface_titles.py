"""D-338 §4 브라우저 제목 규칙: `Rosy <범위> — <화면 이름>`.

범위는 `surfaces.yaml`의 `surface` 값에서 온다. 등록된 표면의 페이지
(HTML 파일 하나, 또는 폴더 안의 `index.html`·`surface.html`)마다 `<title>`을
대조한다. 라이브러리(`web-common`)는 화면이 아니므로 뺀다.
"""

import re

import surface_registry as registry

SCOPE = {"robot": "로봇", "site": "사이트", "sim": "시뮬"}
LIBRARY = {"web-common"}
PAGES = ("index.html", "surface.html")
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
            prefix = f"Rosy {scope} — "
            if scope is None or title is None or not title.startswith(prefix):
                wrong.append(f"{page.relative_to(registry.REPO).as_posix()}: {title!r} (want {prefix!r})")
    assert checked, "등록된 표면 페이지가 없다"
    assert wrong == [], wrong
