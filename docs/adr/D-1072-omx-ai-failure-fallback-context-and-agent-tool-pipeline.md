## D-1072 OMX AI 실패 폴백 제어·풍부한 컨텍스트 번들 및 에이전트 Tool·HTTP 파이프라인

**Status:** Proposed (2026-11-23, 4인 병렬 패널 합의; 코드 구현·D-430 독립 안전 리뷰·현장 수용은 [구현 계획](../plans/2026-11-23-omx-ai-failure-fallback-and-agent-pipeline.md) TODO 슬라이스별 진행).

관련 결정: [D-358](D-358-er2-feedback-outbox-and-replan-fencing.md) · [D-427](D-427-platform-three-parts-middleware-operations-learning.md) · [D-429](D-429-five-concerns-control-port-and-site-devices.md) · [D-430](D-430-safety-as-a-separate-concern.md) · [D-516](D-516-offline-decision-model-replay-boundary.md) · [D-793](D-793-omx-learned-policy-execution-approval-gate.md) · [D-878](D-878-structured-model-output-schema-and-provider-wire.md) · [D-911](D-911-omx-native-reviewed-operating-envelope.md) · [D-935](D-935-arm-s-payload-bound-amends-d911.md) · [D-1019](D-1019-omx-carry-redirects-to-declared-alternate-destinations.md) · [D-1024](D-1024-omx-learned-policy-supervised-real-trial-fast-track.md) · [D-1039](D-1039-ai-assessor-kind-limited-incident-clear.md) · [D-1047](D-1047-cell-s-automatic-departure-and-link-failure-clear.md) · [D-1048](D-1048-automatic-fold-of-a-held-extended-arm.md) · [D-1057](D-1057-cell-task-admission-evidence.md) · [D-1061](D-1061-records-fragments-merge-queue.md) · [D-1065](D-1065-omx-camera-role-names.md).

### D-427 · D-429 · D-430 관계표

| 기준 ADR | 유지되는 계약 | 이번 ADR에서의 변경 |
|---|---|---|
| D-427 (파트 소유) | `middleware/`(장치 안전·제어), `operations/`(Fleet·Decision·World), `learning/`(수집·학습·평가·레지스트리), 공용 `contracts/`·`integrations/`·`shared/web/` 3파트+공용층 및 import 방향을 유지한다. `learning` 산출물은 런타임 import 없이 고정 산출물로만 전달하며, `deploy/robot/omx`는 셀 실행 앱이다. | 새 최상위 폴더를 만들지 않는다. 실패 맥락·제안·승인 상태는 `operations/fleet`·`operations/decision`과 `contracts/foundation`에, 셀 읽기/복구 맥락은 `deploy/robot/omx`에, 외부 `agy`/Argon 어댑터·CLI는 `tools/remote/` 또는 `tools/<subdir>/`(별도 `platform_parts.yaml` root 등록 필수)에 둔다. |
| D-429 (다섯 관심사·포트·판단 층) | 판단 7층 경계(숙고형 `operations/decision`은 후보만, 조정 `operations/fleet`은 원장·승인·인터록, 장치 단일 writer는 `DeviceControlPort`/OMX owner)와 `POLICY_DISPATCH_ENABLED=False`, 닫힌 모델 도구 카탈로그(`read_only`/`candidate_writing`만)를 유지한다. 예약 승인(stale approval queue)은 금지한다(D-429 §3). | 새 판단 층을 추가하지 않는다. AI 실패 폴백과 `agy` 도구는 기존 **숙고형(deliberative)** 층에 고정하며, `core_common.intent` `FORBIDDEN_KEYS`에 팔/PLC 원시 키를 추가하고 실물 팔 구동을 `/api/fleet/do` 밖에 둔다. |
| D-430 (safety 관심사·분리 불변식·변경 통제) | 안전 체인 7층, 분리 불변식 1~5(`safety`는 decision/learning/모델 SDK import 금지, 모델 출력은 안전 기능·해제 불가, 단일 writer, 물리 E-stop 독립), fail-closed 래치(링크 복귀·재시도 자동 해제 금지), `Safety-Review:` trailer + 독립 리뷰(§5)를 유지한다. | 기존 가드 한계값(`max_shift_px=6.0`, D-935 `0.08 kg`, `z_gate`, `SETTLE_TOL=3.0`, D-1039/1047/1048 `3/24h`)을 완화하지 않는다. 누락된 셀·Fleet 게이트 경로(`cell_job_api.py`, `cell_job_spec.py`, `cell_recovery.py`, `cell_task_transport.py`, `cell_vlm_orchestrator.py`, `cell_envelope_review.py`, `pipeline_cell_task_routes.py`, `pipeline_camera_routes.py`, `pipeline_evidence.py`)를 `platform_parts.yaml`의 `safety_review_paths`에 등록해 §5 구멍을 닫는다. |

