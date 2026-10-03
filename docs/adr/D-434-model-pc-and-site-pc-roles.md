## D-434 모델 PC와 관제 PC를 나눈다 — 모델 PC가 학습 모델 처리와 시뮬레이션(Isaac Sim 5.1)을, 관제 PC는 사이트 스택만 맡는다

**Status:** Accepted (2026-10-03, 사용자 결정). 역할 분담과 운용 규칙의 결정이다. 모델 PC의 GPU 학습·NCNN 변환·Isaac 실행, 관제 PC의 사이트 스택 이전은 아직 수용되지 않았다.

### Context

- 학습은 지금까지 Colab에서만 돌았다(D-356). 데이터 수집·라벨·데이터셋 빌드·intake는 이 Windows 개발 PC에서 손으로 실행했다. 2026-10-03 점검에서 학습 고리는 닫혀 있지 않았다(inbox → intake → shadow 만 자동).
- D-373과 운영 안내(`docs/deployment/learned-perception-operators.md`)는 모델 watch를 "사이트 PC"에 둔다. 사이트 스택(Caddy·Fleet·Vision, `deploy/site/`)은 Windows Docker Desktop에서 돌았는데, 컨테이너가 로봇 LAN에 닿지 않아 호스트 relay로 우회했다.
- D-431은 YOLO 물체 검출을 PC에서 NCNN으로 변환한다. NCNN 바인딩이 설치된 PC가 필요하다.
- D-322는 Isaac Sim 6.1을 전제로 했고, GPU 호스트가 없어 실제 실행은 HOLD였다.
- 사용 가능한 Linux 장비가 둘 생겼다.
  - **모델 PC**: Ubuntu 24.04, RTX 5080 Laptop GPU(VRAM 16 GB, Blackwell sm_120), 24 스레드, RAM 15 GB(32 GB로 증설 예정), ZFS 루트. Isaac Sim 5.1(pip, 자체 uv venv Python 3.11)과 Isaac Lab 2.3.2가 이미 설치돼 있다.
  - **관제 PC**: Ubuntu 26.04, Intel GPU, 8 스레드, RAM 14 GB. 로봇 LAN에 직접 닿는다.
- 저장소는 공개다. 장비 주소·계정은 `private/`에만 둔다.

### Decision

1. **모델 PC는 학습 모델에 관한 일을 모두 맡는다.**
   - 로봇에서 세션 수집(`dataset/harvest.py`), 자동 라벨(D-379), 데이터셋·고정 평가 세트 빌드, 학습, ONNX 변환, NCNN 변환(D-431), intake와 평가 게이트(D-379 부록 2026-10-03), store, 모델 watch와 로봇 섀도 반영(D-373)이다.
   - D-373과 운영 안내에서 모델 watch·store의 자리로 쓴 "사이트 PC"는 모델 PC로 읽는다. 설치 절차(`install-model-watch.sh`)는 그대로 쓰고 설치 위치만 바뀐다.
   - 학습은 기존 노트북의 GPU PC 경로를 쓴다(`ROSY_REPO_DIR`, W&B 키는 환경 변수). Colab 경로는 대안으로 남긴다.
   - 모델 PC는 로봇마다 자기 SSH 공개 키(주석으로 모델 PC를 식별)를 두고, 그 키만 회수하면 접근이 끊긴다. D-418의 등록 절차가 구현되면 그 절차로 옮긴다.
2. **관제 PC는 사이트 스택만 돌린다.** Docker Compose 사이트 스택, mDNS 광고, 방화벽, 사이트 설정·비밀은 `deploy/site/README.md` 그대로다. 학습 패키지·store·모델 watch는 두지 않는다. Windows Docker Desktop의 사이트 스택은 관제 PC가 수용되면 내린다. 관제 PC에는 ROS가 필요 없다.
3. **Isaac Sim은 5.1을 유지한다(D-322 버전 개정).**
   - 다시 설치하지 않는다. D-322의 도구 중 6.1에만 있는 API(`isaacsim.asset.importer.urdf.URDFImporter`/`URDFImporterConfig`, `run_rosy.py`·`import_omx.py`)는 5.1 경로(`URDFParseAndImportFile`, `_urdf.ImportConfig`)를 함께 두도록 고친다(미구현). ROS 2 그래프 구성(DifferentialController, odom·TF·clock)은 그대로다.
   - ROS 2 연결을 위해 모델 PC에 ROS 2 Jazzy(apt)를 둔다.
   - D-322의 수용 항목(`/clock`·TF·odom 일관성, 직진·회전·zero-command 정지, 단일 CORE 발행자)은 바뀌지 않는다. Isaac Lab 학습 HOLD(D-427)는 유지한다.
   - 6.1로 올릴지는 RAM 증설 뒤 다시 정한다.
