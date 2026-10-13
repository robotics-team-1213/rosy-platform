## D-753 Fleet holder의 설치 namespace와 구조 증가를 검사에 반영한다

**Status:** Accepted
**Date:** 2026-10-14

## Evidence

Committed faea4101c의 첫 원격 집중 검사: 88 passed, 4 failed. 기존 실패 비교는 4 NEW다. S8의 source holder는 실제 설치 이름 fleet.server.*를 유지하지만 manifest에 source_packages를 적지 않아 AST 검사만 fleet.server.auth/console/ledger.*로 잘못 해석했다. 이 때문에 안전 anchor 및 상대 import의 frozen edge 검사가 실패했다.

독립 delivery_review 측정: Fleet parent 55452, 폴더 정리 시작점 3cf2aecde 55436. 증가16은 server/__init__7, _source_layout3, setup3, proof 설명3이다. 과거 판정 당시 parent55428→정리 시작점55436의8은 이전 공유 main 증가다. 새 동작·DB·서비스·명령 권한은 추가되지 않았다.

## Decision

1. Fleet manifest root의 source_packages에 fleet/server/{peer,cell,auth,console,ledger}→fleet.server를 기록한다. 런타임 설치 mapping과 일치시키며 safety anchor·public API·import 규칙·기존 violation 예외를 완화하지 않는다.
2. 원래 Fleet baseline55286에 구조 보조16만 합쳐55302로 독립 재판정한다. 현재55452는 그 값+150이다. 기능 성장 허용150, 모든 nested·zero·file·hard ceiling과 기존 split 의무·판정 이력은 유지한다.
3. initializer가 없는 source holder를 size unit으로 등록해 스캔에서 제외하지 않는다. 새 namespace나 facade·dependency를 만들어 이 검사를 통과시키지 않는다.
4. 같은 원격 집중 검사를 다시 실행하고 known_failures와 비교한다. pre-push, exact-SHA CI, 서명 candidate, 실제 실행 revision 확인을 통과한 대상만 배포한다. 연결되지 않은 로봇·device/field 수용은 별도 미확인이다.

| Previous ADR | Relationship |
|---|---|
| D-427 | source path와 실제 설치 namespace 연결 |
| D-430 | Safety 검사 범위·공개 anchor·독립 검토 유지 |
| D-738 | 구조 정리 뒤 실제 원격 gate 보완 |
| D-750 | 기존 Fleet holder와 동일한 설치 identity |
