# OMX AI 실패 폴백·컨텍스트 번들 및 에이전트 Tool/HTTP 파이프라인 구현 계획

Date: 2026-11-23  
Status: **Completed — D-1072 코드 구현 PR-0..PR-7 머지 완료 (`#563`, `#564`, `#565`, `#624`, `#629`, `#634`, `#572`, `#566`; §3 현장·후속 트랙 진행 중)**  
근거 결정: [D-1072](../adr/D-1072-omx-ai-failure-fallback-context-and-agent-tool-pipeline.md) · [D-358](../adr/D-358-er2-feedback-outbox-and-replan-fencing.md) · [D-427](../adr/D-427-platform-three-parts-middleware-operations-learning.md) · [D-429](../adr/D-429-five-concerns-control-port-and-site-devices.md) · [D-430](../adr/D-430-safety-as-a-separate-concern.md) · [D-878](../adr/D-878-structured-model-output-schema-and-provider-wire.md) · [D-911](../adr/D-911-omx-native-reviewed-operating-envelope.md) · [D-1019](../adr/D-1019-omx-carry-redirects-to-declared-alternate-destinations.md) · [D-1024](../adr/D-1024-omx-learned-policy-supervised-real-trial-fast-track.md) · [D-1047](../adr/D-1047-cell-s-automatic-departure-and-link-failure-clear.md) · [D-1048](../adr/D-1048-automatic-fold-of-a-held-extended-arm.md) · [D-1057](../adr/D-1057-cell-task-admission-evidence.md) · [D-1061](../adr/D-1061-records-fragments-merge-queue.md)

---

## 0. 전체 아키텍처 및 PR 의존 관계

```text
[PR-0 / TODO 0] D-1072 ADR + 본 구현 계획 (non-safety, docs)
       │
       ├──▶ [PR-1 / TODO 1] 실패 컨텍스트 계약 + 셀 수집/저장/펜스 모듈 (non-safety, omx-cell + core)
       │          │
       │          ▼
       ├──▶ [PR-2 / TODO 2] D-430 태그 폐쇄 + :8781 토큰 분리/안전 게이트 + worker 3상태 (Safety-Review!)
       │          │
       │          ▼
       ├──▶ [PR-3 / TODO 3] :8781 /readiness + /failures HTTP + 상시 Ring(policy+pick) + 영상/데이터셋 작업 + 스텁 제거
       │          │
       │          ▼
       ├──▶ [PR-4 / TODO 4] AI 폴백 9동사 커널 + cell_vlm_orchestrator 수렴 + policy→IK 무승인 차단 (Safety-Review!)
       │          │
       │          ▼
       ├──▶ [PR-5 / TODO 5] Fleet-R PROPOSED→QUEUED + interlock_scope + /readiness + Assistant + FORBIDDEN_KEYS (Safety-Review!)
       │          │
       │          ▼
       ├──▶ [PR-6 / TODO 6] Learning Center :8768 서비스 토큰 + canonical ONNX export/manifest + D-358/D-878 브리지
       │          │
       │          ▼
       └──▶ [PR-7 / TODO 7] agy 12-Tool stdlib HTTP 브리지 (tools/remote/rosy_agent_bridge.py) + 통합 회귀 시험
```

> **참고 (중복 PR 방지):** `deploy/robot/omx/cell_params.py:59`에 `"calibrate.remap_depth_unknown_blocks": (1, "flag", 0, 1)`가 이미 `main`에 반영되어 있으므로 별도 PR을 열지 않는다.

---

## 1. 저장소 공통 제약 (매 TODO 필수 확인)

