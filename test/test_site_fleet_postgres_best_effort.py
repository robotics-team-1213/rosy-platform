"""D-796 best-effort 컨텍스트 미러 — fleet는 postgres를 기다리지 않는다.

미러는 가산 전용이고 쓰기 실패는 경고일 뿐(`context_log.py`), SQLite 원장이 단일
정본이다. compose가 fleet를 postgres healthy까지 묶어 두면 미러가 느려지는 순간
관제 자체가 열리지 않는다 — best-effort 위반.
"""

from pathlib import Path

import yaml

SITE = Path(__file__).resolve().parents[1] / "deploy/site"


def _services():
    return yaml.safe_load((SITE / "compose.yaml").read_text(encoding="utf-8"))["services"]


def test_fleet_does_not_wait_for_the_best_effort_context_mirror():
    fleet = _services()["fleet"]
    assert "postgres" not in (fleet.get("depends_on") or {}), \
        "Postgres가 느려도 관제가 막혀서는 안 된다 (D-796: 실패는 경고)"


def test_the_context_mirror_stays_deployed_in_the_stack():
    assert "postgres" in _services()
