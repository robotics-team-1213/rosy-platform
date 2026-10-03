"""D-148: gz_sim 은 fleet 의 공개 벤치 면(fleet.bench)만 소비한다.

swarm_bench 가 ``fleet.swarm.*`` / ``fleet.formation.*`` 내부 모듈을 직접
import 하면 fleet 내부 재조정이 시뮬 벤치를 깨뜨린다(결합도 평가
2026-09-19 §6 C등급). 이 계약은 ROS 오버레이 없이도 검사된다 — 텍스트
구조 검사이므로 host pytest 에서 그대로 돈다.
"""

from __future__ import annotations

import re
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"

#: fleet.bench 외의 fleet 하위 모듈 직접 import 금지 (D-148).
FORBIDDEN = re.compile(r"^\s*(?:from|import)\s+fleet\.(?:swarm|formation)\b", re.MULTILINE)


def test_scripts_do_not_import_fleet_internals():
    offenders = []
    for path in sorted(SCRIPTS.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        match = FORBIDDEN.search(text)
        if match:
            offenders.append(f"{path.name}: {match.group(0).strip()}")
    assert not offenders, (
        "gz_sim 은 fleet.bench 공개면만 import 할 수 있다 (D-148): " + "; ".join(offenders)
    )


def test_swarm_bench_uses_the_facade():
    text = (SCRIPTS / "swarm_bench.py").read_text(encoding="utf-8")
    assert re.search(r"^\s*from fleet\.bench import", text, re.MULTILINE), (
        "swarm_bench 는 fleet.bench 를 통해 fleet 에 접근해야 한다 (D-148)"
    )
