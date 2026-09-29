# D-348 목표 증거 생산자와 검증기 연결 실행 계획

**작성:** 2026-09-30

**상태:** SOURCE/LOCAL 완료; ROS-SIM/DEVICE/FIELD 미완료

**설계:** [D-348 설계](2026-09-30-goal-evidence-producer-and-verifier-design.md)

**ADR:** [D-348](../adr/D-348-goal-evidence-producer-and-verifier-wiring.md)

## 범위

Fleet 내부에서 등록된 증거 producer의 인증부터 `GOAL_CONFIRMED`/`HOLD` 결정까지 연결한다. D-348은 API/service/store 계약을 결정하고 소스 구현을 허용한다. 이를 사용해 live producer를 등록하거나 Mission/자동 policy dispatch를 켜는 권한은 포함하지 않는다.

## 실행 항목 및 결과

| ID | 항목 | 상태 | 증거 |
|---|---|---|---|
| T1 | strict YAML producer registry: scope, environment-only token, evaluator allowlist, `max_age_s`, `grace_s`, expiry | 완료 | `goal_evidence_registry.py`, registry tests |
| T2 | SQLite evidence store: server `received_at`, evidence ID idempotency, changed replay conflict, accepted payload only | 완료 | `goal_evidence_store.py`, store tests |
| T3 | 두 도착 순서 연결: evidence-first pending, Action-first evidence submission trigger, grace expiry HOLD | 완료 | `GoalEvidenceService`, dispatcher callback, service tests |
| T4 | opt-in `POST /api/fleet/goal-evidence`, separate source token, envelope/error contract | 완료 | Fleet app composition and API tests |
| T5 | verifier injection remains fail-closed without registry; Mission dispatcher and policy dispatch valves stay disabled by default | 완료 | composition behavior, static policy guard tests |
| T6 | API Reference v1.59 and contract version pins | 완료 | API Reference §10.14, contract tests |
| T7 | Fleet logs/progress/index, harness, focused lint and full Fleet suite | 완료 | 724 passed, 5 skipped; changed-file flake8 pass; harness 0 errors, 20 repository staleness warnings |

## 확인 결과

- Evidence producer는 `X-Goal-Evidence-Token`으로만 ingress를 인증한다. Site viewer/operator role은 기존 조회/승인 권한으로 분리된다.
- Invalid/unregistered/stale evidence는 store에 들어가지 않는다. 동일 accepted evidence 재시도는 멱등이고, 같은 ID의 변경 본문은 `EVIDENCE_ID_CONFLICT`다.
- Goal confirmation에는 matching successful terminal Action, new post-action observation, registered evaluator revision, fresh evidence, independently sourced gripper `OPEN` readback가 모두 필요하다.
- Evidence 미도착은 registry grace가 끝나면 `GOAL_EVIDENCE_TIMEOUT`으로 `HOLD`한다. Claims release/GOAL_CONFIRMED는 일어나지 않는다.
- 기존 `POLICY_DISPATCH_ENABLED = False`와 disabled-by-default Mission dispatcher 상태는 유지한다.

## 남은 gate

| Gate | 상태 | 필요한 증거 |
|---|---|---|
| SOURCE | GO | full Fleet host tests |
| LOCAL | GO | fake credentials/clock, registry/service/store/API integration, changed-file lint |
| ROS-SIM | HOLD | ROS environment and simulation producer/consumer trace |
| ARTIFACT | PARKED | approved immutable build target and provenance |
| DEVICE | PARKED | selected robot, driver/gripper/camera, stop-state and readback evidence |
| FIELD | PARKED | supervised pick/place trials, evaluator quality and operational acceptance |

No live producer is configured by this change. Do not infer motor control, emergency stop, physical standstill, successful placement, or field readiness from host tests or the Mission API.
