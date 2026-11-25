# ROSY OMX · Pinky E2E 호밍·VLA·LLM 복구 툴 계약 및 규칙 (Pipeline Recovery Tool Contract)

결정론적·스크립트 경로(`cell_auto_pick`, `depart_tick`, `pipeline_repark`)가 실패해 `ABORTED`, `FOLD_READBACK_MISSING`, `REPARK_LIMIT`, `REPARK_FAILED`, `REVIEW_REQUIRED`, `UNCALIBRATED_DISPLACED_SITE`, `PINKY_FAILED`/`PINKY_REFUSED` 상태로 멈췄을 때, 외부 LLM/VLA 에이전트 또는 운영자가 **허용된 API 툴**만 통해 상황 판단형 단계적 호밍(D-1048 `cell_auto_fold` 세션 통합)·카메라 시각 검증·재관측·폴백(운영자 승인 + D-911 입회 필수)·사람 에스컬레이션을 수행하기 위한 규칙과 규약이다.

## 1. 엔드포인트 (`rosy.pipeline.recovery-tools.v1`)

- **조회 (Tier A):** `GET /api/fleet/pipeline/recovery-tools`
  - OpenAI/MCP 호환 툴 JSON 스키마(`additionalProperties: false`), 불변 금지 규칙, 호밍 상태 머신, 실행 상한, 현재 미해결 실패 컨텍스트(`active_failures` · `context_sha256` CAS 다이제스트 · `homing_stage` · `homing_strategies` · `camera_sequences` · 활성 veto 코드 · 호출 가능 툴 목록), 최근 감사 원장을 반환한다.
  - `GET /api/fleet/pipeline/cell-tasks` 응답에도 `recovery_handoff` 요약이 함께 실린다.
- **실행 (Guarded Invoke):** `POST /api/fleet/pipeline/recovery-tools/invoke` (`proposer_guard`: `operator` 또는 인증된 `service` 주체; `viewer` 403 거부; 본문 최대 `32768B`, 중첩 깊이 최대 `8`)
  - 모든 변이 툴은 `root_task_id`, `expected_context_sha256` (CAS 일치), `request_id` (`principal:request_id` 전용 멱등 테이블 최대 500건 영속, 거부 응답 HTTP 상태 코드 그대로 재생), `caller_kind` (비운영자가 `"operator"` 스푸핑 시 403), `rationale` 을 필수로 요구한다.
  - `enqueue_displaced_recovery` 와 `enqueue_vla_act_fallback(mode="act")` 는 인증 주체가 `operator` 가 아니면 `403 OPERATOR_APPROVAL_REQUIRED_FOR_FALLBACK_ENQUEUE` 로 거부한다(`vla_shadow` 제안 기록은 `service` 허용).
  - CAS 이후 `arm_id` / `robot_id` / `task_id` 변경 시 `409 TARGET_MISMATCH_AFTER_CAS` 로 거부한다.

## 2. 상황 판단형 단계적 호밍 상태 머신 (`safe_fold_home` + `record_visual_checkpoint`)

USB 단절 후 홈 복구가 필요한 팔은 `home-recovery:<arm>:<incident_id>`로 조회한다.
셀 소유 워커는 검증된 연결과 활성 `auto-fold.json`이 있는 팔만 보고하고, 현재 보류 ID로 `safe_fold_home`을 요청한다.
워커가 준비되지 않았으면 `BOUND_HOME_WORKER_UNAVAILABLE`로 대기한다. 현장 수용 전의 `.pending` 파일은 활성 설정에 포함하지 않는다.
셀은 요청 ID·팔·보류 ID가 일치하는지 확인한다. 사이트 Fleet은 복구 완료 응답과 셀의 보류 해제 조회가 일치할 때 해당 기록의 보류를 해제한다.

실제 셀 사고 복구(`release_and_lift -> 카메라 시각 검증 -> guarded_slow_park -> 홈 접힘 시각+관절 검증`)와 자동 폴드(`auto_fold`)를 **D-1048 `cell_auto_fold.py` 세션 래퍼(`with-session-arm-*.sh`, `ROSY_RECOVERY_INCIDENT`, `cell_corridor.check`, `cell_space.reserve`) 안에서만** 선택 실행한다(`park` 는 `chunk_runner` 의 검토된 라이브러리 `transit_speed` 로만 이동하며 코리더 검사도 동일 속도를 사용한다):

