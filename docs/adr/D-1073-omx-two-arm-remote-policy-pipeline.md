## D-1073 OMX 팔별 6축 원격 GPU 정책 추론 및 두 팔 실시간 사전 청크 충돌 가드 파이프라인

**Status:** Proposed (2026-11-23). 관련 결정: [D-427](D-427-platform-three-parts-middleware-operations-learning.md) · [D-429](D-429-five-concerns-control-port-and-site-devices.md) · [D-430](D-430-safety-as-a-separate-concern.md) · [D-770](D-770-fleet-omx-autonomous-imitation-pipeline.md) · [D-778](D-778-bimanual-workcell-foundation.md) · [D-780](D-780-workcell-coordinator-peer-stop-source-and-named-barriers.md) · [D-854](D-854-omx-policy-runner-and-action-space.md) · [D-911](D-911-omx-native-reviewed-operating-envelope.md) · [D-983](D-983-two-arm-timing-on-fixed-paths.md) · [D-1024](D-1024-omx-learned-policy-supervised-real-trial-fast-track.md) · [D-1065](D-1065-omx-camera-role-names.md).

### Context

- 현재 확보된 OMX 학습 데이터(단일 팔 219회 + Isaac 시뮬레이션)는 팔별 6축(`shoulder_pan`, `shoulder_lift`, `elbow_flex`, `wrist_flex`, `wrist_roll`, `gripper`) 단일 팔 작업에 맞춰져 있으며, 12축 결합(simultaneous bimanual) 실물·시뮬레이션 에피소드는 없다.
- 셀 호스트(`rosy-arm-cell`) CPU에서 ACT 두 세션을 동시에 추론하면 청크 생성 지연으로 [D-1024](D-1024-omx-learned-policy-supervised-real-trial-fast-track.md)의 관측 신선도 한계(`MAX_OBSERVATION_AGE_S = 0.6s`)와 연속 청크 핸드오프 예산을 넘기기 쉽다.
- 반면 LAN 내 GPU 학습기(`<ai-pc-host>` 등)에서 `arm_a`·`arm_b`의 6축 ACT 체크포인트를 각자 서빙하고, 셀 제어 루프는 스레드 병렬로 원격 추론과 **실행 직전 swept-capsule + 영역 충돌 가드**를 통과한 청크만 `chunk_runner`에 적재하면 새 12축 데이터 수집 없이 두 팔의 동시/교대 작업을 안전 경계 안에서 수행할 수 있다.

### Decision

#### 1. 3파트·5관심사·안전 분리 매핑 (D-427 · D-429 · D-430)

| 계층/파일 | 소속 파트(D-427) | 책임 | 안전 경계 및 비권한 규칙(D-430) |
|---|---|---|---|
| `learning/training/omx/act_policy_http_server.py` | Learning | `arm_a`·`arm_b` 6축 ACT 체크포인트(`sha256` 고정) LAN HTTP(`GET /health`, `POST /infer`) GPU 추론 | `deploy/` 비의존, `torch`/`lerobot` 지연 임포트, NaN·비유한·형상 오류·리비전 불일치 시 4xx/500 fail-closed, 물리 제어권 없음 |
| `deploy/robot/omx/cell_remote_policy.py` | Operations | `LeRobotShadow` 호환 원격 클라이언트 (`RemotePolicyShadow`), `policy_environment = "remote_lerobot"` | `torch`/`lerobot` 비임포트, Bearer 토큰(선택/`--allow-insecure-loopback`), D-1065 정규 카메라 역할(`top`/`side`/`wrist`) JPEG 인코딩, strict timeout(`0 < timeout_s <= 2.0s`), 응답 리비전·shape `(n, 6)`·유한성 검증 |
| `deploy/robot/omx/cell_two_arm_guard.py` | Operations (Safety Guard 연동) | 두 팔 작업 쌍(`validate_two_arm_task_pair`) 및 실행 직전 swept-capsule + `mid` 상호배제 실시간 충돌 가드(`TwoArmChunkGuard`) | `omx_adapter.swept_volume.capsules` + `omx_adapter.coordination.{moved, thinned, clearance}` 재사용, 테이블 하한(`min_z_m`) 위반·상대 미확인·정지 상대 간섭 시 즉시 거부, 이동 중 상대/shared `mid` 점유 시 대기 후 timeout·교착 시 coupled stop 래치 |
| `deploy/robot/omx/cell_two_arm_policy.py` & `cell_two_arm_policy_cli.py` | Operations | 두 팔 스레드 병렬 정책 러너(`run_two_arm_policy`) 및 감독 CLI(`--dry-run` / `--commissioning --person-at-switch`) | `admit_chunk` 통과 전 `load`/`run policy` 전송 금지, D-911 `Authorization.authorize`/`checked`·D-1024 `--proposer != --operator` 필수, 임의 예외·타임아웃·충돌 거부 시 즉시 양팔 `human-hold` + `coupled_stop` 및 조건부 `safe_fold` |