4. **RAM 32 GB 전까지의 메모리·GPU 운용 규칙.**
   - Isaac은 항상 headless로 돌리고, 렌더 해상도는 작게(예: 640×480, anti-aliasing 끔), 카메라·LiDAR는 필요할 때만 붙인다. 첫 범위는 센서 없는 Pinky 한 대다.
   - NVIDIA 최소 사양은 RAM 32 GB·VRAM 16 GB다. 모자란 RAM은 swap으로 버틴다. swap 우선순위는 zram(zstd, RAM의 50 %, 우선순위 100)이 ZFS zvol swap보다 높게 둔다. ZFS 위의 zvol swap은 메모리가 바닥날 때 ZFS 자신이 메모리를 요구해 멈출 수 있다(OpenZFS의 알려진 한계). ZFS ARC는 4 GB로 제한한다.
   - **Isaac Sim과 학습은 GPU를 동시에 쓰지 않는다.** VRAM 16 GB가 Isaac 최소 사양과 같다.
   - 위 설정을 적용했는지와 실제 효과는 첫 Isaac 실행에서 기록한다. 지금은 규칙이지 측정값이 아니다.
5. **환경 배치.**
   - 모델 PC의 학습 환경은 `~/rosy-ml/.venv`(uv, Python 3.12, PyTorch cu128)이며 Isaac venv와 섞지 않는다.
   - ultralytics·ncnn·pnnx는 cu128 PyTorch 설치 뒤에 넣는다. 그렇지 않으면 PyPI의 CPU PyTorch가 들어온다. 설치한 버전은 manifest의 exporter/runtime 버전 필드(D-431 §4)에 맞춰 기록한다.
   - 소스는 GitHub에 올라가지 않은 로컬 main이 있을 수 있어 당분간 git bundle로 옮기고, 원격은 GitHub로 둔다.
6. **주소·계정은 공개 문서에 적지 않는다.** 이 ADR과 운영 문서는 역할 이름(모델 PC, 관제 PC)만 쓴다. 실제 주소·사용자·키 지문은 `private/`에 둔다.

### Alternatives

| 대안 | 판단 |
|---|---|
| 한 Linux PC에 사이트 스택과 학습을 함께 | 관제 PC는 GPU가 없고, 모델 PC의 학습·Isaac 부하가 사이트 응답성을 흔든다. 기각 |
| 학습은 계속 Colab만 | GPU 시간 제한, 데이터 업로드, NCNN 바인딩·Isaac 불가. 대안 경로로만 유지 |
| Isaac Sim 6.1 새로 설치 | 수십 GB를 Wi-Fi로 받아야 하고, RAM 15 GB에서 이득이 없다. RAM 증설 뒤 재검토 |
| 모델 watch를 문서대로 관제 PC에 | 관제 PC에 ML 패키지·store가 생겨 역할이 섞인다. 기각 |

### Consequences

- 학습 고리의 손 단계(harvest → catalog → autolabel → build → 학습)를 한 PC에서 이어 붙일 수 있다. 자동 연결은 별도 작업이다.
- 관제 PC로 옮기면 Docker Desktop의 LAN 문제(호스트 relay 우회)가 사라진다.
- D-322의 GPU 호스트 HOLD가 풀릴 길이 생긴다. 다만 RAM 부족으로 다중 로봇·센서 장면은 32 GB 전까지 수용하지 않는다.
- 모델 PC 한 대에 학습·변환·시뮬레이션이 몰리므로 GPU 시간을 나눠 써야 한다.

### Validation

- 모델 PC: cu128 PyTorch로 GPU 연산 확인, 노트북 한 에폭 학습 → export → intake(평가 게이트 포함) 한 바퀴, ultralytics·ncnn·pnnx 설치와 작은 NCNN 변환 확인, Jazzy 설치 뒤 Isaac 5.1 headless에서 Pinky 한 대의 D-322 수용 항목.
- 관제 PC: `deploy/site/README.md`의 Ubuntu 호스트 준비와 preflight, 로봇 mDNS 발견, Fleet 콘솔 접속.
- 증거에는 주소를 넣지 않는다.

**Related:** [D-322](D-322-isaac-sim-rosy-integration.md), [D-356](D-356-perception-learning-loop-and-model-delivery.md),
[D-373](D-373-learned-perception-on-pinky-and-capture-loop.md), [D-379](D-379-learning-data-pipeline-auto-labels-local-store.md),
[D-418](D-418-robot-ssh-access-code-enrollment-temporary-password-team-key.md), [D-427](D-427-platform-three-parts-middleware-operations-learning.md), D-431(NCNN, 작업 중).
교훈: `docs/solutions/workflow-issues/cuda-wheel-install-over-wifi-times-out-on-the-model-pc-2026-10-03.md`.
