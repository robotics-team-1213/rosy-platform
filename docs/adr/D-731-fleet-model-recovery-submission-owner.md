# D-731 기존 Fleet 루프의 단일 규칙·모델 제출 책임

**Status:** Accepted (2026-10-12, source contract; no operational activation)

## Context

D-730 원장을 실제 소비자와 연결해야 한다. 기존 규칙 `_answer`와 모델 후보가 서로 다른 명령 서비스를 가지면 같은 사건의 중복 조치를 막을 수 없다.

## Decision

기존 Fleet 루프가 제출을 소유한다. 실제 기존 규칙 dispatch를 `stuck/submission`으로 이동하고 루프 method identity를 보존한다. 같은 책임에 모델 조건부 BACK 제출을 둔다. provider 실행은 기존 worker, 수용·폐기·단일 claim은 operating 원장에 유지한다. 별도 프로세스·DB·모델 호출 경로를 만들지 않는다.

ROOT factory의 명시적 operating 설정은 trusted/evidence owner 포트와 고정 grant_id, recovery_enabled를 요구한다. 기본은 없음이다. 실제 독립 평가와 설치 producer가 없는 상태를 PASS로 대체하지 않는다. 명시적 설정이 있는 규칙 motion과 모델 BACK은 같은 사건 claim을 소비하며 WAIT·ABORT·MANUAL 및 CORE E-stop은 이 slot 밖에 둔다. terminal UNKNOWN은 재전송하지 않는다.

모델 제출은 실제 HttpRobotClient의 구현 method만 사용한다. capability GET 뒤 최종 guard에서 현재 client identity, 자동 처리 대상, 사람 점유, 법칙, 원래 Problem 및 CORE 관측 generation/phase/attempts를 재확인한다. 동일 DB transaction 안에서 현재 운영 수용·보정·원본 평가·예산·epoch와 단일 claim을 검증한다. 취소는 소유 SQLite 작업의 terminal을 기다리며 claim 이후 취소/연결 단절은 UNKNOWN으로 보존한다. 출력 ACK는 실제 복구 성공이 아니며 기존 worker의 새 정상 관측·closure 확인과 최종 미해결 인수로 이어진다.

## Verification

모델 제출도 기존 resolver의 `sent`/`result`를 사용한다. 새 사건으로 재정지해도 같은 chain의 조치 예산을 소비하며, 최종 제출 직전에 전체 resolver 시간 한계·다른 사건의 결과 불명·소진된 관측 상태를 다시 확인한다. ACK·REFUSED·UNKNOWN은 영속 terminal 기준으로 처리하고 UNKNOWN은 재전송하지 않는다.

후속 floor 보완: 모델 BACK도 기존 `lane_lost.ai_proposal_invalid`의 전체 R3 제한을 재사용한다. CORE 교차로 상태 누락/unknown, 지도 관측 소실, 뒤쪽 동료 위치 미확인, 후방 blocked, 현장 AI 사실, 기존 규칙 예산·거절 상태를 모델 합의로 완화하지 않는다. 현재 resolver chain과 동일 관측 창을 요구하며 기존 R6의 peer waiver도 모델에는 적용하지 않는다. 이 source 보완은 기존 작동 AI 제한의 공유이지 새로운 주행 판단식이 아니다.

모델 claim과 기존 사건 PENDING을 같은 DB transaction에 결속한다. 기존 LineStuckAnswerLog는 자신의 DB와 활성 transaction만 받는다. 공개 관제 기록은 commit 성공 후 표시하고 rollback된 제출을 노출하지 않는다. terminal은 operating.finish의 영속 반환 상태를 기준으로 기존 사건 원장과 연결한다. 실제 정상 관측은 UNVERIFIED action credit를 유지하며 모델 성공으로 승격하지 않는다.

실제 SQLite 및 HttpRobotClient 기반 SOURCE fixture에서 단일 POST, GET 중 HOLD/사람 점유/client 교체/미지원 거절, 연결 단절·취소·중복 거절을 원격으로 검증한다. 기존 resolver 회귀와 source 없는 설치 import를 별도로 확인한다. 실제 모델·독립 현장 정답·설치 수용·로봇 복구·FULL CI는 이 source 검증으로 완료하지 않는다.