> **참고:** 신규 파이프라인 파일들의 `tools/harness/platform_parts.yaml` 안전 태그 등재는 `docs/reference/shared-checkout.md`의 FULL CI 분리 원칙에 따라 별도 후속 PR로 처리한다.

#### 2. 두 팔 작업 정의 (Canonical Tasks · `shared/web/cell-site-map.json` 37-site 정본)

`shared/web/cell-site-map.json`의 정식 사이트 ID(`yard:r{1..3}-s{1,2}-t{1..3}`, `temp_a:r{1..3}-s1-t{1..3}`, `temp_b:r{1..3}-s1-t{1..3}`, `stand:r1-s1-t1`, `not_places:belt` 등)와 구역 분리(`zone_a`: `arm_a`, `zone_b`: `arm_b`, `mid`: 공용/벨트·야드 경합 구역)를 기준으로 아래 4개 작업만 허용한다.

| Task ID | 동작 패턴 | 팔별 허용 출발/목적 사이트 규칙 | 병렬·가드 규칙 |
|---|---|---|---|
| `T1_CONCURRENT_ZONE_SPLIT` | 양팔 **동시 비겹침** 작업 (`arm_a`는 A측, `arm_b`는 B측) | `arm_a`: `{belt, temp_a:*, stand:r1-s1-t1}`, `arm_b`: `{belt, temp_b:*}` (양팔이 동시에 같은 `mid` 경합 사이트를 점유하지 않으며, 동일 사이트/동일 스택 중복 금지) | 두 스레드가 각자 원격 GPU 추론 + 사전 `TwoArmChunkGuard.admit_chunk`를 통과할 때마다 **동시 실행** (실제 swept-capsule 마진이 `margin_m` 이상이면 양팔 무대기 동시 적재) |
| `T2_CONCURRENT_OUTBOUND_STAGING` | **출하 스탠드 동시 적재/정렬** (`arm_a`: 출하 스탠드·A버퍼, `arm_b`: B측 야드/임시 정리) | `arm_a`: `{temp_a:*, stand:r1-s1-t1}` 중 출하(`dst=stand:r1-s1-t1` 또는 `src=temp_a:*`), `arm_b`: `{temp_b:*, yard:r{1..3}-s{1,2}-t{1..3}}` | 팔별 고유 구역 우선 동시 진행, 캡슐 여유 `margin_m` 미만 또는 `mid_y_band` 진입 청크는 자동 직렬화(`mid` 상호배제) |
| `T3_SHARED_MID_ALTERNATING` | **공용 중앙(`mid`) 교대 작업** (`belt`·`yard:*`·`stand:r1-s1-t1` 교차 사용) | 두 작업 중 하나 이상이 공용 `mid` 구역(`belt`, `yard:*`, `mid` 플래그, `stand:r1-s1-t1` 경합 포함)을 통과/목표로 사용 (동일 단일 스택 목표 중복은 여전히 금지) | **시지각/추론(`infer`)과 전처리는 병렬**로 선행하고, 실제 팔 진입·청크 실행은 `TwoArmChunkGuard`의 단일 `mid` 락 + swept-capsule 마진 검증으로 **1팔 교대 실행**(D-983 정차 대기/철수 규칙 준수) |
| `T4_DRY_RUN_REMOTE_VERIFY` | **무동작 원격 파이프라인 점검** (`--dry-run`) | T1~T3 중 유효한 작업 쌍 | 원격 `/health`·`POST /infer`·형상/역기구학/가드 판정·`receipt.json` 생성까지 전 구간 실행하되, `load`/`run policy` 모션 명령 0회 전송(관찰·가드 검증 전용) |

#### 3. 명시적 비목표 (Non-Goals)

