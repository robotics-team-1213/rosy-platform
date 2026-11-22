# OMX Cell S ACT 추론·전송 패리티 및 D-1073 LAN keep-alive 검증 (무동작·오프라인)

2026-11-23 KST. `rosy-arm-cell` 실물 영수증 포렌식(Slice 0)과 AI PC RTX 5080 CUDA 오프라인 추론·JPEG 패리티·Ollama 공존·LAN HTTP 전송 A/B 계측(Slice 2) 기록이다. 물리 팔 이동이 없는 영수증 분석 및 오프라인·루프백/LAN 프로브 결과이며, 실물 `rosy_42` S3 pick/place 수용 근거가 아니다(D-947).

- 기준선 및 근거 PR: [PR #554](https://github.com/robotics-team-1213/rosy-platform/pull/554) (`31353316f0f912ec8217655a15f96c94850146ae`, Slice 1 D-430 안전 하드닝) 및 [PR #556](https://github.com/robotics-team-1213/rosy-platform/pull/556) (`02b749b84456f64f211f38293ec4c8c64208d2de`, [D-1073](../../adr/D-1073-omx-two-arm-remote-policy-pipeline.md)).
- 관련 교훈: [omx-cell-cpu-inference-deadline-and-sim-real-branch-preflight-2026-11-22.md](../../solutions/runtime-errors/omx-cell-cpu-inference-deadline-and-sim-real-branch-preflight-2026-11-22.md).

## 1. Slice 0 — Cell S (`arm_s`) 실행 영수증 분해 (`GUARD_UNITS_PER_S = 5.0`)

| 실행 ID / 조건 | `load ok` (캡처+CPU 추론+형태변환+적재) | `run policy` (물리 재생) | `park` (복귀·정착) | 총 시간 및 결과 |
|---|---:|---:|---:|---|
| `1795339932` (`20261122-183207-172008`, `max_chunks=1`) | **0.715 s** (`1121` frames @ `30 fps`) | **37.456 s** (`joint_travel: 51.43`, `top_change: 25.12`) | **30.226 s** (`settled: true`, `peak_lag: 1.71`) | `68.398 s` (`chunks_done`, `parked: true`; **98.95%** 물리 재생·복귀, **1.05%** 로드·추론) |
| `1795348024` (`20261122-204700-e22b7b`, `max_chunks=1`) | **0.719 s** (`1162` frames @ `30 fps`) | **38.828 s** (`joint_travel: 51.68`, `top_change: 16.27`) | **30.975 s** (`settled: true`, `peak_lag: 1.66`) | `live_1chunk 76.58 s` (`chunks_done`, `held: false`, `parked: true`, `unsent_outbox: 0`) |
| `1795348512` (`max_obs_age_s=0.6`, `elbow_flex=55.02`) | **1.040 s** (`650` frames) | — | 정착 (`elbow_flex=50.43`) | `refused: stale policy observation` (`1.045 s > 0.6 s`) 후 안전 복귀 |
| `1795348733` (`max_obs_age_s=2.0`, `elbow_flex=54.87`) | **0.843 s** (`638` frames) | **21.357 s** (`joint_travel: 53.72`) | **47.423 s** | `chunks_done` 정상 완료 |

- 결론: Paced `arm_s` 루프에서는 `shape_chunk`가 모델 스텝을 가드 속도(`5.0 / 30 = 0.167 u/frame`)로 보간해 1청크당 `638–1162`프레임(`21–39 s`)이 생성되므로, 추론 지연(`0.715 s`)은 전체 벽시계의 `1.05%`에 불과하다.

## 2. Slice 2 — AI PC (RTX 5080 CUDA) 오프라인 추론·JPEG 패리티·Ollama 공존

- 대상 체크포인트(`policy_revision`): `bc0939e9b757433cfd0868f7bd43994d763852dacc5ebc7bab854a5d4c7906e4` (`fastest_u_per_frame: 0.075`).

### 2.1 Cold / Warm 지연 및 VRAM 점유
- **Cold 기동**: `load_s = 3.3003 s`, `first_infer_s = 0.5365 s`, 합계 `3.8368 s`, `torch_peak_mib = 269.9 MiB`, VRAM `18 MiB -> 589 MiB` (`/ 16303 MiB`).
- **Warm (`n = 1,000`)**:
  - `infer_only`: `min 10.390 ms`, **p50 `12.011 ms`**, p95 `12.708 ms`, **p99 `14.043 ms`**, `max 105.089 ms` (mean `12.141 ms`).
  - `inputs_plus_infer`: `min 12.807 ms`, **p50 `14.359 ms`**, p95 `15.197 ms`, **p99 `16.633 ms`**, `max 107.465 ms` (mean `14.500 ms`).
- **Ollama (`qwen3-vl:8b-instruct`, Q4_K_M, `6,536,183,152` B VRAM) 공존**: `ollama_warmup_s = 5.026 s`, 합산 VRAM **`8,465 / 16,303 MiB`** (`7,376 MiB` 여유), `warm_200_inputs_plus_infer` `min 12.729 ms` / **p50 `14.633 ms`** / p95 `16.148 ms` / **p99 `17.903 ms`** / `max 18.374 ms`; 언로드 후 VRAM `589 MiB` 복귀.

### 2.2 무손실 vs JPEG q85 / q95 안전 판정 패리티 (`timed_rate_limit = 100`)

| 시작 자세 | 입력 인코딩 | `accepted` | `frames_cell_len` | `timed_rate_ok` | 무손실 대비 `max_abs_diff` | `mean_abs_diff` | `p99_abs_diff` | `same_verdict` |
|---|---|---|---:|---|---:|---:|---:|---|
| `on_home` | `lossless` | `true` | `1146` | `false` (`>> 100`) | — | — | — | 기준 |
| `on_home` | `jpeg_q85` | `true` | `1140` | `false` (`>> 100`) | `0.330873` | `0.070314` | `0.292079` | `true` |
| `on_home` | `jpeg_q95` | `true` | `1151` | `false` (`>> 100`) | `0.182007` | `0.046940` | `0.169305` | `true` |
| `sagged` | `lossless` | `true` | `1166` | `false` (`>> 100`) | — | — | — | 기준 |
| `sagged` | `jpeg_q85` | `true` | `1168` | `false` (`>> 100`) | `0.328657` | `0.070673` | `0.292065` | `true` |
| `sagged` | `jpeg_q95` | `true` | `1174` | `false` (`>> 100`) | `0.180305` | `0.046756` | `0.166576` | `true` |

## 3. Slice 2 — `rosy-arm-cell` ↔ AI PC LAN HTTP 전송 A/B (`deadline_s = 0.3 s`, 비편향 모수)

모든 실패(mDNS/URL 오류·타임아웃·주입 HTTP 503)를 지연 분포 모수(`n = 1,000` 또는 `1,010`)에 그대로 포함하여 D-854 §4 기준으로 비교했다.

| 전송 방식 | 정상 `1,000`회 성공률 (`errors`) | `e2e p50` | `e2e p95` | `e2e p99` | `e2e max` | 서버 `p50` | 1% 장애 주입 `1,010`회 (`errors`) |
|---|---|---:|---:|---:|---:|---:|---|
| `urllib.request` (요청당 신규 TCP + `.local` mDNS 재조회) | **984/1,000** (`URLError: 10`, `TimeoutError: 6`) | `82.457 ms` | `333.662 ms` | **5,131.632 ms** | `10,312.361 ms` | `17.248 ms` | **984/1,010** (`URLError: 10`, `TimeoutError: 11`, `http_503: 5`) |
| `http.client.HTTPConnection` (keep-alive + 1회 IP 해석 `5.727 ms` + `TCP_NODELAY`) | **1,000/1,000** (`errors: {}`, `reconnects: 0`) | **29.693 ms** | **38.009 ms** | **43.182 ms** | `304.206 ms` | `14.033 ms` | **1,000/1,010** (`TimeoutError: 5`, `http_503: 5`, `reconnects: 5`, `p99: 56.947 ms`) |

## 4. D-854 §4 판정 및 적용 조치

1. **Cell S paced `arm_s` 원격 GPU 추론 전환: NO-GO.** GPU 추론을 `12 ms`대로 줄여도 물리 재생이 `98.95%`이고 `frames_cell_len`이 `1140–1174`로 `run_timed` 상한(`100`)을 크게 초과하므로 별도 `rosy-act-infer.service`를 Cell S에 상시 배선할 실익이 없다.
2. **D-1073([PR #556](https://github.com/robotics-team-1213/rosy-platform/pull/556)) 원격 추론 파이프라인 전송 보강:** 요청마다 mDNS를 다시 질의하고 TCP를 새로 맺는 `HTTP/1.0` + `urllib.request` 조합은 `1.6%` 실패와 `5.13 s` `p99` 꼬리지연을 유발해 `D-854`의 `MAX_OBSERVATION_AGE_S = 0.6 s` 예산을 깬다. 이를 해결하기 위해 `learning/training/omx/act_policy_http_server.py`를 `HTTP/1.1` + `TCP_NODELAY` + `request_id` 에코로 전환하고, `deploy/robot/omx/cell_remote_policy.py`가 keep-alive 영속 연결 + 세션 내 IP 캐시(오류 시 재해석으로 `<name>.local` mDNS 규칙 유지) + `request_id` 일치를 검증하도록 수정했다.
