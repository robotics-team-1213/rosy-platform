"""D-178 모듈 병렬 유지보수 평가표 — 산출 규칙만 검사한다 (D-178 Validation).

기준선의 점수 값은 회차 입력이라 이 시험이 고정하지 않는다 — 주관 채점은 ADR 표와
저장소 밖 채점표(`module-coupling-scorecard.md`)가 소유한다. 고정하고 재계산하는 것은
산출 규칙뿐이다:

- 가중치 합 100, ``총점 = Σ(축 점수 × 가중치) ÷ 5``
- 등급 구간(ADR 구간 표)과 컷 게이트 — M5≤2 또는 M3≤2 → 상한 B, M2≤2 → 상한 C,
  S는 M3≥4 · M5≥4 (자격 미달이면 상한 A), 구간과 게이트는 낮은 쪽이 이긴다
- 패키지 집합 동일성 — 새 패키지 = 기준선 누락 = 적색 (D-168 스타일)

근거 ADR: ``docs/adr/D-178-module-maintainability-scorecard.md``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
AXES = ("M1", "M2", "M3", "M4", "M5")
RANK = {"D": 0, "C": 1, "B": 2, "A": 3, "S": 4}


def _read(path: Path) -> str:
    # utf-8-sig: 저장소에 BOM이 실려도 표 파싱이 죽지 않는다 (2026-09-23 BOM 결함 선례).
    return path.read_text(encoding="utf-8-sig")


def _adr_path() -> Path:
    files = sorted((REPO / "docs" / "adr").glob("D-178-*.md"))
    assert files, f"D-178 ADR not found under {REPO / 'docs' / 'adr'}"
    return files[0]


def _rows(text: str):
    for line in text.splitlines():
        line = line.lstrip()  # Decision 안의 표는 들여쓰기돼 있다
        if line.startswith("|"):
            yield [cell.strip() for cell in line.strip().strip("|").split("|")]


def _cap(scores: list[int]) -> int:
    """컷 게이트 (D-178 Decision 2): 허용되는 최고 등급 순위."""
    _, m2, m3, _, m5 = scores
    cap = RANK["S"]
    if m5 <= 2 or m3 <= 2:
        cap = min(cap, RANK["B"])
    if m2 <= 2:
        cap = min(cap, RANK["C"])
    if m3 < 4 or m5 < 4:
        cap = min(cap, RANK["A"])  # S 자격(M3·M5 ≥ 4) 미달 → 최대 A
    return cap


def _total(scores: list[int], weights: dict) -> int:
    raw = sum(score * weights[axis] for score, axis in zip(scores, AXES))
    total, remainder = divmod(raw, 5)
    assert remainder == 0, f"총점이 정수가 아니다: {raw}/5"
    return total


def _band_grade(total: int, bands: list) -> str:
    for low, high, grade in bands:
        if low <= total <= high:
            return grade
    raise AssertionError(f"등급 구간 표에 없는 총점: {total}")


@pytest.fixture(scope="module")
def adr_text() -> str:
    return _read(_adr_path())


@pytest.fixture(scope="module")
def weights(adr_text: str) -> dict:
    found: dict = {}
    for cells in _rows(adr_text):
        if len(cells) >= 4 and cells[0] in AXES and cells[-1].isdigit():
            found[cells[0]] = int(cells[-1])
    assert set(found) == set(AXES), f"축 가중치 표를 찾지 못함: {found}"
    return found


@pytest.fixture(scope="module")
def bands(adr_text: str) -> list:
    found: list = []
    for cells in _rows(adr_text):
        if (
            len(cells) >= 3
            and re.fullmatch(r"\d+–\d+", cells[0])
            and len(cells[1]) == 1
            and cells[1] in RANK
        ):
            low, high = cells[0].split("–")
            found.append((int(low), int(high), cells[1]))
    assert len(found) == len(RANK), f"등급 구간 표 5행이 필요: {found}"
    return found


@pytest.fixture(scope="module")
def baseline(adr_text: str) -> dict:
    """기준선 표: | `패키지` | M1..M5 | 총점 | 등급 | 비고 |"""
    found: dict = {}
    for line in adr_text.splitlines():
        line = line.lstrip()
        if not line.startswith("| `"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 8:
            continue
        scores = cells[1:6]
        if not all(score.isdigit() for score in scores):
            continue
        total, grade = cells[6], cells[7]
        if len(grade) != 1 or grade not in RANK:
            continue
        name = cells[0].strip("`")
        assert re.fullmatch(r"[a-z0-9_]+", name), f"패키지명 형식: {name!r}"
        found[name] = {
            "scores": [int(score) for score in scores],
            "total": int(total),
            "grade": grade,
        }
    assert found, "D-178 기준선 표를 찾지 못함"
    return found


def test_weights_sum_to_100(weights: dict) -> None:
    assert sum(weights.values()) == 100, weights


def test_baseline_covers_workspace_packages_set_equality(baseline: dict) -> None:
    """집합 동일성 — 새 패키지는 기준선에 없으면 붉다 (D-178 Decision 5)."""
    workspace: set = set()
    for manifest in sorted((REPO / "src").glob("*/*/package.xml")):
        match = re.search(r"<name>([^<]+)</name>", _read(manifest))
        assert match, f"<name> 없는 manifest: {manifest}"
        workspace.add(match.group(1).strip())
    assert workspace, "src/*/*/package.xml 스캔 결과가 비었다"
    missing = workspace - set(baseline)
    stale = set(baseline) - workspace
    assert not missing, f"기준선에 없는 새 패키지: {sorted(missing)}"
    assert not stale, f"기준선에만 있는(삭제된) 패키지: {sorted(stale)}"


def test_baseline_totals_and_grades_recompute(
    baseline: dict, weights: dict, bands: list
) -> None:
    """총점 재계산 + 등급 구간 + 컷 게이트가 기준선 행마다 스스로 맞아야 한다."""
    for package, row in baseline.items():
        computed = _total(row["scores"], weights)
        assert computed == row["total"], (
            f"{package}: 총점 재계산 {computed} != 기록 {row['total']}"
        )
        expected = min(RANK[_band_grade(computed, bands)], _cap(row["scores"]))
        grade = [name for name, rank in RANK.items() if rank == expected][0]
        assert grade == row["grade"], (
            f"{package}: 기록 등급 {row['grade']} != 규칙 등급 {grade} "
            f"(총점 {computed}, 게이트 상한 순위 {_cap(row['scores'])})"
        )


def test_gate_rules_fire_on_synthetic_rows(weights: dict, bands: list) -> None:
    """합성 행으로 컷 게이트가 죽은 규칙이 아님을 고정한다 (변이 증명의 상시판)."""
    # 총점은 높지만 M5=1 → 상한 B
    m5_broken = [5, 5, 5, 5, 1]
    assert min(RANK[_band_grade(_total(m5_broken, weights), bands)], _cap(m5_broken)) == RANK["B"]
    # M2=2 → 상한 C
    m2_broken = [5, 2, 5, 5, 5]
    assert min(RANK[_band_grade(_total(m2_broken, weights), bands)], _cap(m2_broken)) == RANK["C"]
    # 구간상 S지만 M3=3 → S 자격 미달이라 상한 A
    s_unqualified = [5, 5, 3, 5, 5]
    assert _band_grade(_total(s_unqualified, weights), bands) == "S"
    assert min(RANK[_band_grade(_total(s_unqualified, weights), bands)], _cap(s_unqualified)) == RANK["A"]
    # 전축 5점 → S 통과 (게이트가 S를 루틴으로 막지 않음을 보증)
    perfect = [5, 5, 5, 5, 5]
    assert _cap(perfect) == RANK["S"]
