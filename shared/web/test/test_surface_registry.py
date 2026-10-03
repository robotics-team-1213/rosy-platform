"""D-329 표면 레지스트리 계약.

표면 계약 적용 범위의 단일 출처는 `surfaces.yaml`다. 이 시험은 두 가지를 지킨다:
등록되지 않은 표면이 있으면 빨갛게 되고, 세 계약 시험이 목록을 다시 손으로 적지
않는다. 판정 규칙 자체는 `surface_registry.problems()`에 있고 여기는 규칙별로
걸러 대조한다 — 빨개지면 접두사가 무엇을 어겼는지 말해준다.
"""

import re
from pathlib import Path

import pytest

import surface_registry as registry

REPO = registry.REPO

#: D-329 계약 시험은 이 셋에서 표면 목록을 읽는다. 여기가 손으로 적힌 자리다.
CONSUMERS = {
    "shared_controls": Path("shared/web/test/test_shared_controls.py"),
    "typography_focus": Path("shared/web/test/test_surface_typography_focus_contracts.py"),
    "dialog": Path("test/test_web_dialog_contract.py"),
}

#: 계약을 다시 적는 상수. 이 이름으로 목록을 만들면 시험이 빨갛다.
RESTATE = re.compile(r"^\s*SURFACES\s*=", re.M)


def _under(scope: str) -> list[str]:
    return registry.problems_with(REPO, scope)


def test_registered_paths_exist():
    assert _under("path") == []


def test_registry_values_stay_in_their_domains():
    assert _under("value") == []
    assert _under("shape") == []


def test_a_dropped_contract_or_baseline_is_explained():
    """이유 없는 빈 칸은 등록되지 않는다 — 구멍을 눈에 보이게 하는 쪽이다."""
    assert _under("reason") == []


def test_declared_baselines_are_tracked():
    assert _under("baseline") == []


def test_every_html_under_src_is_registered():
    """추적 파일과 아직 add하지 않은 파일을 모두 잡는다.

    파일시스템 `rglob`을 쓰면 `.gitignore`된 빌드 산출물이 들어오고,
    `git ls-files -c`만 쓰면 아직 add하지 않은 새 표면이 빠진다.
    """
    if not registry.git_available(REPO):
        pytest.skip("D-329 발견 스캔은 git 체크아웃이 필요하다")

    registered = [row["path"] for row in registry.load(REPO)]
    orphans = []
    for page in registry.discover_html(REPO):
        here = page.relative_to(REPO).as_posix()
        if not any(here == path or here.startswith(path.rstrip("/") + "/") for path in registered):
            orphans.append(here)
    assert orphans == [], (
        "src/의 HTML이 레지스트리에 없다 — 표면을 등록하거나 이 파일에서 제외 사유를 적어라:\n"
        + "\n".join(orphans)
    )


def test_contract_consumers_read_the_registry_not_a_literal():
    """세 시험은 목록을 다시 적지 않는다 — 레지스트리에서만 읽는다."""
    offending = []
    for name, relative in CONSUMERS.items():
        text = (REPO / relative).read_text(encoding="utf-8")
        if RESTATE.search(text):
            offending.append(f"{relative} 가 표면 목록 상수를 다시 정의한다")
        if "for_contract(" not in text:
            offending.append(f"{relative} 가 레지스트리에서 읽지 않는다")
        if f'"{name}"' not in text:
            offending.append(f"{relative} 가 자기 계약 이름 {name} 으로 읽지 않는다")
    assert offending == [], offending


def test_the_grammar_source_is_readable():
    """GRAMMARS가 ui.js에 없으면 grammar 검사가 공허해진다 — 여기서 먼저 잡는다."""
    assert registry.grammars(REPO), "web_common/ui.js 가 GRAMMARS 를 선언하지 않는다"


def test_for_contract_returns_registered_paths_in_order():
    """계약별 목록이 등록 순서를 그대로 따른다 — 판정이 아니라 경로 형태의 계약."""
    dialog = registry.for_contract(REPO, "dialog")
    registered = [row["path"] for row in registry.load(REPO) if "dialog" in row["contracts"]]
    assert [path.relative_to(REPO).as_posix() for path in dialog] == registered


def test_a_file_surface_is_returned_as_a_file_not_walked():
    """진단 표면은 파일 하나다 — 로더가 폴더로 착각해 안을 훑지 않는다."""
    diagnostic = registry.for_contract(REPO, "shared_controls")
    file_surfaces = [path for path in diagnostic if path.suffix == ".html"]
    assert file_surfaces, "파이 경로 표면이 등록돼 있지 않다"
    assert all(path.is_file() for path in file_surfaces)


def test_registered_ports_match_their_source_and_do_not_collide():
    assert _under("port") == []


