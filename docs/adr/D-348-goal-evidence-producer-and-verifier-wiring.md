## D-348: Fleet이 목표 증거 생산자 등록과 검증 연결을 소유한다

**Status:** Accepted (2026-09-30). 계약·SOURCE/LOCAL 구현 결정이다. 실물 증거 생산자, ER 2 tool 제공, 자동 정책 실행, ROS 연결, 장치 및 현장 수용은 승인하지 않는다.

## Context

ER 2 응답은 후보와 시각적 해석으로 취급한다. 후보가 Mission으로 수락되어도 그 응답이나 OMX Action의 `SUCCEEDED` readback만으로 물체가 목적지에 놓였다고 결론 내릴 수 없다. 기존 `MissionService.confirm_goal()`은 독립 증거와 주입 verifier를 요구하지만, Fleet에 생산자 등록·제출 API·저장·Action 종단 결과와의 연결이 없었다. verifier가 없으면 fail-closed로 유지되어야 한다.

## Decision

1. Fleet은 배포 시 읽는 producer registry를 소유한다. 등록은 producer token 환경변수 이름, workcell, predicate/object/destination, `camera_observation`, 허용 evaluator revision, 서버 기준 `max_age_s`, 누락 대기 `grace_s`, timezone 포함 `valid_until`로 제한한다. 평문 token은 YAML이나 응답에 넣지 않는다.
2. producer는 `X-Goal-Evidence-Token`으로 `POST /api/fleet/goal-evidence`에 `mission_id`와 기존 `GoalEvidence`를 제출한다. 이 credential은 Fleet viewer/operator/policy-admin 계정과 별도다. endpoint는 registry가 구성된 Mission API에서만 노출한다.
3. Fleet은 등록 scope, evaluator revision, 현재 Mission Action/attempt, 독립적인 새 관측, freshness, 만족 predicate, gripper `OPEN` readback을 검증한다. 호출자가 보내는 최대 수명 설정은 신뢰하지 않고, 수신 시각은 서버가 기록한다. 거부한 원문 evidence는 저장하지 않는다.
4. 검증을 통과한 envelope는 Mission과 같은 SQLite DB에 저장한다. `evidence_id`와 같은 내용의 재전송은 멱등 성공이며, 같은 ID에 다른 내용은 충돌이다.
5. 증거와 Action terminal success는 어느 순서로 도착해도 처리한다. 두 조건이 모두 맞으면 Fleet이 `confirm_goal()`을 호출한다. 증거가 없으면 등록된 grace 기간까지 대기하고, 만료 시 Mission을 `HOLD`한다. Action failure/unknown, evidence conflict, stale/mismatched evidence는 `GOAL_CONFIRMED`를 만들지 않는다.
6. registry/verifier 미구성 상태에서는 기존 fail-closed를 유지한다. 이 결정은 Mission dispatcher나 `POLICY_DISPATCH_ENABLED`를 켜지 않는다. ER 2는 evidence 제출 credential이나 verifier가 아니며, ROS/OMX가 독립적인 구동·정지·상태 readback owner로 남는다.

## Alternatives

- 모델의 성공 문장이나 원래 입력 이미지로 목표 성공을 추정: 독립 증거가 아니므로 기각.
- caller가 freshness 정책을 정하게 함: stale evidence 허용을 호출자에게 맡기므로 기각.
- 거부 증거 원문을 감사 로그에 저장: 크기와 민감 데이터 경계를 불필요하게 넓히므로 기각.
- 지금 verifier를 비워 두고 수동 확인만 사용: 안전한 fallback이지만 생산자 계약을 구현하지 못하므로 최종 방향으로는 기각. registry 미구성 fallback으로는 유지.

## Consequences and validation

- SOURCE/LOCAL 범위에서 registry, SQLite store, HTTP ingress, 두 도착 순서, 재전송 충돌, grace timeout을 fake credential/clock으로 검증한다.
- 현장 카메라 evaluator, gripper feedback, 실제 evidence 품질/오탐률, ROS-SIM, device/field acceptance는 별도 증거가 생길 때까지 HOLD다.
- 실행 내역과 API 필드는 [D-348 실행 계획](../plans/2026-09-30-goal-evidence-producer-and-verifier.md) 및 [API Reference §10.14](../reference/ROSY%20API%20%26%20Protocol%20Reference.md)에 기록한다.