- **행 수 상한 (`size_range.py`, `rosy_harness.py:395-397`, `size_ratchet.txt` 비어 있음):**
  - `deploy/robot/omx/*.py`는 **400줄 미만(`<= 399`, 권장 `<= 370`)** 필수.
  - 기타 프로덕션 `.py`는 **600줄 이하(`<= 600`)**, 테스트는 **1,500줄 이하**.
  - **줄 절벽 파일(수정 전 먼저 헬퍼 분리 필수):** `cell_auto_pick.py`(398), `omx_incident.py`(394), `cell_job_spec.py`(383), `cell_task_exec.py`(382), `cell_task_worker.py`(378), `pipeline_evidence.py`(582), `schemas.py`(597), `review_app.py`(599).
- **D-1061 기록 컷오버:** `docs/reference/ROSY ADR Log.md`, `logs.md`, `ROSY API & Protocol Reference.md`, `contract_version.py`를 PR에서 직접 수정 금지. API 변경은 `python tools/new_record.py api --surface fleet|core|cell --slug <slug> --title ...` 사용.
- **D-226 & LF:** 모든 커밋 파일은 **LF(`\n`) 전용**, 실제 실험실 IP/내부 계정/토큰 경로 기재 금지, 테스트에서도 합성 RFC 5737/6598 IP(`100.64.0.x`, `192.168.50.x`, `10.0.0.x`)만 사용.
- **D-584 원격 시험:** 노트북 로컬 `pytest` 금지 — 모든 시험은 `python tools/remote/remote_pytest.py --log-dir D:/DevTemp/<slug> -- <tests>` + `python test/known_failures.py D:/DevTemp/<slug>/run-1.txt`로 검증.

---

## 2. 단계별 TODO 체크리스트

### [x] TODO 0 — PR-0: D-1072 ADR 및 구현 계획 확정 (`docs/omx-ai-failure-fallback-and-agent-pipeline`)
- **대상 파일:** `docs/adr/D-1072-omx-ai-failure-fallback-context-and-agent-tool-pipeline.md`, `docs/plans/2026-11-23-omx-ai-failure-fallback-and-agent-pipeline.md`
- **안전 태그:** 없음 (`neutral` / docs)
- **작업 내용:**
  - `python tools/harness/adr_reserve.py next`로 `D-1072` 선점 및 D-427·D-429·D-430 관계표 포함 ADR 작성.
  - TODO 0~7 체크리스트, 줄 절벽 경고, D-430·D-1061 규칙을 포함한 본 계획 문서 작성.
- **완료 기준 / 검증:**
  - `python tools/harness/rosy_harness.py lint` (`0 error(s)`)
  - `python tools/harness/size_range.py --base origin/main --head HEAD`
  - `remote_pytest.py` (`test/architecture/test_document_placement.py`, `test/test_records_fragments.py`, `test/test_network_topology_contracts.py`) + `known_failures.py` 통과.

---

### [x] TODO 1 — PR-1 (`#564`): `rosy.omx-failure-context.v1` 계약 및 셀 번들 수집·저장·펜스 모듈 (`feat/omx-failure-context-bundle`)
- **대상 파일(모두 신규 파일, 줄 절벽 파일 0건 수정):**
  - `contracts/foundation/core_common/protocol/cell_failure_context.py` (`<= 350`줄)
  - `deploy/robot/omx/cell_failure_context.py` (`< 380`줄, stdlib 전용)
  - `test/test_omx_failure_context.py` (`<= 450`줄)
