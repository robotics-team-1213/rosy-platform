# ACT 정책의 원장 등록·거절 재독출

2026-10-04 KST. learning/registry/policy의 로컬 metadata 원장을 구현하고
실제 ACT 연구 산출물을 등록했다. 물리 owner/dispatch 또는 운영 승격을 켜지 않았다.
D-449는 Proposed다.

## 실제 실행

입력은 [새 Gazebo ACT run](omx-diverse-sim-act-2026-10-04.md)의
`ede80a29f56e210bf814a4e888d931ed1462c2dc42eb374dfb0c611b0aa6dca9` 정책이다.
X의 원장을 대상으로 별도 CLI 프로세스에서 register → assess-act → show를
실행했다. policy의 weights/config/정규화/evaluation 실제 bytes/SHA를 확인하고
내부 snapshot에 보존했다. 원본 offline report SHA는
`9e376a60a320ce5425423017debb805312e98eaff1842525ca0c65e0bf7ebe09`다.

원장: `X:/DevTemp/rosy-learning-audit-20261004/policy-registry/`.
재독출: `X:/DevTemp/rosy-learning-audit-20261004/policy-registry-readback.json`.

- register event revision:
  `ecd20fd1fdebc88b62b8159fae6a376b630884100403f523f93bd52d77367b67`
- assessment event revision:
  `488757da92ec75226c0c0555188028ba2d978a4e09fda4895266f9129d21b055`
- 마지막 metadata stage: **unregistered**.
- 평가: **reject**, does_not_beat_constant_target_baseline.
- 독립 policy task 성공: **unverified**.

평가 report의 pass 주장을 복사하지 않고 ACT error/count/reload 지표로 기존
연구 조건을 재계산했다. 같은 source의 register/assess-act 재실행 후에도
이력은 두 개 그대로였다. 원장 등록은 L0 정책 등록이나 모델 수용이 아니다.
기존 Python 3.12 native 환경에서도 show를 실행해 Python 3.14 CLI 재독출과
두 event 및 stage가 동일함을 비교했다.

## 구현과 시험

SQLite BEGIN IMMEDIATE·FULL synchronous, canonical event hash chain,
단계 CAS와 immutable 파일 snapshot을 구현했다. 원본/보존 파일 손상·이력/단계
불일치는 조회와 후속 변경에서도 거절한다. snapshot 후 DB commit 전 실패는
미등록 orphan으로 남으며 재검증 뒤 등록할 수 있다.

promote API는 공통 PromotionRecord와 실제 policy-bound report JSON을 검사한다.
별도 설치 trust의 principal/kind별 HMAC receipt가 promotion/policy/report SHA를
정확히 묶어야 한다. authority가 있으면 operating_authority receipt도 요구한다.
실패한 bound ACT 평가를 별도 signed pass 보고서로 덮어쓸 수 없다.
운영 verifier/trust keys는 설치하지 않았으며 CLI에는 promote가 없다.

- registry+공통 계약: **38 passed**. 위조 signature/principal/scope, 실패 report,
  잘못된 metric/verdict, 파일/chain 손상, 재시작, idempotence, transaction 실패,
  두 연결의 동시 승격(one commit, one stale-stage rejection)을 확인했다.
- 소유/import 방향·모듈 구조: **51 passed**. 새 root를 tracked 상태로 검사했다.
- 테스트의 signed L0 pass는 합성 fixture다. 실제 정책은 승격하지 않았다.
- CI selector/registry/공통 계약/OMX helper·변환/export: **81 passed/1 skipped**.
  skip은 호스트 LeRobot 부재다. ACT 보고서 이름을 바꿔도 실제 내용으로 찾아
  거절하는 회귀 검사를 포함했다. 새 learning-policy CI matrix에 registry,
  OMX 학습 helper와 변환 tests를 등록했다. matrix 출력 확인은 runner 실행
  증거가 아니며 push/원격 CI는 아직 없다.
- 문서 배치/harness **65 passed**, generate/lint **0 errors/기존 26 warnings**.
- registry.py source SHA:
  `e971d8562b3bfc7a4c213282e31efd6aa908ba607268d945c9efe942237a4c47`.
- 원장 DB/보존 파일·두 Python 재독출·CI 선택·실행 소스 bundle:
  `X:/DevTemp/rosy-learning-audit-20261004/policy-registry-evidence.zip`,
  41,999,158 bytes, SHA
  `ba614878aba3e88a9c3664874b50a17f46f224d2ff44ed7c83260625c35a8973`.

독립 코드 리뷰는 registry/공통 계약/CI selector 70 tests와 실제 SQLite
read-only event·snapshot·stage 재독출을 확인했다. reset_events가 dict여도 통과하는
계약 오류를 발견해 RED 재현 후 list를 요구하도록 수정했다. 리뷰어의 수정 검증
6 passed, 남은 blocking/nonblocking findings 없음. 이는 코드 리뷰이며 운영/현장
수용 판정이 아니다. 계약 wheel 0.1.2를 X 복사본에서 빌드·별도 target에 설치하고
Python 3.12 isolated import로 정상 정책 수용/잘못된 reset object 거절과
no runtime dependencies/torch 미로드를 확인했다. wheel SHA는
`d1164a672d43cc6697950bbac5e888021b706f59d5b9f7ac94994cbd15c543a3`.
수정 소스·wheel·현재 원장/재독출은 원래 bundle을 유지하고 별도 보존했다:
`X:/DevTemp/rosy-learning-audit-20261004/policy-registry-reviewed-evidence.zip`,
42,007,701 bytes, SHA
`c2182e5c9d91eb4df4d695ae6fa4f732d623a8366b12507b74772a109304f68f`.

## 증거 한계와 잔여 gate

서명은 설치된 verifier의 해당 bytes 인정이며 독립 평가 정확성이나 actuator
권한을 자동 증명하지 않는다. verifier/approval trust 설치·승인 절차는 후속이다.
history 조회는 bytes/chain/단계를 확인하며 과거 key의 현재 신뢰를 재판정하는
owner loader가 아니다. hash chain은 외부 anchor가 없으므로 전체 DB를 재작성한
공격에 대한 독립 tamper-proof 증거라고 주장하지 않는다.

DatasetManifest의 원장 ingestion과 원본 dataset 교차검증, rollback stop-readback/
승인 계약, owner lease/generation/stale/reset/HOLD 집행, 실제 정책의 독립 SIM
과제 판정과 Pinky/Fleet/Isaac 결과 연결은 남아 있다. 모델 PC step-up은 미해결이고
기존 SSH handle 72212는 실패 종료(exit 1)했다. 원격 recording-job 실행 증거는
없으며 같은 연결이 아직 실행 중이라고 주장하지 않는다. 전체 목표는 active다.