- **12축 단일 물체 양손 협동 파지(tight dual-arm grasp)** 및 공중 직접 전달(**mid-air handover**): 중간 거치 사이트(`temp_a`/`temp_b`/`yard`) 없이 두 팔이 한 강체/연성 물체를 동시에 잡는 작업은 본 ADR 범위에서 제외한다.
- **무감독 L3 자율 실행**: 본 파이프라인은 `--dry-run` 또는 D-911 `--commissioning --person-at-switch` 및 D-1024 `--proposer != --operator` 감독 실기 검증 전용이며, 현장 무인 자율(`L3`) 권한을 부여하지 않는다.

#### 4. 하드웨어 전제조건 및 정량 KPI

- **실기 투입 전제 (Open Preconditions):** 실기 시험 전에 ① 양팔 캘리브레이션·정밀 사이트 맵 및 `rigid_of` 3D 정합 확보, ② `arm_a`/`arm_b` 모든 필수 D-1065 카메라 역할(`top`/`side`/`wrist`) `fresh=True` 및 체크포인트 `sha256` 고정, ③ `arm_b` 리더 재연결·`record-config-bi-ab.json` 정렬·핀치/엔드이펙터(`fingertip_m`) 일치 검증, ④ 두 팔 `operating_profile_path` 및 D-911 `Authorization` 검토가 완료되어야 한다.
- **정량 KPI:**
  - 원격 추론(`POST /infer`, LAN warm): 목표 RTT `< 50 ms` (hard timeout `<= 2.0 s`, 전체 관측~적재 경과 `<= MAX_OBSERVATION_AGE_S = 0.6 s`).
  - 충돌 가드 안전성: 테이블 하한(`min_z_m`) 위반 적재 **0건**, 정지 상대/미지 상대 간섭 청크 적재 **0건**, `mid` 이중 점유 **0건**, 원격 오류·타임아웃·가드 거부 시 양팔 `human-hold` 및 `coupled_stop` 래치 전환율 **100%**.

#### 5. 실기 사전점검 현황 및 잔여 TODO (2026-11-23 기준)