### Context

- **실셀 실패 맥락의 파편화와 정책 실패 공백:** `main`(`7645dd1f10`) 기준 학습 정책 실행 경로(`deploy/robot/omx/cell_policy_drive.py`, `cell_policy_timing.py`, `cell_policy_paced.py`, `cell_policy_handoff.py`)는 `cell_evidence.Ring`·`Stills`·`cell_tip_view`·`cell_why`·`attempts.jsonl`·`decisions.jsonl`·사후 `z_gate`를 남기지 않는다. `cell_auto_pick.py` 경로에서도 `cell_hooks.Stills`는 `config["evidence"]` opt-in 및 `status["contact"]`일 때만 기록되어 `empty`/`misaligned`/`still_holding`/`verify_fail` 시 번들이 없고, `omx_incident_fleet.py:212`는 손목 카메라 프레임을 버리며, `cell_job_api.py`는 `:8767` 프레임 헤더(`X-Frame-Seq`, `X-Source-Stamp`)를 제거하고 작업 로그를 마지막 `4000`바이트로 잘라 구조화 결과를 잃는다.
- **실셀 실행 방식과 ROS 2 경계:** 실물 `rosy-arm-cell`은 `omx.disabled.yaml`(`enabled: false`) 상태에서 `record_session.py --chunks`, FIFO(`chunk-io-*`), `SnapshotChannel`, `:8781` HTTP(`cell_job_api.py`), `cell_task_worker.py` HTTPS 폴링으로 동작한다. 반면 ROS 2(`run_hardware_owner.py`, `omx_adapter/ros_*.py`, `omx_ladder.py`)는 `ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST`·Gazebo 실행 계약 검증 전용이다.
- **조작·인증·워커 경계의 취약점:** `:8781`은 단일 정적 bearer 토큰으로 원시 JSON `person_at_switch: true`·`operator`·`proposer`를 신뢰하고 warm 세션 재사용 시 `omx_incident`와 피어 A/B 접힘을 확인하지 않는다. `cell_task_worker.py:76-105,169-172`는 Fleet 통신 두절과 명시적 `active_estop`/`human_detected`를 구분하지 못해 모든 팔 FIFO에 `human-hold\n`을 반복 전송한다.
- **영상·학습 브리지와 에이전트 툴 부재:** `bench_record_pipeline.py:103-153`은 실제 증강/학습 없이 가짜 `ckpt://{aug_name}-step1000` 완료를 반환하는 스텁이다. Learning Center(`:8768`)는 백엔드(`canonical_web.py`, `omx_center_web.py`, `ladder_web.py`)를 갖췄으나 브라우저 쿠키+CSRF(`review_app.py:358-368`, `learning_collaboration.py`)를 강제해 `agy` 등 헤드리스 에이전트 호출이 막혀 있고, `canonical_workers.py:507`은 `export_cell_onnx()`와 `bundle-manifest` 서빙을 연결하지 않았다. `agy`/Argon용 ROSY MCP·Tool 어댑터도 없다.

### Decision

#### 1. 풍부한 실패 컨텍스트 번들 (`rosy.omx-failure-context.v1`) 및 저장·HTTP 조회