def test_a_surface_without_role_or_owns_is_not_registered(tmp_path):
    """D-370 1·4항: 역할 한 줄과 소유 목록이 빈 칸이면 레지스트리가 빨개진다."""
    (tmp_path / "shared" / "web").mkdir(parents=True)
    (tmp_path / "shared" / "web" / "ui.js").write_text(
        "const GRAMMARS = ['spatial'];", encoding="utf-8")
    (tmp_path / "a").mkdir()
    row = ("  - id: {id}\n    path: a\n    surface: site\n    medium: web\n"
           "    audience: x\n    contracts: [shared_controls, typography_focus, dialog]\n"
           "    baseline_reason: x\n{extra}")
    (tmp_path / registry.REGISTRY).write_text(
        "surfaces:\n"
        + row.format(id="bare", extra="")
        + row.format(id="blank", extra="    role: ' '\n    owns: [estop, estop, {id: teleop}]\n")
        + row.format(id="good", extra="    role: x\n    owns: [{id: teleop, transitional: y}]\n"),
        encoding="utf-8")
    found = registry.problems_with(tmp_path, "value")
    assert any("(bare)에 한 줄짜리 role이 없다" in line for line in found)
    assert any("(bare)에 owns 목록이 없다" in line for line in found)
    assert any("(blank)에 한 줄짜리 role이 없다" in line for line in found)
    assert any("(blank) owns에 중복이 있다" in line for line in found)
    assert any("(blank) owns teleop이(가) 표이지만 transitional 사유가 없다" in line
               for line in found)
    assert not any("(good)" in line for line in found)


def test_a_port_collision_or_drift_is_caught(tmp_path):
    """새 표면이 이미 쓰는 포트를 고르거나 기본값이 바뀌면 레지스트리가 빨개진다."""
    (tmp_path / "shared" / "web").mkdir(parents=True)
    (tmp_path / "shared" / "web" / "ui.js").write_text(
        "const GRAMMARS = ['spatial'];", encoding="utf-8")
    (tmp_path / "a.py").write_text("default=8090", encoding="utf-8")
    (tmp_path / "b.py").write_text("default=18090", encoding="utf-8")
    row = ("  - id: {id}\n    path: {src}\n    surface: site\n    medium: web\n"
           "    audience: x\n    contracts: [shared_controls, typography_focus, dialog]\n"
           "    baseline_reason: x\n    ports:\n      - {{port: 8090, source: {src}}}\n")
    (tmp_path / registry.REGISTRY).write_text(
        "surfaces:\n" + row.format(id="one", src="a.py") + row.format(id="two", src="b.py"),
        encoding="utf-8")
    found = registry.problems_with(tmp_path, "port")
    assert any("(two)의 8090를 one도 쓴다" in line for line in found)
    assert any("8090가 source b.py의 기본값에 없다" in line for line in found)


def test_every_surface_declares_its_themes_and_its_pages_follow_them():
    """D-359 §2·§3.3·§7.3 — themes 값, 테마 표면의 theme.js, 고정 표면의 pin,
    정적 theme-color = dark --ground, 표면 CSS에 color-scheme 없음."""
    assert _under("theme") == []


def test_a_theme_drift_is_caught(tmp_path):
    """고정 표면의 pin 누락, 테마 표면의 theme.js 누락, 틀린 theme-color·값이 빨갛다."""
    common = tmp_path / "shared" / "web"
    common.mkdir(parents=True)
    (common / "ui.js").write_text("const GRAMMARS = ['spatial'];", encoding="utf-8")
    (common / "tokens.css").write_text(
        ':root, [data-theme="dark"] { --ground: #101214; }\n', encoding="utf-8")
    (tmp_path / "pinned.html").write_text('<html lang="ko"><head></head></html>', encoding="utf-8")
    (tmp_path / "themed").mkdir()
    (tmp_path / "themed" / "index.html").write_text(
        '<html><head><meta name="theme-color" content="#111614">'
        '<link rel="stylesheet" href="/common/tokens.css"></head></html>', encoding="utf-8")
    (tmp_path / "themed" / "styles.css").write_text(":root { color-scheme: dark; }", encoding="utf-8")
    row = ("  - id: {id}\n    path: {path}\n    themes: {themes}\n    surface: site\n"
           "    medium: {medium}\n    audience: x\n    contracts: []\n    contract_reason: x\n"
           "    baseline_reason: x\n")
    (tmp_path / registry.REGISTRY).write_text(
        "surfaces:\n"
        + row.format(id="pin", path="pinned.html", themes="[dark]", medium="web")
        + row.format(id="themed", path="themed", themes="[dark, light]", medium="web")
        + row.format(id="lcd", path="pinned.html", themes="[dark, light]", medium="lcd")
        + row.format(id="odd", path="pinned.html", themes="[light, sepia]", medium="web"),
        encoding="utf-8")
    found = "\n".join(registry.problems_with(tmp_path, "theme"))
    assert 'pinned.html가 [dark] 표면인데 <html data-theme-pin="dark">가 없다' in found
    assert "themed/index.html가 tokens.css 바로 뒤에 /common/theme.js를 싣지 않는다" in found
    assert "정적 theme-color #111614가 dark --ground #101214가 아니다" in found
    assert "themed/styles.css가 color-scheme을 선언한다" in found
    assert "(lcd)는 웹이 아닌 사본이라 [dark]에 고정한다" in found
    assert "(odd) themes가" in found and "(odd) themes의 첫 값(기본)이 dark가 아니다" in found
    # P2-5 review: a pinned web surface says why it does not follow the theme
    assert "(pin)는 [dark] 고정 웹 표면인데 theme_reason이 없다" in found
    assert "(themed)는 [dark] 고정" not in found and "(lcd)는 [dark] 고정 웹 표면" not in found
