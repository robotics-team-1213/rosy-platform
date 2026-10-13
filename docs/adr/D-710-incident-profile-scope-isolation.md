# D-710 Incident worker의 profile·CORE 소유 scope 분리

**Status:** Accepted (2026-10-12, source contract)

모델 revision별 worker가 같은 DB를 읽을 때 현재 구현은 전체 active_scopes/pending_handoffs를 처리해 다른 profile의 사건을 PROFILE_CHANGED로 닫거나 최종 인수를 대신 큐에 넣을 수 있다. D-709 후속 모델 교체의 전제는 이 소유권 침범을 막는 것이다.

기존 CaseScope와 SQLite schema를 유지하고 worker가 자신의 전체 profile tuple SHA와 CORE owner의 active/최종 인수 대기 사건만 처리한다. 다른 revision/owner의 사건 상태·예산·시도·최종 인수는 그대로 보존한다. 동일 robot/case에 다른 profile로 begin_case를 시도하면 기존 scope 검증에서 거절하며 예산이나 시도를 초기화하지 않는다. 자기 profile이 현재 admission에서 폐기되면 기존 HOLD fence는 유지한다.

이 변경은 운영 current/previous 전환이나 새 사건 배정의 완료가 아니다. 진행 사건의 pinned profile 보존·새 사건에만 새 승인 revision 배정·복귀·재시작의 실제 dispatcher는 lifecycle 후속이다. 단순히 두 worker에 전체 snapshot을 보내는 구성을 승인하지 않는다. CORE의 최종 제어 권한과 기존 관측/호출 예산을 유지한다.