1. **경로 A (`already_home` / `finalize_home_verify`):** 이미 홈 공차 이내 + `AFTER_PARK_VISUAL_FOLDED` 확인 시 운영자 `POST /arm-holds/clear` 준비 판독만 반환(뻗은 팔 토크 해제 절대 금지).
2. **경로 B (`direct_slow_park`):** 그리퍼가 비어 있고 장애물이 없는 경우 `record_visual_checkpoint(stage="pre_park", verdict="CLEAR")` 통과(60초 유효) 후 `safe_fold_home(strategy="guarded_slow_park")` 실행(`cell_auto_fold --stage park_only`).
3. **경로 C (`staged_release_lift_then_park`):** 컨테이너 파지 또는 저고도 정지 시:
   - Step 1: `safe_fold_home(strategy="release_and_lift")` -> `cell_auto_fold --stage release_and_lift` 로 코리더·공간 예약 검증 후 `cell_unwedge.release_and_rise` 실행 및 `human-hold` (`hold_ok=True` 검증 필수; 실패 시 `"held"`) 로 토크 ON 정지 (`risen_for_visual_verify`).
   - Step 2: `record_visual_checkpoint(stage="after_lift", verdict="CLEAR", cargo_detached=true, gripper_open=true, overhead_clear=true, cameras_checked={...})` -> 모션 완료 이후 **엄격히 증가한** 최신 카메라 시퀀스(`checked > min_camera_seqs`) 및 `recorded_at <= 15s` 신선도로만 통과(`arm_a`/`arm_b` 3뷰 `top`/`side`/`arm_X_wrist`, `arm_s` 2뷰 `arm_s_top`/`arm_s_wrist`). `OBSTRUCTED`/`UNCERTAIN` 이면 `HOLD_VISUAL_BLOCKED` 로 잠금(`FOLDED_HOME` 판정은 `after_lift` 에서 409 거부, 단계적 진입 이후 일반 `auto_fold` 피벗 차단).
   - Step 3: `safe_fold_home(strategy="guarded_slow_park")` -> `AFTER_LIFT_VISUAL_CLEAR` / `DIRECT_PARK_VISUAL_CLEAR` (60초 이내) 에서만 허용(`expires_at` + `stop_generation` 바인딩).
   - Step 4 (`park_only` 보류 유지): `cell_auto_fold --stage park_only` 는 세션 종료·토크 OFF 확인 후 자동 보류 해제를 건너뛰고 `parked_for_visual_verify` 를 반환하며, `record_visual_checkpoint(stage="after_park", verdict="FOLDED_HOME", ...)` + 단계 종료 이후의 신선한 관절 `folded: true` readback 동시 확인으로 `AFTER_PARK_VISUAL_FOLDED` 에 도달한다.
4. **경로 D (`auto_fold`):** 기존 D-1048 `cell_auto_fold --stage full` 코리더 자동 폴드(단계적 호밍 진입 전 `IDLE` 상태에서만 허용).
5. **전송·권한·신선도 규약:** `POST /cell-quality` 는 `HUMAN_HOLD` / 원장 장애 시 `pending_safe_home_arms: {}` 를 반환하고 만료(`expires_at`)·정지 세대 불일치 요청을 정리한다. `safe_home_acks` 는 운영자 또는 `ROSY_FLEET_CELL_OWNERS` 등록 소유자만 제출할 수 있고, 소유자 등록 시 `cameras`/`arm_states` 역시 비소유 `service` 를 차단한다. OMX 워커는 `--execute-mode guarded-pick` 이고 **CA 검증된 HTTPS(`is_https and tls_verified`)** 일 때만 기동하며 `in_flight`/`started` 로컬 마커를 일시적 홀드 숨김 동안 보존한다.

## 3. 툴 계층 및 허용 목록 (8종 폐쇄 집합)

