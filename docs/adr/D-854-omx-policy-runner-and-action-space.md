## D-854 OMX 학습 정책 실행기 하나로 — 정책 종류를 갈아 끼우는 AI PC 정책 실행기

**Status:** Proposed (2026-10-23). 사용자가 실행기 통합·AI PC 추론·실측 기반 chunk 값·데이터셋 변환 구조화를 결정했다. 이 ADR은 CORE wire 계약·실물 실행 관문(D-793, G4)·AI PC 현장 경로를 바꾸거나 열지 않는다. 각 단계는 별도 브랜치로 착지한다.

**관련:** D-800 · D-794 · D-793 · D-773 · D-516(넓힘) · D-527 · rosy-vault V-018(대체 예정)

### Context

2026-10-23 코드 확인 결과, SmolVLA 같은 VLA는 미들웨어에 연결되어 있지 않다. 연결된 정책은 ACT 하나뿐이고, 정책 실행기가 두 곳에 따로 있다.

| | ① 플랫폼 경로 (D-800) | ② device-core 경로 (V-018) |
|---|---|---|
| 흐름 | `lerobot_robot_rosy_omx` → CORE HTTP → `CoreArmPolicyPort` → `OwnerPolicySession` → ROS Action | `device_core/backends/lerobot_policy.py`가 프로세스 안에서 추론 → `SafeDriver` |
| 정책 종류 | ACT만 (`n_action_steps=1`, ensemble 금지) | 종류 제한 없음 (`get_policy_class(cfg.type)`) |
| 카메라 | 1대 | 여러 대 |
| 행동 단위 | rad | LeRobot 정규화 값 (−100..100, 그리퍼 0..100) |
| 상태 | SIM만. D-793·G4 닫힘 | 실물 미확인 (KAN-30 전) |

학습 쪽도 ACT만 있다(`learning/training/omx/act_job.py`, `act_inference.py`). 내보내기(`curation/omx/lerobot_export.py`)는 정규화 값으로 쓰는데 ①은 rad만 받고, 변환하는 곳이 없다.

### Decision

#### 1. 실행기 하나: 정책 실행기(Policy Runner)

정책을 실제로 돌리는 곳은 **AI PC의 정책 실행기 하나**다. 실행기는 고정된 뼈대에 세 가지 꽂는 자리(포트)가 있다.

```text
AI PC: Policy Runner
  ├─ PolicyAdapter   (정책 종류)   act · smolvla · (나중에 pi0, diffusion …)
  ├─ ActionSpace     (단위 변환)   lerobot_norm ↔ rad   — 데이터셋 변환과 같은 모듈
  └─ ArmTarget       (팔 쪽 계약)  CORE arm-policy HTTP  — 관측 받기 / 목표 묶음 보내기 / stop
        │
        ▼  HTTP (관측 ID, 목표 묶음)
CORE → OwnerPolicySession → owner (유일한 joint writer, 승인·한계·stop fence)
```

- **뼈대(고정)**: 관측 받기 → 전처리 → 추론 → 후처리 → 단위 변환 → 목표 묶음 보내기 → 준비 대기. 타이밍 기록, 관측 ID 결속, 불확실한 응답이 오면 stop을 보내는 동작도 뼈대에 둔다. 정책 종류가 이 부분을 바꾸지 못한다.
- **PolicyAdapter**: 정책 종류 하나에 하나씩 만든다. 각 adapter는 다음을 신고한다.
  - `policy_type`
  - 입력 카메라 이름·크기 목록
  - state·action feature 이름과 단위
  - `chunk_size`, `n_action_steps`
  - 언어 지시가 필요한지
  - `load(checkpoint, device)`
  - `infer(obs, task) -> 목표 묶음`
  
  LeRobot 계열은 `predict_action`과 체크포인트에 저장된 전·후처리를 쓰는 공통 adapter 하나로 ACT와 SmolVLA를 함께 다룬다. LeRobot 밖의 정책(예: openpi)은 adapter를 하나 더 만든다.
- **허용 목록**: 실행기는 registry에서 허용된 `policy_type`만 불러온다. 목록에 넣는 일은 이 ADR 개정과 adapter 계약 시험 통과가 있어야 한다.
- **ArmTarget**: 지금은 CORE arm-policy HTTP 하나다. 다른 팔이나 로봇은 같은 계약을 구현하는 target을 추가해서 붙인다. 실행기 뼈대는 바꾸지 않는다.

