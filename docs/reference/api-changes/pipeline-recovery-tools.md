---
surface: fleet
kind: additive
slug: pipeline-recovery-tools
date: 2026-11-24
title: Fleet 파이프라인 호밍·VLA/LLM 복구 툴 계약
history: Additive: GET /pipeline/recovery-tools, POST /pipeline/recovery-tools/invoke 및 D-1048 단계적 호밍·시각 체크포인트
---
`GET /api/fleet/pipeline/recovery-tools` 와 `POST /api/fleet/pipeline/recovery-tools/invoke` 는 결정론적 OMX/Pinky 파이프라인이 실패해 `ABORTED`, `FOLD_READBACK_MISSING`, `REVIEW_REQUIRED`, `REPARK_LIMIT`, `REPARK_FAILED`, `PINKY_FAILED`/`REFUSED` 상태일 때 LLM/VLA 및 운영자에게 허용된 8종 복구 툴 스키마·D-1048 세션 통합 단계적 호밍·실행 게이트(`rosy.pipeline.recovery-tools.v1`)를 제공한다(v1.next).

* `inspect_failure_context`, `safe_fold_home`(`auto_fold` · `release_and_lift` · `guarded_slow_park` · `finalize_home_verify`, 전부 `cell_auto_fold` 세션 래퍼 경유 · `expires_at`/`stop_generation` 바인딩), `record_visual_checkpoint`(카메라 `recorded_at <= 15s` 신선도·모션 이후 엄격 단조 프레임 시퀀스 검증), `enqueue_displaced_recovery`(운영자 승인 · 루트당 1회 · D-911 입회 필수), `request_repark`(`MAX_REPARK=2`), `enqueue_vla_act_fallback`(`vla_shadow` 또는 운영자 승인 + D-911 입회 필수 `act`), `dispatch_pinky_reroute`(기존 dispatch 게이트 · 동일 루트당 1회), `escalate_human`(활성 실패+CAS 필수, 루트당 단일 티켓) 만 허용하며 원시 명령·우회 키(`FORBIDDEN_RAW_COMMAND_KEY`)를 `422`로 거부한다(v1.next).
* 모든 변이 툴은 `expected_context_sha256` CAS 검증(`409 STALE_FAILURE_CONTEXT`), principal 바인딩 `request_id` 멱등성(거부 상태 코드 포함 재생), `HUMAN_HOLD` 차단(`409 HUMAN_HOLD_ACTIVE`), `caller_kind` 역할 일치(`403`), `TARGET_MISMATCH_AFTER_CAS`, `fallback_chain_depth < 1` 상한을 적용하고 저장 실패 시 인메모리 상태를 롤백한다(v1.next).
* `POST /api/fleet/pipeline/cell-quality` 는 `ROSY_FLEET_CELL_OWNERS`/운영자 한정 `safe_home_acks` 로 `cell_camera_telemetry_sync.py` 및 `cell_auto_fold.py` (`--stage release_and_lift | park_only | full`) 를 검증된 HTTPS · `guarded-pick` 모드에서만 안전 기동하며 `park_only` 는 `after_park` 검증 전 보류 해제를 건너뛴다(v1.next).