- **완료된 무동작 사전검증:** `<ai-pc-host>` CUDA GPU 원격 추론 서버 가동 및 D-1065 정규 역할(`top`/`side`/`wrist`) `sha256` 고정 75k ACT 번들 적재, Bearer 인증 401 fail-closed 확인, 양팔 관절 캘리브레이션 `joint_offsets = [0.0]*6` 및 `cell-arm-{a,b}/operating-envelope.json`(`reviews: []`, `payload = 0.016 kg`, 커미셔닝 허용 / 무심사 자율 거부) 정렬, 실측 `rigid_of(pallet, pallet)` 기반 `TwoArmChunkGuard` 무동작 검증(`admitted=True`, `clearance_m` `0.2148–0.22599 m`)을 완료하였다. 추가로 실물 4카메라(`top`/`side`/`arm_a_wrist`/`arm_b_wrist` 모두 `200`) + 옵서버 실자세(`arm_a`·`arm_b`) 연동 비모션 드라이런에서 `arm_a` `clearance_m = 0.2247 m` 적재 판정 및 `arm_b` `frame 0 shoulder_lift=-67.9 outside reviewed -65.2..-7.1` 안전 거부의 `coupled_stop` 연동 차단까지 확인했다.
- **현장 물리 조작·승인 게이트 (완료 및 잔여):** [완료] `arm_b_wrist` USB 카메라(`200`) 및 `arm_b` 리더 보드 물리 재연결 완료. [잔여 — 사람 전용] ① Fleet 콘솔에서 `arm_a` 인시던트(`stale effort sample`) 보류 해제(D-971), ② 전원 스위치 앞 감독(`--person-at-switch`, D-911) 확인 하 양팔 `remap` 캘리브레이션 및 `arm_b` 홈 자세·봉투 범위 점검 후 `cell_two_arm_policy` 시범 기동, ③ (권장) 두 호스트 유선 GbE 이더넷 연결.
- **잔여 엔지니어링·운영 TODO (2026-11-23 반영):**
  - [x] **1. 원격 추론 LAN RTT `< 50 ms` KPI 달성 최적화:** [PR #574](https://github.com/robotics-team-1213/rosy-platform/pull/574) (`aa5cb3327f`) HTTP/1.1 keep-alive + `TCP_NODELAY`에 더해 [PR #598](https://github.com/robotics-team-1213/rosy-platform/pull/598) (`d2e25aae3a`)에서 `act_policy_http_server.py`의 `uint8` 텐서 선전송을 적용해 OpenCV/PyTorch CPU OpenMP 경합을 제거했다(서버 `server_infer_ms` `9.18–12.98 ms`). 안정된 Wi-Fi 구간 실측은 `arm_a` median `26.8–32.78 ms` · `arm_b` `22.95 ms`(`< 50 ms`)를 달성했으나, 양 호스트 유선 포트가 비활성인 현재 Wi-Fi 대역 혼잡 시 client RTT가 `arm_a` `159.73 ms` (`p95 483.93 ms`) · `arm_b` `94.16 ms` (`p95 155.96 ms`)까지 상승하므로 실기 기동 시 유선 GbE 연결을 권장한다.
  - [ ] **2. 양팔 `remap`·공통 `belt` 사이트 맵 등록 및 `arm_b` `pallet` 정밀 재보정:** `:8781` 잡 경로의 `--model-site-a`/`--model-site-b` 연동과 `cell_calibrate.py auto --plan-only`(`refused: null`)는 완료되었으나, `cell_calibrate.py check`가 `camera_moved: true`(`arm_a` `36.0 px`, `arm_b` `8.0 px`, `todo: ["remap", "regions"]`)를 검출했다. 감독 `--commissioning --person-at-switch` `remap` 및 공통 `belt`·`arm_b` `pallet`(`loo_error_mm.max = 12.65 mm`) 실물 측정이 필요하다.
  - [x] **3. 안전 태그 등재·`cell-job-api` 공식 통합 및 셀 도구 승격:** `tools/harness/platform_parts.yaml` `safety_review_paths`에 D-1073 4개 모듈 등재([PR #594](https://github.com/robotics-team-1213/rosy-platform/pull/594)), `cell_job_api.py` `:8781` 공식 `cell_two_arm_policy` 잡([PR #596](https://github.com/robotics-team-1213/rosy-platform/pull/596)) 및 셀 도구 승격을 완료했다.
  - [x] **4. `<ai-pc-host>` 원격 GPU 추론 서버 운영화 및 학습 락 조율:** `learning/training/omx/rosy-omx-act-http.service` 및 `act_gpu_lock.py`(`--gpu-lock-file`/`--jobs-dir`/`--reject-when-training-busy`)로 비점유 `gpu.lock`/`train-*.lock` 감지·학습 중 `/health` 표시 및 `POST /infer` 503 fail-closed를 운영 적용했다.
  - [ ] **5. D-911 운영 봉투(`operating-envelope.json`) 인간 심사 등재:** 현재 양팔 `operating-envelope.json`은 `reviews: []`(감독 커미셔닝 전용) 상태이므로, 현장 감독 시험(`attempts.jsonl`) 결과를 누적한 뒤 `deploy/robot/omx/cell_envelope_review.py add --confirm-physical-review`로 정식 인간 심사 기록을 등재한다.
  - [x] **6. (선택 · 양팔 텔레오퍼/추가 녹화용) `arm_b` 리더 및 녹화 설정 정합:** `record-config-arm-{a,b}.json`의 `side` 카메라 경로를 실물 `record-config-bi-ab.json`과 동일 장치 경로(`/dev/v4l/by-path/...`)로 정렬했고, `arm_b_wrist` 및 `arm_b` 리더 보드 물리 재연결 후 세 설정 파일의 모든 카메라·시리얼 장치 경로 실존 여부를 검증했다.

### Consequences & Invariants

- 기존 6축 데이터·학습 체계와 `chunk_runner`·`cell_policy_shape`·`cell_two_arm` 안전 유틸리티를 그대로 재사용하므로 12축 데이터를 새로 수집하지 않고도 T1~T4 병렬/교대 파이프라인을 구성할 수 있다.
- 모든 물리 모션 명령 전에 원격 리비전 일치·유한 (n, 6) 형상·`cell_policy_shape` 클램프·`TwoArmChunkGuard.admit_chunk`가 통과해야 하며, 어느 한 팔의 실패·타임아웃·가드 거부는 즉시 반대팔까지 `coupled_stop` + `human-hold`로 정지시킨다.
- 본 ADR의 PR 머지는 코드·문서·시뮬레이션/루프백 단위·계약 테스트 기준이며, 실기 배포(`rosy-arm-cell`/`<ai-pc-host>`), 학습 중 GPU 프로세스 변경, 실물 두 팔 시험 합격과는 엄격히 분리한다.