- **단일 정본 번들 스키마(`contracts/foundation/core_common/protocol/cell_failure_context.py`, `deploy/robot/omx/cell_failure_context.py`):**
  - `bundle.json`은 최대 **`48 KiB`**(`FAILURE_CONTEXT_MAX_BYTES = 49_152`), 중첩 깊이 **`<= 6`**, `allow_nan=False`, 정렬 키 정규화 JSON으로 제한하며 **인라인 base64 이미지를 금지**한다. `context_sha256`는 `context_sha256`와 읽기 전용 `freshness` 필드를 제외한 정규 JSON의 SHA-256이다.
  - 필수 4축 정보: ① **측정·정지 진실**(결과/단계/원인, `cell_why` 판정 및 `free_lag` 대비 수치, 관절 위치·목표·추종 오차·홈 오차·PWM·전류·온도·정책 청크 지연, `still_holding`·이중 `fold_readback`/`live_fold`, `omx_incident` 상태, `trace-tail.jsonl` SHA-256), ② **공간·보정 진실**(37개 정본 사이트, `top` 카메라 이동 px, 누락 맵, `z_gate`/배치 검증, 검출 객체, A/B 팔 임대·잠금·피어 접힘·Fleet 안전 상태), ③ **다중 시점 시각 증거**(`camera_manifest` + `gaps`, `frame_receipt()` 기반 `source_seq`·`source_stamp`, `cell_tip_view` FK 집게 끝 크롭, `cell_evidence.Ring` 전/중/후 프레임 최대 24장, `control_ref`, `depth_summary`), ④ **이력·제약**(최근 `attempts`/`decisions`/`why`/`knowledge`/`choices`, `repeat_unknown` 카운터, 서버가 계산한 **16개 `measured_vetoes`**, **`allowed_fallback_menu`**).
  - **결측 센서 패딩 금지:** 물리적으로 빠진 카메라(`arm_b_wrist` 등)는 합성 검은 프레임을 채우거나 조용히 생략하지 않고 `camera_manifest`의 `missing_device`와 `gaps`에 명시한다.
- **저장소·보존·신선도(`deploy/robot/omx/cell_failure_context.py`):**
  - CWD 상대 경로(`Path("incidents")`)를 금지하고 `${ROSY_OMX_STATE_DIR:-~/rosy-omx}/failure-bundles/`에 임시 스테이징 → 파일 SHA-256 계산 → `fsync` → 원자적 rename 순으로 기록한다.
  - 실패 `200`건·기준 `control` `50`건·총 `512 MiB` 상한으로 정리하되, 열린 `HOLD-<arm>.json`·`attempts.pending.json`·미전송 outbox가 가리키는 번들은 **삭제에서 영구 핀(보호)** 한다.
  - `cell_evidence.Ring`은 opt-in이 아니라 `cell_auto_pick`의 모든 비-`placed` 종료와 `cell_policy_drive`(timed/paced/hybrid/taught) 전체에 상시 연결하되 제어/추론 루프 밖 스레드에서 `MAX_OBSERVATION_AGE_S = 0.6 s`를 침해하지 않게 수집한다.
- **`:8781` 무-SSH HTTP 및 Fleet 미러:**
  - `cell_job_api.py`에 `GET /readiness`(`rosy.cell-readiness.v1`, `max_age_s <= 5.0`), `GET /failures`, `GET /failures/latest`, `GET /failures/{bundle_id}`, `GET /failures/{bundle_id}/assets/{filename}`(`ETag`, `X-Cell-State-Gen`, 경로 탈출·심볼릭 링크 차단)를 추가하고, `GET /frame/{view}.jpg`는 `:8767`의 `X-Frame-Seq`·`X-Source-Stamp`·`ETag` 헤더를 보존한다.
  - Fleet가 온라인이면 `omx_incident_fleet.py`는 `ArmIncidentReport.facts`(`<= 12 KiB`)에 번들 요약(`bundle_id`, `context_sha256`, `attempt_cause`, `why`, `measured_vetoes`)을 싣고 `tip_crop`·손목 포함 우선 프레임(`<= 24`장)을 기존 incident evidence 경로로 올린다(상시 영상 중계 없음, D-136·D-516).

#### 2. 3계층 실패 분류·9개 닫힌 폴백 동사·정책→IK 무승인 교체 금지

- **3계층 분류(Strata):**
  - **Stratum A (결정론적 즉시 반사, LLM 미호출):** 실시간 안전 정지(`human-hold`, 확장 팔 토크 유지 D-1048), `cell_feel` 축 이동, `cell_grasp_debate` `reinsert`(최대 1회), 실패 에피소드 즉시 봉인(`outcome="failure"`).
  - **Stratum B (AI 선택 가능 폴백):** **Tier 2 자동 허용**은 기존 ADR 범위로만 엄격히 제한한다(D-1019 동작 전 목적지 가득 참 `redirect_alt_dest`, D-1039/D-1047/D-1048 `3/24h` 조건 충족 시 자동 정리·접기). 그 외 **모든 교차 실행기 폴백(`policy -> IK`)과 D-911 범위 밖 복구 동작은 Tier 1(AI 제안 → 기명 인간 운영자 승인, `approved_by != proposer`)** 만 허용한다.
  - **Stratum C (인간 전용 래치):** 하드웨어 래치 오류(`latched`), 케이블 감김(`windup_hits`), `HOLDING_HIGH`/`ALL_PATHS_BLOCKED`, `camera_moved > 6.0 px`, `missing_map`, `repeat_unknown`, Fleet `HUMAN_HOLD`/`active_estop`/`ABORTED`, `4th clear / 24h`. AI는 Tier 0 진단과 `cell_requests.py` 구조화 요청 발행만 수행한다.