- **안전 태그:** 없음 (`core` + `omx-cell`, 신규 읽기/계약 모듈)
- **작업 내용:**
  1. Pydantic v2 strict 계약(`CellFailureContext`, `CellReadiness`, `FailureContextFence`, `MeasuredVeto`, `FallbackMenuOption`, `CameraManifestEntry`, `FailureAssetRef`, `FailureFreshness`, `canonical_sha256`): `<= 48 KiB`, 깊이 `<= 6`, `allow_nan=False`, base64 이미지 인라인 금지, `missing_device` 카메라 프레임 금지, `context_sha256` 무결성 검증.
  2. stdlib 기반 `cell_failure_context.py`: `redact_context()`(사설/Tailscale IP·홈 경로·토큰 키 마스킹), `compute_measured_vetoes()`(16개 결정론적 거부 코드), `build_allowed_fallback_menu()`(9개 동사·Stratum A/B/C·정책→IK 무승인 차단·깊이 2 제한), `write_bundle()`(원자적 스테이징·보존 `200/50/512 MiB`·hold 핀), `list_bundles()`, `load_bundle()`, `resolve_asset()`(심볼릭 링크·경로 탈출·SHA 불일치 거부), `check_fence()`(`409 STALE_FAILURE_CONTEXT`).
  3. 교차 검증 단위 테스트: `cell_failure_context.py`가 만든 번들이 `core_common.protocol.cell_failure_context.CellFailureContext`를 무보정으로 통과하는지 확인.
- **완료 기준 / 검증:**
  - `deploy/robot/omx/cell_failure_context.py` `< 400`줄 확인, LF 확인, `rosy_harness.py lint` 0 error, `size_range.py` 통과.
  - `remote_pytest.py` (`test/test_omx_failure_context.py`, `test/architecture/test_document_placement.py`, `test/architecture/test_platform_parts.py`) + `known_failures.py` 통과.

---

### [x] TODO 2 — PR-2 (`#565`): D-430 안전 태그 보완 + `:8781` 토큰 분리·게이트 + `cell_task_worker` 오프라인 경화
- **안전 태그:** **YES — D-430 (`Safety-Review:` trailer + 독립 리뷰 필수)**
- **대상 파일:**
  - `tools/harness/platform_parts.yaml`: `safety_review_paths`에 `cell_job_api.py`, `cell_job_spec.py`, `cell_recovery.py`, `cell_task_transport.py`, `cell_vlm_orchestrator.py`, `cell_envelope_review.py`, `pipeline_cell_task_routes.py`, `pipeline_camera_routes.py`, `pipeline_evidence.py` 추가.
  - `deploy/robot/omx/cell_task_worker.py` (378줄 — 헬퍼를 `cell_task_transport.py` 또는 신규 헬퍼로 분리해 `< 400` 유지): `_bounded_safety_listing` 3상태(`EXPLICIT_STOP` vs `FEED_UNAVAILABLE` vs `OK`) 분리; 통신 두절 시 `cell-task-worker:*` 임대 및 무임대 활성 청크에만 `human-hold\n` 전송.
  - `deploy/robot/omx/cell_job_api.py` (348줄) & `deploy/robot/omx/cell_job_spec.py` (383줄 — 스펙 사전 분해로 `< 400` 유지):
    - `--machine-token-file` / `--human-token-file` 분리(`cell-job-machine`은 `person_at_switch: true`·시운전 이동 작업에 `403 MACHINE_COMMISSIONING_FORBIDDEN`, 서버 바인딩 `proposer` 강제, `audit.jsonl`에 `principal_role`/`principal_id` 기록).
    - `Runner.start`(warm 재사용 포함)에서 `omx_incident.status(arm)`, 피어 A/B 접힘, 온라인 시 Fleet 안전 상태, D435 `depth-d435.lock` 확인.
    - 오프라인 정적 화물 이동 시 `cell-state-dirty-<arm>.json` 기록, `Idempotency-Key` 멱등성 저장, `act_backend`(`ROSY_ACT_BACKEND`)·`goal_slot` 전달 지원.
  - `deploy/robot/omx/cell_upkeep_checks.py`: `check_boards(mode="autonomous"|"teleop")` 분리.
  - `deploy/robot/omx/cell_zone_verification.py`, `cell_task_exec.py` (382줄 → 헬퍼 분리), `cell_auto_pick.py` (398줄 → 헬퍼 분리): `depth-d435.lock`, 직접 `:8781` 폴백 실행의 `zone_verification` 활성, `attempts[].zone_verification` 출력.
  - D-226 템플릿/ignore: 신규 머신 토큰 파일 경로가 있다면 `MUST_IGNORE`·`.gitignore`·`MUST_TRACK` 예시 파일 동시 반영.
  - API 조각: `python tools/new_record.py api --surface cell --slug omx-cell-job-api-auth-and-safety --title "..."`