| 툴 | Tier | 사전 조건 및 서버 강제 규칙 | 루트당 상한 |
|---|---|---|---|
| `inspect_failure_context` | Tier A (읽기) | 언제든 호출 가능(`HUMAN_HOLD` 중에도 허용). 상태 변경 없음 | 무제한 |
| `safe_fold_home` | Tier B (보수 홈) | `auto_fold` / `release_and_lift` / `guarded_slow_park` / `finalize_home_verify`. 전부 `cell_auto_fold` 세션 래퍼 경유. `expires_at(60s)` + `stop_generation` 바인딩 | 전략당 1회 · 팔당 24h 3회 |
| `record_visual_checkpoint` | Tier A (시각 게이트) | `pre_park` / `after_lift` (`CLEAR`/`OBSTRUCTED`/`UNCERTAIN`), `after_park` (`FOLDED_HOME`). 카메라 `recorded_at <= 15s` + 모션 이후 엄격 단조 시퀀스 검증 | 상태 전이당 |
| `enqueue_displaced_recovery` | Tier B (이탈 복구) | 운영자(`role="operator"`) 승인 + `cell_s`/`arm_s` 전용. `site` 는 `"belt_far"`/`"floor_front"` 만 허용. **D-911 `presence-confirm` 필수** | 루트당 1회 |
| `request_repark` | Tier B (재정차) | 실측 `reach_fix`/`zone_fix` + 전 팔 `folded: true` + `FOLD_READBACK_MISSING` 금지 + `MAX_REPARK(2)` 미만 | 루트당 2회 |
| `enqueue_vla_act_fallback` | Tier C (VLA/ACT) | `vla_shadow` 는 무동작 제안(`service` 허용). `act` 는 운영자(`role="operator"`) 승인 + `cell_s`/`arm_s`, `max_chunks` 1..4, `fallback_chain_depth==0`, **D-911 `presence-confirm` 필수** | 루트당 1회 · 자동 재시도 0회 |
| `dispatch_pinky_reroute` | Tier B (Pinky 재경로) | `PINKY_FAILED`/`PINKY_REFUSED` 전용. `ROSY_FLEET_PINKY_TASK_DISPATCH=1`, 기명 요청자(`requester_named`), 활성 맵 place 및 셀 비충돌 검증 후 `QUEUED` | 루트당 1회 |
| `escalate_human` | Tier C (에스컬) | 활성 `failure` + CAS 일치 필수(`HUMAN_HOLD` 중에도 허용). 동일 `root_task_id` 단일 티켓 중복 제거 + `person_needed: true` | 루트당 1티켓 |

## 4. 절대 금지 규칙 (Fail-Closed Hard Boundaries)

1. **원시 명령·권한 우회 인자 거부 (`422 FORBIDDEN_RAW_COMMAND_KEY`):** `cmd_vel`, `twist`, `joints`, `joints_deg`, `pose`, `pwm`, `torque`, `torque_off`, `eeprom`, `raw_ticks`, `goal_pos`, `motor_id`, `bus`, `fifo`, `shell`, `command`, `path`, `file_path`, `url`, `uri`, `operator_confirmed`, `bypass_presence`, `clear_estop`, `clear_human_hold`, `x`, `y`, `z`, `yaw` 키는 어떤 중첩 위치에서도 거부한다.
2. **팔 확장 상태 토크 차단 금지 (D-1048):** 어떤 복구·호밍 경로에서도 뻗은 팔 토크를 끄지 않으며(`release_and_lift` 종료 시 `human-hold` `hold_ok=True` 검증), `park_only` 역시 `after_park` 시각·관절 검증 전 자동 보류 해제를 금지한다.
3. **안전 잠금 자동 해제 금지:** LLM/VLA 는 `HUMAN_HOLD`, `arm_holds`, E-stop, `ABORTED` 잠금을 해제할 수 없다(`POST /arm-holds/clear` 및 `presence-confirm` 은 기명 운영자 전용).
4. **배치 완료 후 재집기 금지:** `FOLD_READBACK_MISSING` 은 `REPARK_FAILED`/`REPARK_LIMIT` 로 덮어쓰이지 않으며 `complete` 단계 `on_abort()` 및 `enqueue_displaced_recovery`·`enqueue_vla_act_fallback`·`request_repark` 를 모두 `409 PLACEMENT_ALREADY_VERIFIED_HOME_ONLY` 로 차단한다.
