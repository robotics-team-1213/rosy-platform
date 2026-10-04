"""D-329 Decision 4 / Transition 4 — 보존 회차의 선언과 실물을 대조한다.

회차 폴더의 ``matrix.json``(스키마 ``rosy.g2-matrix/1``)이 선언한 셀마다 파일이
그 자리에 있고 추적돼 있어야 한다. 파일명 규칙(``<surface>-<state>-<가로>x<세로>.png``)도
여기서 판정한다. 변이 확인(합성 오류 매트릭스)을 같은 파일에서 수행한다 —
검사 함수가 실제로 빨갛게 되는 것을 보인 뒤에만 실제 회차에 대해 초록을 주장한다.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from surface_registry import REPO, load

SCHEMA = "rosy.g2-matrix/1"
FILENAME_RE = re.compile(r"^(?P<id>[a-z0-9]+(?:-[a-z0-9]+)*?)-(?P<state>[a-z0-9]+)-(?P<w>\d+)x(?P<h>\d+)\.png$")
VIEWPORT_RE = re.compile(r"^\d+x\d+$")
STATE_RE = re.compile(r"^[a-z0-9]+$")


def _tracked(root: Path, relative: str) -> bool:
    out = subprocess.run(["git", "-C", str(root), "ls-files", "--", relative],
                         capture_output=True, text=True)
    return bool(out.stdout.strip())


def matrix_files(root: Path) -> list[Path]:
    """추적된 matrix.json 만 — 파일시스템 훑기는 빌드 산출물을 집는다(D-329 Context 3)."""
    out = subprocess.run(["git", "-C", str(root), "ls-files", "--", "docs/validation"],
                         capture_output=True, text=True)
    return [root / line for line in out.stdout.splitlines() if line.endswith("/matrix.json")]


def validate(root: Path, matrix_path: Path, registry_ids: set[str]) -> list[str]:
    """오류 문장 목록. 비면 합격."""
    errors: list[str] = []
    try:
        data = json.loads(matrix_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 — 회차 파일이 깨져도 문장으로 남긴다
        return [f"{matrix_path.name}: 해석 불가 ({exc})"]

    if data.get("schema") != SCHEMA:
        errors.append(f"{matrix_path.name}: schema가 {SCHEMA!r}이(가) 아니다: {data.get('schema')!r}")
    if not isinstance(data.get("tier"), str) or not data["tier"].strip():
        errors.append(f"{matrix_path.name}: tier(증거 등급)가 비었다")
    folder_date = re.search(r"(\d{4}-\d{2}-\d{2})", matrix_path.parent.name)
    if not folder_date or data.get("round") != folder_date.group(1):
        errors.append(f"{matrix_path.name}: round({data.get('round')!r})가 폴더 날짜와 다르다")

    seen: set[tuple[str, str, str]] = set()
    for surface in data.get("surfaces", []):
        sid = surface.get("id")
        if sid not in registry_ids:
            errors.append(f"{matrix_path.name}: 미등록 표면 id {sid!r}")
        for cell in surface.get("cells", []):
            key = (str(sid), str(cell.get("state")), str(cell.get("viewport")))
            if key in seen:
                errors.append(f"{matrix_path.name}: 중복 셀 {key}")
            seen.add(key)
            state, viewport, name = cell.get("state"), cell.get("viewport"), cell.get("file")
            if not isinstance(state, str) or not STATE_RE.match(state):
                errors.append(f"{matrix_path.name}: state 규칙 위반 {state!r}")
            if not isinstance(viewport, str) or not VIEWPORT_RE.match(viewport):
                errors.append(f"{matrix_path.name}: viewport 규칙 위반 {viewport!r}")
            if not isinstance(name, str):
                errors.append(f"{matrix_path.name}: file이 없다({key})")
                continue
            match = FILENAME_RE.match(name)
            if not match or match.group("id") != sid or match.group("w") + "x" + match.group("h") != viewport:
                errors.append(f"{matrix_path.name}: 파일명 규칙 위반 {name!r} (셀 {key})")
            target = matrix_path.parent / name
            if not target.is_file():
                errors.append(f"{matrix_path.name}: 셀 파일 없음 {name}")
            elif not _tracked(root, target.relative_to(root).as_posix()):
                errors.append(f"{matrix_path.name}: 셀 파일이 추적되지 않음 {name}")
    return errors


def test_every_tracked_matrix_declares_only_real_cells():
    registry_ids = {row["id"] for row in load()}
    files = matrix_files(REPO)
    assert files, "추적된 matrix.json이 최소 하나 있어야 한다 (첫 적용: pilot-g2-baseline-2026-10-04)"
    errors = [e for path in files for e in validate(REPO, path, registry_ids)]
    assert errors == [], "\n".join(errors)


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")


def test_synthetic_mutation_matrix_is_caught(tmp_path):
    """변이 확인 — 각 오류 종류가 검사를 통과하지 못한다."""
    root = tmp_path
    (root / "docs" / "validation" / "round-2026-01-02").mkdir(parents=True)
    good = {
        "schema": SCHEMA, "round": "2026-01-02", "tier": "LOCAL-synthetic",
        "surfaces": [{"id": "pilot", "cells": [
            {"state": "drive", "viewport": "390x844", "file": "pilot-drive-390x844.png"}]}],
    }
    cases: list[tuple[str, dict | str, list[str]]] = [
        ("스키마", {**good, "schema": "other/1"}, ["schema가"]),
        ("미등록 id", {**good, "surfaces": [{"id": "ghost", "cells": good["surfaces"][0]["cells"]}]}, ["미등록 표면"]),
        ("round 불일치", {**good, "round": "1999-01-01"}, ["round"]),
        ("tier 없음", {**good, "tier": ""}, ["tier"]),
        ("규약 밖 파일명", {**good, "surfaces": [{"id": "pilot", "cells": [
            {"state": "drive", "viewport": "390x844", "file": "drive-phone.png"}]}]}, ["파일명 규칙"]),
        ("뷰포트 불일치", {**good, "surfaces": [{"id": "pilot", "cells": [
            {"state": "drive", "viewport": "390x844", "file": "pilot-drive-2000x1200.png"}]}]}, ["파일명 규칙"]),
        ("중복 셀", {**good, "surfaces": [{"id": "pilot", "cells": [
            good["surfaces"][0]["cells"][0], good["surfaces"][0]["cells"][0]]}]}, ["중복 셀"]),
        ("없는 파일", {**good, "surfaces": [{"id": "pilot", "cells": [
            {"state": "drive", "viewport": "390x844", "file": "pilot-drive-390x844.png"}]}]},
         ["셀 파일 없음"]),  # 실제 PNG를 쓰지 않는다
        ("깨진 json", "{not json", ["해석 불가"]),
    ]
    for name, payload, expected in cases:
        matrix = root / "docs" / "validation" / "round-2026-01-02" / "matrix.json"
        _write(matrix, payload)
        errors = validate(root, matrix, {"pilot"})
        assert any(all(word in e for word in expected) for e in errors), f"{name}: 잡히지 않았다 — {errors}"

    # 정상본은 파일이 있으면 통과한다
    matrix = root / "docs" / "validation" / "round-2026-01-02" / "matrix.json"
    _write(matrix, good)
    _write(root / "docs" / "validation" / "round-2026-01-02" / "pilot-drive-390x844.png", "")
    # tmp_path는 git 저장소가 아니므로 추적 검사를 건너뛴 별도 판정은 하지 않는다:
    # 존재 검사까지를 여기서, 추적 검사는 진짜 회차 시험이 담당한다.
    assert not [e for e in validate(root, matrix, {"pilot"}) if "없음" in e or "규칙" in e]
