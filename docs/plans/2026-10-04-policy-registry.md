# 정책 원장 구현 계획

**Goal:** 실제 PolicyArtifact 파일과 평가·승격 이력을 내구성 있게 연결한다.
**Architecture:** learning/registry/policy의 SQLite 트랜잭션과 immutable 파일
snapshot을 사용한다. canonical event hash chain과 단계 CAS를 검증한다.
서명된 verifier receipt는 별도 설치 신뢰 설정으로 검증하며 실행 권한과 구분한다.
**Tech Stack:** Python stdlib/sqlite3, rosy.contracts.learning, pytest.

1. 신규 정책 등록·재등록, 파일 손상, 실제 ACT 실패 평가 이력 테스트를 먼저 쓴다.
2. 파일 snapshot·등록·hash-chain readback·평가 재계산을 구현한다.
3. PromotionRecord와 실제 보고서 bytes, policy/stage/보고서 hash에 binding된
   trusted-principal HMAC receipt, 이전 단계 CAS를 검증한다. 신뢰 설정 없는
   호출·실패 보고서·위조 receipt·단계 도약·동시 stale 승격을 거절한다.
4. register/assess/show CLI로 실제 seed42751 거절 정책을 원장에 넣고, 별도
   process 재독출·파일 무결성과 재등록 idempotence를 확인한다.
5. 영향 tests/ownership/docs/lint와 검증 기록을 남긴다. 원장은 metadata 상태이며
   로봇 dispatch/운영 활성화/physical approval verifier 설치를 수행하지 않는다.

모든 산출물·DB·scratch는 X에 둔다. 기존 모델 PC/robot 원장이나 운영 파일은
바꾸지 않는다. rollback의 stop-readback/승인 계약과 owner 소비는 후속이다.
