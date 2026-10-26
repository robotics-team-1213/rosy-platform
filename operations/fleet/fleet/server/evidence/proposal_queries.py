"""D-865 P2c: RESOLVED 제안 열거 — proposal_store 크기 레칫(D-766) 밖의 작은 조회.

ProposalStore 의 인스턴스 도구(purge_expired/_connect/_row)를 빌려 쓰는 자유
함수다. 저장소 자체는 줄을 늘릴 수 없어 여기에 둔다. 소비자는 정책 승인 worker
하나뿐이고 범위·상태 재검사는 소비자 쪽에서 한다(제안 행은 대용량이 아니므로
bounded read 로 충분하다). 가짜 저장소 시험은 행 목록을 반환하는 list_resolved
메서드만 구현하면 이 함수를 건너뛸 수 있다.
"""

from __future__ import annotations

from contextlib import closing
from typing import Any


def list_resolved(store, *, limit: int = 20) -> list[dict[str, Any]]:
    """RESOLVED 상태이고 Mission 초안(mission_id)이 있는 제안, 오래된 순.

    소비자가 상태·원장·만료를 다시 확인하므로 이 조회는 표면 그대로를 돌려준다.
    ``list_resolved`` 메서드가 이미 있으면(가짜 저장소) 그 값을 그대로 쓴다."""
    if hasattr(store, "list_resolved"):
        return list(store.list_resolved(limit=limit))
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer in 1..100")
    store.purge_expired()
    with closing(store._connect()) as connection:  # noqa: SLF001 - 도구 빌림이 이 모듈의 계약
        rows = connection.execute(
            "SELECT * FROM fleet_proposals WHERE state='RESOLVED' "
            "AND mission_id IS NOT NULL ORDER BY rowid ASC LIMIT ?",
            (limit,),
        ).fetchall()
    return [row_dict for row in rows if (row_dict := store._row(row))]  # noqa: SLF001