**② device-core 경로는 정리한다.** `backends/lerobot_policy.py`의 프로세스 안 추론은 끝낸다. 그 안의 `Units` 식은 ActionSpace의 정본 시험 기준으로 옮긴다. device-core가 실물 팔을 계속 맡는다면, 같은 arm-policy 계약(관측·목표 묶음·stop)을 구현하는 ArmTarget이 된다. 이렇게 하면 추론과 실행 루프는 한 곳에 있고, 팔 쪽 owner만 갈아 끼우게 된다. V-018은 이 ADR로 대체(Superseded)된다고 표시한다.

#### 2. AI PC 추론과 권한

- AI PC는 **목표를 제안만 한다.** 승인, 한계 검사, stop fence, HOLD는 지금처럼 CORE와 owner가 한다. AI PC에는 ROS, 장치 Action, lease 발급 권한이 없다.
- 그래서 D-516의 AI PC 역할에 "승인된 고정 버전 OMX 정책의 관절 목표 제안"을 추가해야 한다. 이 ADR이 D-516을 그만큼 넓힌다(D-516 본문은 고치지 않는다).
- 체크포인트는 registry가 승격한 고정 버전만 불러온다. 실행기는 체크포인트 sha256을 실행 기록에 남긴다. CORE가 받는 policy pin과 맞지 않으면 시작하지 않는다.
- AI PC와 CORE 사이 망 지연은 행동 나이(관측 시각부터 계산)에 그대로 포함된다. 추론과 전송이 느리면 owner의 신선도 검사가 거부한다. 신선도 검사를 느슨하게 하지 않는다.

#### 3. CORE 계약: 카메라 N대와 목표 묶음

- **카메라**: 설치 정책 문서 `cameras`는 순서가 있는 1..N대 목록이다(지금은 D-794의 top·front). 관측은 카메라마다 `{name, shape, rgb_base64, received_at_ns, frame_sha256}`를 준다. 신선도와 결속은 카메라마다 검사하고, 하나라도 실패하면 관측 전체를 거부한다.
- **목표 묶음**: 관측 ID 하나에 목표를 최대 `timing.max_chunk`개까지 보낼 수 있다. owner는 목표마다 승인을 다시 확인한다. 하나라도 거부되면 남은 목표는 버리고 HOLD한다. 묶음 전체는 관측 시각 + `timing.max_chunk_horizon_ns` 안에서만 실행한다.
- **기본값**: `max_chunk = 1`, horizon 기본값은 지금 `max_observation_age_ns`와 같다. 기본값에서는 지금 ACT 동작이 바뀌지 않는다.
- **task 문장**: CORE 계약에 넣지 않는다. 실행 기록에는 sha256만 남긴다.

#### 4. chunk 값은 실측으로 정한다

`max_chunk`와 `max_chunk_horizon_ns`는 이 ADR에서 숫자로 정하지 않는다. 아래 측정을 거쳐 정책 종류별로 설치 정책 문서에 적는다. 측정 없이 1이 아닌 값을 쓸 수 없다. preflight가 측정 기록의 sha256을 확인한다.

- **측정 위치**: AI PC. 실제 GPU, 실제 체크포인트, 설치할 카메라 크기와 대수를 쓴다. SIM CORE는 같은 망 경로에 둔다.
- **잴 구간**:
  1. 관측 요청 → 수신
  2. 전처리
  3. 추론
  4. 후처리·변환
  5. 묶음 전송 → 승인 응답
  
  1~5 합계를 종단 지연 L로 기록한다.
- **분량**: 예열 뒤 1,000회 이상. p50·p95·p99·최댓값을 기록하고, 첫 추론 시간은 따로 기록한다. GPU 모델, 드라이버, torch·lerobot 버전, dtype, 배치 크기, 카메라 크기도 같이 적는다.
- **정하는 식**: fps는 녹화 fps다.
  - `max_chunk_horizon_ns ≥ L_p99 + (n_action_steps / fps)`
  - `max_chunk ≤ n_action_steps`
  - 이렇게 정한 horizon이 `max_observation_age_ns`보다 길면 그 정책은 실행할 수 없는 것으로 판정한다. 신선도 한계를 늘리지 않는다.
- **기록 위치**: `docs/validation/policy-latency-<policy_type>-<날짜>/`. 측정 도구는 실행기 뼈대의 타이밍 기록을 그대로 쓰고, 별도 계측 코드를 만들지 않는다.