- **9개 닫힌 폴백 동사(`FALLBACK_VERBS`):** `reinsert`, `release_and_rise`, `align_push`, `retry_ik_slower`, `retry_ik_alt_axis`, `redirect_alt_dest`, `home_unwedge`, `propose_ik_fallback_for_policy`, `escalate_human` 외 원시 관절/PWM/토크/FIFO 명령 생성은 금지한다.
- **정책→IK 즉석 교체(in-place swap) 절대 금지:** `act_policy`/`hybrid` 실패 시 같은 `task_id`·`handoff_lease_id`·소비된 `presence-confirm` 아래에서 `cell_auto_pick`을 직접 호출하지 않는다. 반드시 실패 에피소드를 봉인하고 팔을 접음/무보류로 확인한 뒤 **새 `PROPOSED` 작업 + 기명 운영자 승인**을 거친다(자동 수락 시도 시 Fleet가 `403 POLICY_FALLBACK_REQUIRES_NAMED_APPROVAL`로 거부).
- **이중 루프 방지·TOCTOU CAS 펜스·배움 환류:**
  - `(parent_task_id, attempt_id)`당 후속 폴백 제안 **`1`회** AND `root_task_id` 기준 **최대 연쇄 깊이 `2`**(`fallback_chain_depth >= 2` 시 `409 FALLBACK_RETRY_LIMIT_EXCEEDED` + `escalate_human`), 기존 `tried[cause]`·`repeat_unknown`·`SLOWEST=0.25`·`max_reinsert=1`·`3/24h` 캡을 유지한다.
  - 모든 폴백 제안과 승인은 `expected_context_sha256`, `expected_readiness_digest`, `expected_cell_state_gen`/`expected_dispatch_generation`/`expected_stop_generation` 및 `ttl_s <= 30.0 s`를 바인딩하며, 단일 SQLite 트랜잭션 검증에서 어긋나면 **`409 STALE_FAILURE_CONTEXT`** 로 즉시 거절한다.
  - `cell_vlm_orchestrator.py`는 `cell_recovery.py` 단일 정책 커널의 얇은 어댑터로 수렴하고, HTTP `200`/`exit == 0`이 아닌 이중 `folded`·`z_gate`/`verify.inside`/`took_one`·사후 `incident_status` 무보류를 검증한 뒤 `cell_choices`, `cell_decisions`, `cell_failure_scenarios`, 분리된 에피소드 원장에 기록한다.

#### 3. 3평면 비-ROS HTTP 경계 및 `:8781`·워커 경화

- 실셀 `agy` 도구는 **Cell `:8781`**, **Fleet-R HTTPS**, **Learning Center `:8768`** 세 인증된 HTTP 평면에만 결합하며, 실셀용 새 ROS 2 브리지를 두지 않는다. `:8767`과 `:8771`은 로컬/사람 전용으로 유지한다.
- `:8781` 토큰을 `cell-job-machine`(읽기·dry-run·실패 컨텍스트·D-911 검토된 비-AMR 정적 작업만 허용, `person_at_switch: true` 시 `403 MACHINE_COMMISSIONING_FORBIDDEN`, 서버가 `proposer` 강제 바인딩)과 `cell-job-human`으로 분리하고, warm 세션 재사용 시 `omx_incident`·피어 A/B 접힘·Fleet 안전을 재확인한다.
- `Idempotency-Key`, `GET /jobs/{id}` 구조화 결과, `upkeep_check`(`cell_upkeep_checks.py` `autonomous` vs `teleop` 분리), `cell_policy_drive`의 `act_backend`+`goal_slot`, 제한된 영상/데이터셋/스테이징 작업(`capture_clip`, `convert_episodes`, `transfer_dataset`, `stage_policy_bundle`), `depth-d435.lock`을 추가하고 `bench_record_pipeline.py:103-153`의 가짜 `augment`/`ckpt://` 스텁을 제거한다.
- `cell_task_worker.py`의 안전 조회를 `EXPLICIT_STOP`(전체 팔 무조건 `human-hold`) / `FEED_UNAVAILABLE`(`cell-task-worker:*` 임대 또는 무임대 활성 청크에만 `human-hold`) / `OK` 3상태로 분리한다.

