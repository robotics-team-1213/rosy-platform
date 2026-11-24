---
surface: cell
kind: additive
slug: omx-cell-failure-context-and-media-jobs
date: 2026-11-23
title: OMX Cell API (:8781) 실패 컨텍스트·준비 상태·프레임 메타 및 비-이동 미디어/스테이징 작업
history: GET /readiness, /failures*, /frame/{view}.jpg 헤더 보존, /jobs/{id} structured_result 및 5종 비-이동 작업 추가
---
- `cell_job_api.py` (`:8781`)에 읽기 전용 상태/증거 엔드포인트를 추가합니다 (D-1072 PR-3).
- `GET /readiness`: `rosy.cell-readiness.v1`(`max_age_s <= 5.0`, `cell_state_gen`, 3개 팔 잠금/보류/폴드/오염 상태, `blocking_refusals`, `allowed_tiers_now`, `readiness_digest`) 및 `X-Cell-State-Gen` 헤더 반환.
- `GET /failures`, `GET /failures/latest`, `GET /failures/{bundle_id}`, `GET /failures/{bundle_id}/assets/{filename}`: `rosy.omx-failure-context.v1` 번들 및 SHA-256 검증 사이드카 자산 서빙(`ETag`, `X-Cell-State-Gen`, 경로 탈출·심볼릭 링크·변조 `400` 차단).
- `GET /frame/{view}.jpg`: `:8767` 원본 헤더(`X-Frame-Seq`, `X-Source-Stamp`, `ETag`, `Cache-Control`) 보존.
- `GET /jobs/{id}`: 4000B 로그 tail 밖 JSON까지 파싱해 `structured_result`와 `failure_bundle_id` 제공.
- 비-이동 작업 5종(`cell-job-machine` 허용): `upkeep_check`(`--mode autonomous`), `capture_clip`(1..15s MP4 `<= 16 MiB`, D435/팔 잠금 미사용), `convert_episodes`(`DO_NOT_TRAIN` 차단), `transfer_dataset`(봉인 `CLOSED` 하드웨어 컬렉션 전용), `stage_policy_bundle`(`:8768` SHA-256 검증 원자 스테이징).
