# 모델 PC Isaac Lab 강화학습 환경 점검 — 2026-10-10

**판정: 설치 경로 확인, 강화학습 실행 준비 HOLD.** 모델 PC에 기존 SDK·Lab·CUDA·Jazzy가 있으나 RAM과 의존성 게이트가 실패했고, D-322 I1의 전진 추종·물리 정지 실패도 남아 있다. 이 점검에서 시뮬레이터나 학습을 실행하지 않았다.

## 읽기 전용 관측

기존 모델 PC에 BatchMode SSH로 접속했다. 주소·계정·키는 기록하지 않는다. 기존 작업의 `~/rosy-jobs/*.lock` 하나가 있었으므로 GPU 작업을 시작하지 않았다.

| 항목 | 관측 | 판정 |
|---|---|---|
| 메모리 | `free -h`: 물리 RAM 15 GiB, 가용 약 9.6 GiB, swap 43 GiB | [Isaac Sim 5.1 최소 32 GB](https://docs.isaacsim.omniverse.nvidia.com/5.1.0/installation/requirements.html) 미달; swap 제외 |
| GPU | `nvidia-smi`: RTX 5080 Laptop GPU, VRAM 16303 MiB, 드라이버 580.178.04 | GPU 인식; 학습 가용 용량·안정성 미검증 |
| 저장 공간 | `df -h ~`: 홈 약 265 GB 여유 | 후보 환경 공간은 있으나 실제 설치 크기 미측정 |
| Isaac | `~/isaac-sim-workspace/.venv`의 `pip show`: Isaac Sim 5.1.0.0, Python 3.11; `IsaacLab` Git 태그 v2.3.2 | 버전 핀 확인 |
| 학습 프레임워크 | 같은 venv: `isaaclab` 0.54.2, `isaaclab_tasks` 0.11.12, `rl-games` 1.6.1, PyTorch 2.7.0+cu128; `torch.cuda.is_available()` True | import/CUDA 기본 확인, reset/step·학습은 미실행 |
| ROS | `/opt/ros/jazzy/setup.bash` 존재; source 후 `ros2 --help` 성공 | CLI 준비; Isaac ROS graph 연동 미실행 |
| 의존성 | 기존 Isaac venv의 `python -m pip check` 실패: Isaac Sim 핀과 `filelock`, `fsspec`, `numpy`, `psutil` 등 충돌 및 누락 | 후보 환경에서 해결 필요. 기존 venv 제자리 수정 안 함 |

Isaac Lab 소스 Git 작업 트리는 점검 당시 변경을 보고하지 않았다. `pip check` 실패를 무시하고 기본 RL task가 실행된다고 판단하지 않는다. 이전 [2026-10-04 I1 실측](../cell-isaac-2026-10-04/isaac-core-drive.md)에서 실제 전진 추종과 만료 뒤 정착은 HOLD였다.

## 다음 검증

1. 물리 RAM을 32 GB 이상으로 늘린 뒤 실제 용량과 동시 GPU 작업을 재확인한다.
2. 기존 venv는 보존하고 별도 후보 환경에 5.1/v2.3.2 핀을 적용해 `pip check` 0을 얻는다. Python 3.11·CUDA Torch와 Isaac Lab 기본 task의 headless reset/step을 검증한다.
3. D-322의 CORE→Isaac 명령, 휠 추종, 명령 만료 뒤 실제 정지를 독립 관측으로 통과시킨다. 그다음 선택한 ROSY 행동에 대해 기존 로직과 RL 후보의 같은 폐루프 시나리오를 비교한다.

이번 결과는 설치 현황의 원격 점검이다. ROS-SIM, 학습 실행, 장치·현장 수용은 증명하지 않는다.