#### 4. Fleet-R 권한·Assistant 및 D-358/D-878 외부 전송 관문

- 정본 `/api/fleet/pipeline/cell-tasks`에 `PROPOSED -> QUEUED`(`proposer != approved_by`), `request_key` 멱등성, SQLite 영속 세대·확인 저장소, 서버 도출 `interlock_scope: "amr_bed" | "cell_internal"`(정적 `belt -> pallet` 작업의 `_ready_amr` 오결합 해소), `GET /api/fleet/pipeline/cells/{cell_id}/readiness`를 추가한다.
- `assistant/context.py`에는 부동소수점 없이 범주형 OMX 사실만 넣고, `model_tool_catalog.py`는 `scope='cell'` 읽기/제안 도구(`get_cell_readiness`, `get_cell_failure_context`, `propose_cell_fallback`)만 노출하며, `contracts/foundation/core_common/intent.py` `FORBIDDEN_KEYS`를 확장한다.
- Argon 등 외부 클라우드 LLM 호출은 D-358 §6 기본 거부(default DENY) `EgressPolicy`, 데이터 등급 분리, 사설/Tailscale IP·경로·비밀값 결정론적 마스킹(`redact_context`), D-878 `strict: true` JSON 스키마(복구 파서 금지, 오류 시 `escalate_human`)를 통과해야 한다.

#### 5. Learning Center (`:8768`) 서비스 토큰 및 표준 ONNX 서빙

- `review_app.py`·`learning_collaboration.py`에 `--service-tokens` 스코프 bearer(`{"view", "service_offline_job"}`)를 추가해 `agy`의 오프라인 학습·DART 수집·L1 평가 요청은 허용하되 `/ladder/decision`, `/promotion-requests` 승인, `/hub-upload`, `/cuda-run`, `/frames/*`, `/accounts/*`는 `403`으로 차단한다.
- `canonical_workers.py:507`이 `export_cell_onnx()`를 호출하고 `canonical_web.py`가 `bundle-manifest`와 `file/{relpath}`를 서빙해 셀 `stage_policy_bundle`이 SHA-256 검증 후 원자적 스테이징할 수 있게 연결한다.

#### 6. 12-Tool `agy` MCP/CLI 브리지 및 D-430 누락 태그 폐쇄

- `tools/remote/rosy_agent_bridge.py`에 stdlib HTTP 전용 12개 도구(`cell_readiness`, `cell_failure_context`, `cell_frame`, `cell_upkeep_check`, `cell_dry_run`, `fleet_propose_cell_task`, `job_status`, `cell_open_human_request`, `cell_capture_clip`, `cell_dataset_pipeline`, `learning_run_job`, `learning_stage_bundle`)를 두고 SSH 키와 타 파트 import를 금지한다.
- `tools/harness/platform_parts.yaml`의 `safety_review_paths`에 누락된 셀/Fleet 안전 게이트 경로 9개를 등록한다.

### Consequences & Invariants

- 실패 시 AI가 추측성 정지 사진만 보는 대신 측정값·결측 센서 목록·금지 사유·허용 동사 메뉴를 함께 받아 안전 경계 안에서만 폴백을 제안할 수 있다.
- 모든 API 변경 조각은 D-1061에 따라 `docs/reference/api-changes/` 조각으로 제출하며, `deploy/robot/omx/*.py` `< 400`줄(`rosy_harness.py:395-397`)과 D-766 커밋 단위 `<= 600`줄(`size_range.py`, `size_ratchet.txt` 비어 있음) 및 LF-only 규칙을 지킨다.
- 호스트 pytest(`tools/remote/remote_pytest.py`, D-584) 통과는 코드 계약 검증이며, 실셀 수용(`ROSY_FLEET_CELL_AB_RELEASE_ENABLED=1`, `Slice 1` 물리 복구, `cell_envelope_review.py --confirm-physical-review`)은 별도 현장 게이트다.

### Validation

- **PR-0 (문서):** `python tools/harness/rosy_harness.py lint` 0 error, `size_range.py` 통과, `test/architecture/test_document_placement.py`·`test/test_records_fragments.py`·`test/test_network_topology_contracts.py` 원격 pytest 통과.
- **TODO 1~7 (코드):** 각 슬라이스마다 `< 400`/`<= 600` 줄 제한, D-430 `Safety-Review:`(해당 PR), `remote_pytest.py` + `test/known_failures.py` 기준 통과 후 다음 단계로 진행한다.
