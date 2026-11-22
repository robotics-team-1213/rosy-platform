---
surface: cell
kind: additive
slug: omx-cell-job-api-auth-and-safety
date: 2026-11-23
title: OMX Cell Job API (v1.next) 토큰 분리·안전 게이트·멱등성
history: cell-job-human/machine 토큰 분리, Idempotency-Key, warm 재사용 안전 게이트, depth-d435.lock, act_backend/goal_slot/verify_zones 추가
---
- `GET /readiness` 및 실패 컨텍스트 HTTP 경로 전 단계로 `:8781` `cell_job_api.py` 인증 분리 및 실행 전 안전 게이트를 추가합니다 (D-1072 PR-2).
- 이중 토큰(`--human-token-file` vs `--machine-token-file`): `cell-job-machine`은 `person_at_switch: true`·비검토 이동 작업 시 `403 MACHINE_COMMISSIONING_FORBIDDEN` 반환 및 서버 바인딩 `proposer` 강제(`403 PROPOSER_MISMATCH`), `audit.jsonl`에 `principal_role`·`principal_id` 기록.
- `Runner.start`·warm 재사용 게이트: `omx_incident.status(arm)`(`409 ARM_INCIDENT_HELD`), 피어 A/B 접힘(`409 PEER_ARM_NOT_FOLDED`), 온라인 Fleet 안전(`409 FLEET_SAFETY_STOP`), `depth-d435.lock`(`409 DEPTH_LOCK_HELD`), 오프라인 이동 시 `cell-state-dirty-<arm>.json` 기록, `Idempotency-Key` 헤더(`409 IDEMPOTENCY_KEY_CONFLICT`).
- `cell_policy_drive` `act_backend`(`ROSY_ACT_BACKEND`)·`goal_slot`(`--goal-slot`) 및 `auto_pick` `verify_zones`(`--verify-zones`) 옵션 추가.