#### 5. 데이터셋 변환 구조

단위 변환은 실행 경로와 학습 경로가 **같은 모듈(ActionSpace)**을 쓴다.

- **단위 선언**: 모든 데이터셋은 메타데이터에 `action_space`를 적는다. 값은 `{unit: lerobot_norm_v1 | rad, calibration_sha256, motor_order}`다. 선언이 없는 데이터셋은 학습과 내보내기 모두 거부한다.
- **정본 단위**: `lerobot_norm_v1`(omx_follower, `use_degrees: false`, lerobot 0.4.4 `motors_bus` 식)이다. 학습은 정본 단위 데이터셋만 받는다.
- **변환기**: `(from_unit, to_unit, version)`마다 순수 함수 하나를 둔다. 보정 파일이 필요한 변환은 보정 파일 sha256을 입력으로 받는다. 기존 rad 데이터셋은 `rad → lerobot_norm_v1` 변환기로 **새 데이터셋을 만든다.** 원본은 고치지 않는다.
- **출처 기록**: 변환된 데이터셋에는 원본 데이터셋 id·sha, 변환기 버전, 보정 sha, 변환 시각, 경계 밖이라 잘린 값의 개수를 남긴다. 잘린 값이 0이 아니면 검수 대상으로 표시하고 자동으로 승격하지 않는다.
- **정확도 시험**: 왕복 변환 오차 한계와 vault `Units` 골든 값 일치를 확인한다. 실행기의 ActionSpace도 같은 시험을 통과해야 한다.
- **위치**: 단위 이름은 `lerobot_norm_v1`·`dynamixel_rad_v1`이다. 변환기와 선언 검사는 `contracts/learning/src/rosy/contracts/learning/action_space.py`(curation과 실행기가 함께 쓰는 교차 part 계약, D-449 wheel)에, 일괄 변환 CLI는 `learning/curation/omx/`에 둔다. `dynamixel_rad_v1`(Present Position 2048 중심)이 설치된 ROS 관절 rad와 같은지는 따로 확인해야 한다.

### Consequences

- 정책 종류를 추가하는 일은 adapter 하나와 계약 시험, 허용 목록 개정으로 끝난다. CORE와 owner는 바뀌지 않는다.
- 추론은 한 곳(AI PC)에, 실행 권한은 한 곳(CORE와 owner)에 있다. 두 실행기가 따로 갈라지는 문제가 없어진다.
- 기본값(K = 1, 카메라 1대)에서는 지금 ACT 동작이 바뀌지 않는다.
- CORE 정책 계약이 바뀌므로 API reference 버전을 올린다(`api_reserve.py`).
- 실물 실행 관문(D-793, G4)은 이 ADR로 열리지 않는다. AI PC 현장 경로를 켜는 일도 별도 승인이 필요하다.
- rosy-vault 쪽 변경(V-018 대체, device-core ArmTarget)은 vault의 V-nnn과 팀 ADR(Confluence)을 먼저 고쳐야 한다.

### 남은 질문

1. device-core를 ArmTarget으로 남길지, 아니면 실물 팔도 플랫폼 OMX owner(①)로 옮기고 device-core 정책 기능을 완전히 뺄지. 이 ADR은 "남긴다"를 기본으로 하되 vault 팀 결정에 맡긴다.
2. SmolVLA 실측에 쓸 체크포인트. 학습된 체크포인트가 없으면 공개 `smolvla_base`로 지연만 잰다. 성능 근거로는 쓰지 않는다.

### 구현 순서 (착지 단위)

1. `contracts/learning`: `action_space` 선언과 변환기, 골든·왕복 시험.
2. `curation/omx`: 일괄 변환 CLI와 출처 기록, 기존 rad 데이터셋 변환.
3. CORE 계약: 카메라 N대와 목표 묶음(기본값은 지금과 같게), API 버전 올리기.
4. 정책 실행기 뼈대 + LeRobot 공통 adapter(ACT부터). 기존 `lerobot_robot_rosy_omx` 시험이 그대로 통과하는지 확인.
5. AI PC 지연 측정: ACT, 그다음 SmolVLA. 측정 결과로 정책별 `max_chunk`·horizon을 정한다.
6. SmolVLA를 허용 목록에 넣고, Gazebo `policy_chain_gazebo.py`로 chunk 실행부터 stop까지 확인. 과제 성공 증거가 아니다.
7. vault: V-018 대체, device-core ArmTarget(또는 정리).