- **검증:** `rosy_harness.py lint`, `size_range.py`, `test_safety_separation.py`, `test_omx_cell_job_api.py`, `test_omx_cell_task_worker.py`, `test_omx_upkeep.py`, `test_document_placement.py`.

---

### [x] TODO 3 — PR-3 (`#624`): `:8781` 실패 컨텍스트·준비 상태 HTTP + 상시 `Ring` + 영상/데이터셋/스테이징 작업 + 스텁 제거
- **안전 태그:** **YES** (`cell_job_api.py`, `cell_job_spec.py`, `cell_policy_drive.py`, `cell_auto_pick.py` 포함 시 `Safety-Review:` 필수)
- **대상 파일:**
  - `deploy/robot/omx/cell_evidence.py`, `cell_hooks.py`, `cell_transfer.py`: `FifoCell.frame_receipt()` 사용(무시된 `304` 캐시 제거), `cell_auto_pick` 모든 비-`placed` 종료에서 번들 저장, `omx_incident_fleet.py`(394줄 — 헬퍼 분리)에서 손목 카메라 포함·요약 `facts` 첨부 및 상대 `Path("incidents")` 버그 수정.
  - `deploy/robot/omx/cell_policy_drive.py` (335줄) / `cell_policy_timing.py` / `cell_policy_paced.py` / `cell_policy_handoff.py`: 비동기 제어 루프 밖에서 상시 `Ring`·`tip_view`·`cell_failure_context.write_bundle()`·구조화 실패 기록 연결(`MAX_OBSERVATION_AGE_S = 0.6 s` 비침해).
  - `deploy/robot/omx/cell_job_api.py` + `cell_job_spec.py` + `cell_job_client.py`:
    - `GET /readiness`, `GET /failures`, `GET /failures/latest`, `GET /failures/{bundle_id}`, `GET /failures/{bundle_id}/assets/{filename}`, `GET /jobs/{id}`(`structured_result`, `failure_bundle_id`), `GET /frame/{view}.jpg` 헤더 보존.
    - 신규 비-이동 작업: `upkeep_check`, `capture_clip`(1..15 s, MP4 `<= 16 MiB`, arm/D435 잠금 미사용), `convert_episodes`(`episode_recorder.convert`, `DO_NOT_TRAIN` 차단), `transfer_dataset`(`omx_collection_transfer`, `CLOSED` 전용), `stage_policy_bundle`(`:8768` SHA 검증 원자 배치).
  - `deploy/robot/omx/bench_record_pipeline.py`: `109-145`줄 가짜 `augment`·가짜 `ckpt://` 스텁 제거 후 fail-closed 전송 상태 머신으로 교체.
  - API 조각: `python tools/new_record.py api --surface cell --slug omx-cell-failure-context-and-media-jobs --title "..."`
- **검증:** `rosy_harness.py lint`, `size_range.py`, `test_omx_failure_context.py`, `test_omx_cell_job_api.py`, `test_omx_cell_evidence.py`, `test_omx_policy_drive.py`, `test_omx_bench_record.py`.

---

