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
    "shared_controls": Path("src/hmi/web/test/test_shared_controls.py"),
    "typography_focus": Path("src/hmi/web/test/test_surface_typography_focus_contracts.py"),
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
