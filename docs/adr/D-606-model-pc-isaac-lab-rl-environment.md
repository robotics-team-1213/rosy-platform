## D-606 모델 PC의 Isaac Lab 강화학습 환경은 기존 5.1 계열을 격리해 준비하고 물리·자원 게이트 뒤에 학습한다

**Status:** Accepted (2026-10-10, 사용자 요청; 환경 점검 완료, RL 실행·ROS-SIM 수용 HOLD)

### Context

ROSY는 D-322의 Isaac Sim runner와 D-427의 Gymnasium 학습 계약을 갖지만, 일반 Pinky 주행 RL 환경과 보상·관측·행동 공간은 아직 없다. D-434는 모델 PC에 Isaac Sim 5.1과 Isaac Lab 2.3.2를 유지하고 학습과 시뮬레이션의 GPU 동시 사용을 금한다. 2026-10-04 I1 실측에서는 CORE 명령 만료와 유한 프레임 종료를 확인했으나 전진 추종과 명령 종료 뒤 물리 정착이 실패했다. 2026-10-09 차선 재생 기록에 따르면 Isaac runner에는 차선 카메라·LiDAR·지도 폐루프가 없다. 현재 물리 모델과 관측으로 주행 정책을 학습하면 보상 결과를 신뢰할 수 없다.

2026-10-10 모델 PC 읽기 점검: Ubuntu 24.04, Isaac Sim 5.1.0.0, Isaac Lab 소스 태그 v2.3.2, Python 3.11, PyTorch 2.7.0+cu128의 CUDA 사용 가능, ROS 2 Jazzy(source 후 CLI 정상), RTX 5080 Laptop GPU 16 GB, RAM 15 GiB, 홈 디스크 여유 약 265 GB. 기존 Isaac venv의 `pip check`는 의존성 충돌을 보고했다. NVIDIA의 Isaac Sim 5.1 최소 RAM은 32 GB이고 Isaac Lab 학습에는 추가 RAM·VRAM이 필요하다. 설치 파일의 존재와 CUDA 확인은 학습 준비 완료가 아니다.

### Decision

1. 모델 PC의 `~/isaac-sim-workspace`에서 Isaac Sim **5.1.0.0**과 Isaac Lab **v2.3.2**를 기준으로 한다. ROSY runner는 5.1 importer 경로를 쓴다. 기존 `~/rosy-ml/.venv`(인지 모델 학습)와 Isaac Python 3.11 환경을 섞거나 제자리에서 무작정 업그레이드하지 않는다. 버전 변경은 별도 후보 환경에서 검증한다.
2. 환경 수용은 순서대로 판정한다. (a) 물리 RAM 32 GB 이상, GPU/드라이버/디스크 여유와 동시 작업 확인, (b) 격리된 후보 Isaac 환경에서 `pip check` 0과 Isaac Lab 기본 환경의 headless reset/step 성공, (c) ROS 2 Jazzy bridge의 `/clock`·TF·odom·joint 상태와 단일 CORE 최종 `cmd_vel` 확인, (d) Pinky 접지·전진 추종·회전 후 정착·명령 만료 후 실제 정지 확인. 각 단계가 실패하면 RL 학습은 HOLD한다. swap은 최소 RAM을 충족한 것으로 세지 않는다.
3. 첫 RL 과제는 한 행동 계약으로 제한한다. 기존 로직의 고정 평가 시나리오·시드·시작 자세·속도와 실패 판정을 먼저 기록한다. D-427에 따라 관측·행동 공간은 PolicyArtifact와 같게 하고, 엔벌로프 위반은 `terminated=True`와 실패 보상으로 기록한다. 시간 제한만 `truncated=True`다. 안전 판단은 기존 CORE·Safety Guard가 맡으며 Isaac 환경에 별도 최종 명령 권한을 만들지 않는다.
4. 학습은 모델 PC에서만 격리 실행한다. Gazebo, Isaac 검증, 인지 모델 학습과 GPU 시간을 예약해 겹치지 않게 한다. 실물 로봇·운영 Fleet endpoint에 학습 runner를 연결하지 않는다. 먼저 baseline과 RL 후보를 같은 닫힌 고리 sim 과제에서 독립 시드로 비교하고, 정책 산출물은 D-427의 L0→L1→L2 승격 경계를 따른다. 실물 RL은 D-427의 별도 선행 조건 전부가 충족되기 전까지 금한다.
5. 이번 모델 PC 점검은 설치 현황만 확인했다. RAM 부족과 `pip check` 실패, Isaac 물리 주행 HOLD를 해소한 뒤 재검증한다. 어느 한 단계의 SOURCE·LOCAL 통과를 RL 학습 또는 DEVICE/FIELD 수용으로 올리지 않는다.

### Alternatives

- Isaac Sim 6.1로 즉시 교체: 기존 5.1 실행 경로를 버리고 자원 부족과 물리 모델 실패를 해결하지 못하므로 보류한다.
- Gazebo 결과만으로 RL 시작: 기존 로직의 폐루프 기준에는 활용하되 Isaac Lab의 관측·물리·정지 경계를 증명하지 못하므로 채택하지 않는다.
- 기존 Isaac venv에 충돌 패키지를 제자리 갱신: 다른 세션의 SDK 실행을 깨뜨릴 수 있어 채택하지 않는다.

### Verification and next action

- 점검 증거: `docs/validation/model-pc-isaac-rl-2026-10-10/result.md`.
- 첫 외부 조치: 모델 PC RAM을 최소 32 GB로 증설하고 실측한다. 이후 독립 후보 환경의 의존성을 맞추고 `pip check` 및 한 환경 headless reset/step을 재실행한다. 기존 venv는 후보가 통과할 때까지 유지한다.
- 그다음 D-322 I1 물리 정지 HOLD를 풀고, 선택한 행동의 관측·행동·보상·실패 정의를 별도 구현으로 진행한다. 학습 성능은 기존 로직과 같은 시나리오에서 검증한다.

**Related:** D-322, D-427, D-434, D-480.