### [x] TODO 4 — PR-4 (`#629`): AI 폴백 9동사 커널 + `cell_vlm_orchestrator` 수렴 + `policy -> IK` 무승인 교체 차단
- **안전 태그:** **YES — D-430 (`Safety-Review:` trailer + 독립 리뷰 필수)**
- **대상 파일:**
  - `deploy/robot/omx/cell_diagnose.py`: 정책 실패/시간초과/엔벨로프/`z_gate` 원인 추가 및 `classify_failure()` 추가.
  - `deploy/robot/omx/cell_recovery.py`: `FALLBACK_VERBS`, `MAX_AI_FALLBACK_PER_TASK = 2`, 순수 정책 커널 `select_fallback()`, `escalate_to_request()`(`cell_requests.open_request` 연동) 추가.
  - `deploy/robot/omx/cell_vlm_facts.py` & `cell_vlm_orchestrator.py`: `:8781 /failures/latest`·`/readiness` 소비, 동적 `allowed_fallback_menu` 스키마 제한, `expected_context_sha256`+`expected_cell_state_gen` 펜스, `exit == 0` 완료 오판 제거(이중 `folded`+`z_gate`/`verify`+`post_incident` 검증), `cell_choices`/`cell_decisions`/에피소드 분리 봉인 기록.
  - `deploy/robot/omx/cell_task_act.py` & `cell_executor.py`: ACT 실패 시 정규화 `failure_class` + 봉인 `episode_ref` 반환(즉석 IK 교체 금지), `cell_executor.outcome()`에 ACT 결과 기록.
  - `deploy/robot/omx/cell_failure_scenarios.py` + `test/test_omx_cell_recovery.py`, `test/test_omx_cell_vlm_orchestrator.py`: 정책 실패·`z_gate`·깊이 2 한도·`repeat_unknown`·`STALE_FAILURE_CONTEXT` 시나리오 추가.
- **검증:** `rosy_harness.py lint`, `size_range.py`, `test_omx_cell_recovery.py`, `test_omx_cell_vlm_orchestrator.py`, `test_omx_collect_plan.py`.

---

### [x] TODO 5 — PR-5 (`#634`): Fleet-R 권한·인터록·Assistant 및 Intent 경화
- **안전 태그:** **YES — D-430 (`Safety-Review:` trailer + 독립 리뷰 필수)**
- **대상 파일:**
  - `operations/fleet/fleet/server/sitemap/pipeline_evidence.py` (582줄 — 수정 전 반드시 헬퍼 분리해 `<= 600` 준수).
  - `operations/fleet/fleet/server/sitemap/{pipeline_cell_task_routes,pipeline_camera_routes,pipeline_routes}.py`:
    - `POST /api/fleet/pipeline/cell-tasks`의 `PROPOSED -> QUEUED`(`proposer != approved_by`), `POST .../admit`, `request_key` 멱등성, SQLite 영속 `authority_epoch`·`dispatch_generation`·`stop_generation`·확인 저장소.
    - `expected_context_sha256`·`expected_readiness_digest`·`expected_dispatch_generation` 단일 트랜잭션 CAS(`409 STALE_FAILURE_CONTEXT`), 후속 재시도 예산 1 + 깊이 2 제한(`409 FALLBACK_RETRY_LIMIT_EXCEEDED`), `act_policy`→`guarded_pick` 폴백 자동 수락 거부(`403 POLICY_FALLBACK_REQUIRES_NAMED_APPROVAL`).
    - 서버 도출 `interlock_scope: "amr_bed" | "cell_internal"`, `GET /api/fleet/pipeline/cells/{cell_id}/readiness`.
  - `operations/fleet/fleet/server/assistant/{context,routes}.py`, `operations/decision/src/rosy/decision/model_tool_catalog.py`, `contracts/foundation/core_common/intent.py`: 범주형 OMX `AssistantFact`, `scope='cell'` 도구 3종(`get_cell_readiness`, `get_cell_failure_context`, `propose_cell_fallback`), `FORBIDDEN_KEYS` 팔/PLC 원시 키 확장.
  - API 조각: `python tools/new_record.py api --surface fleet --slug fleet-cell-task-propose-admit-and-readiness --title "..."`
- **검증:** `rosy_harness.py lint`, `size_range.py`, `operations/fleet` + `operations/decision` + `contracts/foundation` 원격 pytest.

---

