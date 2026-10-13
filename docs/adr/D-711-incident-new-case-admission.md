# D-711 새 사건 생성 허가와 기존 pinned 실행 분리

**Status:** Accepted (2026-10-12, source contract)

D-710 후속으로 worker의 선택적 `new_case_admission(scope)` 내부 포트를 추가한다. 이 포트는 기존 사건 실행 admission과 별개인 빠른 동기 local predicate다. 없으면 기존 동작을 유지하며 지정하면 exact true만 새 사건 생성을 허용한다. 일반 포트 오류는 새 사건을 허용하지 않고 cancellation/BaseException은 삼키지 않는다.

기존 사건의 profile/current/admission 검증과 원래 예산·시도·UNKNOWN·최종 인수는 그대로 유지한다. `prepare_receipt`의 기존 outbox 트랜잭션과 `_drain` poll에서 실제 새 사건 생성 전에만 새 허가를 확인한다. 닫힌 사건·다른 scope의 기존 robot/case는 기존 SQLite 검증으로 재생성·예산 초기화를 거절한다. CORE 최종 authority와 기존 enabled 기본값을 바꾸지 않는다.

이 포트는 pure local 생성 fence이며 registry 조회·네트워크·추론을 직접 하지 않는다. 영속 current/previous 전환이나 원자적 새 사건 배정 router의 완료가 아니다. 전체 snapshot을 두 worker에 공급하는 운영 구성을 승인하지 않으며, 실제 전환은 trusted revision loader와 사건 배정 트랜잭션·pinned worker dispatcher를 별도로 결속해야 한다.
