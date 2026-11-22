## D-1071 미확정(UNKNOWN) 네비게이션 작업의 정지 증거 기반 운영자 정산

**Status:** Accepted (2026-11-22). 관련 결정: [D-330](D-330-fleet-action-admission-stop-and-recovery.md) · [D-421](D-421-fleet-cancel-all-driving-separate-from-latched-estop.md) · [D-540](D-540-fleet-console-structure-v2.md) · [D-732](D-732-core-native-outcome-ports.md).

### Context

- `FleetTaskService._dispatch_next`가 `RobotApiError(status>=500)` 또는 전송/타임아웃 예외로 `COMMAND_RESULT_UNKNOWN`(`UNKNOWN`)에 들어가면 `fleet_action_claims`의 `robot:<id>` 점유(`DISPATCHING`)와 `fleet_robot_reservations`를 안전상 유지한다(자동 재시도 및 자동 해제 금지).
- 첫 `CORE` 영수증(`receipt.operation`)이 바인딩된 작업은 `reconcile_tasks`가 D-732 `quiescence` 증명으로 종결·해제할 수 있다. 그러나 첫 전송 응답 전에 끊긴 `receipt_json=None`(또는 `native_required`만 있는 미바인딩 `UNKNOWN`) 작업은 `reconcile_tasks` 대상이 아니며, `/api/fleet/cancel-all`의 `nav.canceled` 상관 이벤트도 CORE에 목표가 닿지 않았으면 도착하지 않아 `unresolved_actions=1` 상태로 재개(`POST /api/fleet/dispatch/rearm`)까지 영구 교착된다.

### Decision

| 항목 | 결정 |
|---|---|
| 경로·권한 | `POST /api/fleet/tasks/{task_id}/reconcile` (기명 운영자 `require_named_operator` 전용, API 감사 대상). 요청 본문 `{operator_confirmed: true, expected_attempt_id}` (`extra="forbid"`, `StrictBool`). |
| 미바인딩 `UNKNOWN` 정산 | 1) 대상 로봇에 `console.cancel(robot_id)` 실행(실패 시 `503 ROBOT_UNREACHABLE`, 점유 유지), 2) 2초 이내 `GET /api/v1/navigation/state`로 D-732 `quiescence` 전체 증명(`lookup=="FOUND"`, `navigation`이 `{IDLE, ARRIVED, CANCELED, FAILED}` 중 하나이며 `PLANNING`·`NAVIGATING`·`BLOCKED` 거부, `operation.phase=="TERMINAL"` 및 `operation.boot_id==owner.boot_id`, `quiescence.requested_run_id==operation.run_id`, `quiescent=true`, `owner.owner_run_id=null`, `quiescence.owner_run_id=null`, `boot_id`·`owner_generation` 일치, `admitting`/`pending_submission`/`actuating_callback`/`lease_active` 전부 `false`) 또는 해당 부트 내 네이티브 실행 이력이 없는 경우의 무실행 정지 증명(`operation=null`, `quiescence=null`, `lookup=="UNKNOWN"`, `navigation=="IDLE"`, 유효한 `owner.boot_id`/`owner_generation>=0`/`owner_run_id=null`) 검증(`operation!=null && quiescence=null` 및 구형 D-732 미지원 페이로드는 계속 `409 ROBOT_NOT_QUIESCENT`, 통신 불능 시 `503 CORE_QUIESCENCE_UNAVAILABLE`), 3) `BEGIN IMMEDIATE`에서 `status=="UNKNOWN"`·`attempt_id==expected_attempt_id`·미바인딩 CAS로 `HOLD(OPERATOR_RECONCILED_QUIESCENT)` 전이 및 해당 세대 `fleet_action_claims`·예약 해제. |
| 네이티브 바인딩 `UNKNOWN` | `receipt.operation`이 이미 있으면 기존 D-732 `task_result` readback 경로로 위임하며 `safe_released=true`일 때만 `200`, 아니면 `409 ROBOT_NOT_QUIESCENT`. |

### Consequences & Invariants

- 백그라운드 자동 해제는 도입하지 않는다. 첫 전송이 CORE에 닿았는지 불명확한 작업은 기명 운영자의 명시적 정산과 실시간 CORE 정지 증거 없이는 풀리지 않는다.
- 오프라인·타임아웃·비정지 응답에서는 어떤 DB 점유도 풀지 않고 `fleet.sqlite3` 수동 편집을 필요로 하지 않는다.