### [x] TODO 6 — PR-6 (`#572`): Learning Center `:8768` 서비스 토큰 + ONNX 서빙 + D-358/D-878 외부 전송 관문
- **안전 태그:** 없음 (`learning` + `operations/decision`, 비안전 경로)
- **대상 파일:**
  - `learning/curation/perception/review_app.py` (599줄 — 헬퍼 모듈로 라우트/인증 위임해 `<= 599` 유지), `learning_collaboration.py`, `canonical_web.py`, `omx_center_web.py`, `ladder_web.py`:
    - `--service-tokens` 기반 `service_offline_job` 스코프 bearer(오프라인 읽기/제출 허용, `/ladder/decision`·`/promotion-requests` 승인·`/hub-upload`·`/cuda-run`·`/frames/*` `403` 차단).
    - `canonical_web.py`에 `GET /api/learning/canonical/runs/{rid}/bundle-manifest`·`/file/{relpath}` 추가.
  - `learning/training/omx/canonical_workers.py`: `run_cell_live_check`에 `export_cell_onnx()` + OpenVINO 패리티 검증 추가.
  - `operations/decision/src/rosy/decision/`: Argon/외부 VLM 호출용 D-358 `EgressPolicy`(기본 DENY, 등급 분리, IP/경로/비밀 마스킹) + D-878 `strict: true` JSON 스키마 어댑터.
- **검증:** `rosy_harness.py lint`, `size_range.py`, `test/learning/perception/`·`learning/training/omx/test/`·`operations/decision` 원격 pytest.

---

### [x] TODO 7 — PR-7 (`#566`): `agy` 12-Tool stdlib HTTP 브리지 + 통합 회귀 시험
- **안전 태그:** 없음 (`tools/remote/` 또는 `tools/<subdir>/` 등록 시 `platform_parts.yaml` root 추가)
- **대상 파일:**
  - `tools/remote/rosy_agent_bridge.py`: stdlib HTTP 전용 12개 도구(`cell_readiness`, `cell_failure_context`, `cell_frame`, `cell_upkeep_check`, `cell_dry_run`, `fleet_propose_cell_task`, `job_status`, `cell_open_human_request`, `cell_capture_clip`, `cell_dataset_pipeline`, `learning_run_job`, `learning_stage_bundle`) MCP stdio / CLI 어댑터. 타 파트 import·SSH 전송·실제 실험실 주소 기재 금지.
  - `test/test_rosy_agent_bridge.py`: 목 HTTP 서버 3평면(`:8781`, Fleet-R, `:8768`)을 상대로 12개 도구 계약, `409 STALE_FAILURE_CONTEXT` 처리, `403` 권한 거절, D-226 무누출 검증.
- **완료 기준 / 검증:** `rosy_harness.py lint`, `size_range.py`, `test/test_rosy_agent_bridge.py`, `test/architecture/test_document_placement.py`, `test/architecture/test_platform_parts.py` 원격 pytest 통과.

---

## 3. 별도 현장·후속 트랙 (본 계획 코드 PR과 병행/후행)

1. **현장 물리 복구 (`Slice 1`):** `rosy-fleet-r` 재연결, `arm_s_top`·`arm_b_wrist` USB 재연결 및 180° 방향 대조, 감독 `arm_b home` → `arm_a`/`arm_b` `remap` (`--commissioning --person-at-switch`).
2. **D-1057 현장 수용 (`Slice 4`):** 4개 측정 결함(`floor_depth_mm` 9 mm 표류, 깊이 잡음, Pose-2 11–12 px 오차, `attempts[].zone_verification`) 해결 및 `cell_envelope_review.py --confirm-physical-review` 뒤 `ROSY_FLEET_CELL_AB_RELEASE_ENABLED=1`.
3. **`arm_b` Fleet ACT 및 양팔 성숙화 (`Slice 5`):** 3개 D-1024 L3 블로커 해소, `cell_task_act.py:103`·`pipeline_cell_task_routes.py:170` `arm_b` 개방, `cell_two_arm.py` 별도 PR.
