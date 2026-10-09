## D-571 팀 PC는 시뮬레이션을 미리 갖추고, 실행은 측정한 여유로 고른 PC에 상한을 걸어 보낸다

**Status:** Proposed (2026-10-09, 사용자 목표 "가제보 같은 것도 미리 준비해서 언제든 처리할 수 있게, 모델 PC·관제 PC까지, 자원을 적절히 분배하도록"). 저장소 조각(매니페스트 종류, 이미지, 실행기, 문서)만 이 브랜치에 있다. 어느 PC에도 아무것도 설치하지 않았다. 설치는 각 PC 소유자가 sudo로 한다. [D-530](D-530-host-management-desired-state-and-guard.md) 위에 선다.

### Context

2026-10-09 읽기 전용 측정(ssh, 출력마다 nonce):

| PC | OS | 코어 | RAM | 시뮬 스택 | docker | 사용 |
| --- | --- | --- | --- | --- | --- | --- |
| 모델 PC | Ubuntu 24.04 | 24 | 15 GB | Jazzy desktop, ros_gz, gz_ros2_control, Nav2 전부 설치 | 있음, `rosy` 계정은 소켓 권한 없음 | `remote_pytest.py` 실행기, 다른 세션의 Gazebo·학습. 측정 중 부하 25.5(코어당 1.06), 남은 메모리 1.8 GB, GPU 98 %인 때가 있었다 |
| AI PC | Ubuntu 24.04 | 24 | 15 GB | Jazzy desktop만(ros_gz·Nav2 없음) | 없음 | 같은 `ai` 계정에서 다른 사람의 nav2/amcl 스택과 Python 작업, `gz sim`이 돈다 |
| 관제 PC | Ubuntu 26.04 | 8 | 14 GB | `/opt/ros/jazzy`·`lyrical` 디렉터리만, Jazzy 데비안 패키지 없음 | 있음, Fleet·Vision·Proxy 운영 컨테이너 | 운영. 부하 코어당 0.05, 남은 메모리 13.8 GB |

- Gazebo는 이 노트북에서 돌리지 않는다. 지금은 세션마다 모델 PC에 자기 clone과 colcon 작업공간을 만들고, CORE pip 의존성을 손으로 넣었다(D-476 검증 기록). 준비가 세션마다 되풀이되고, 모델 PC가 바쁠 때 다른 PC로 보낼 방법이 없다.
- 모델 PC는 자주 바쁘고, AI PC와 관제 PC는 자주 한가하다. 그러나 AI PC는 다른 사람과 같이 쓰고(D-530 6항: 설치는 소유자 동의 뒤), 관제 PC는 운영이다.

### Decision

**1. PC별 역할.**

| 일 | 모델 PC | AI PC | 관제 PC |
| --- | --- | --- | --- |
| 호스트 pytest (`remote_pytest.py`) | 첫 번째 | 두 번째 | 하지 않음 |
| 헤드리스 Gazebo (`remote_sim.py`) | 기본, 네이티브 | 소유자가 설치에 동의한 뒤, 네이티브 | 마지막 수단, 컨테이너만 |
| 학습·모델 평가(D-434, D-527) | 맡음 | 하지 않음 | 하지 않음 |
| AI 추론(D-516, D-527) | 하지 않음 | 맡음 | 하지 않음 |
| 운영 Fleet·Vision(D-434) | 하지 않음 | 하지 않음 | 맡음, 언제나 우선 |

D-434 2항("관제 PC는 사이트 스택만, ROS 불필요")은 이렇게 고친다: 관제 PC 호스트에는 ROS를 설치하지 않는다. 시뮬레이션은 `rosy-sim:jazzy` 컨테이너로만, 아래 3항의 상한과 거절 조건 아래에서 돈다.

**2. 미리 갖춤은 D-530 매니페스트와 이미지로 한다.**

- `rosy-host-state`에 종류 `apt <패키지>...`를 더한다. `dpkg-query`로 확인하고 `apt-get install --no-install-recommends`로 설치한다.
- 모델 PC와 AI PC 매니페스트에 `approval=sim apt ...` 한 줄을 둔다. 목록은 `gz_sim`의 의존 닫힘(저장소 `package.xml`을 `gz_sim`까지 따라간 외부 키)이다. `sllidar_ros2`(Jazzy 데비안 없음, 장치 전용), `tf_transformations`, `joint_state_publisher_gui`(벤치 경로 밖)는 뺀다. CORE의 pip 고정(`requirements-core.txt`)은 Ubuntu의 pydantic 1과 맞지 않아 apt로 넣지 않고 실행기가 `~/rosy-test/sim-pydeps/`에 둔다.
- `approval=sim` 줄은 `install <role> --approve sim`일 때만 설치되고, 드리프트 타이머는 보고만 한다(설치하지 않는다).
- 관제 PC 매니페스트에는 apt 줄을 두지 않는다. 26.04에는 Jazzy 데비안이 없고, 운영 호스트의 패키지를 시뮬 때문에 바꾸지 않는다. 대신 `deploy/sim/Dockerfile`(ros:jazzy-ros-base + 같은 apt 목록 + CORE pip 고정 + `gz_sim`까지 colcon 빌드)을 git-archive 스냅샷에서 빌드한다. 이미지는 포트를 열지 않는다.

**3. 배치는 측정한 여유로 고른다.**

- `tools/remote/remote_sim.py`가 후보 PC마다 ssh로 nonce를 붙여 읽는다: 준비(네이티브 ros_gz·Nav2·gz_ros2_control, 또는 이미지), 코어당 부하, `MemAvailable`, `nvidia-smi` 사용률, 돌고 있는 `gz sim` 수, 누적 CPU 50 % 이상인 남의 프로세스 수.
- 거절 조건(어느 하나라도): 준비 안 됨, 코어당 부하가 상한 초과(모델·AI 0.9, 관제 0.3), 남은 메모리가 하한 미만(모델·AI 4 GB, 관제 8 GB), 관제 PC에서 이미 `gz sim`이 돎. Fleet 컨테이너가 도는 호스트는 이름과 관계없이 관제 PC 규칙을 받는다.
- 점수 = min(남은 코어 ÷ 실행당 CPU 상한, 남은 메모리 ÷ 실행당 메모리 상한) × 가중치 − 돌고 있는 `gz sim` 수 − (GPU 90 % 이상이면 1). 가중치는 관제 PC 0.5, 나머지 1. 점수가 0 이하이면 거절한다. 남의 무거운 프로세스는 표에 보이지만 점수에는 부하 평균으로만 들어간다.
- 가장 높은 점수의 PC, 또는 `--host`로 지정한 PC로 보낸다. 지정한 PC도 거절 조건을 그대로 받는다. 받아 줄 PC가 없으면 표를 보여 주고 실행하지 않는다.
- `--check`는 표만 출력한다.

**4. 상한.** 실행 하나당:

| 역할 | CPU | 메모리 | 방식 |
| --- | --- | --- | --- |
| 모델 PC | 8코어 | 6 GB | `systemd-run --user --scope -p MemoryMax -p CPUQuota`, `nice -n 10` |
| AI PC | 4코어 | 4 GB | 같음 |
| 관제 PC | 2코어 | 4 GB | `docker run --network none --cpus --memory --memory-swap --cpu-shares 256 --pids-limit 4096`, `nice -n 10` |

- 모든 실행은 벽시계 상한(기본 45분, colcon 빌드 포함)을 받는다. 실행마다 `GZ_PARTITION`이 다르고, `ROS_DOMAIN_ID`는 120–219 무작위, `ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST`, `GZ_IP=127.0.0.1`이다. 컨테이너는 `--network none`이라 loopback 밖으로 아무것도 열지 않는다.
- 커밋된 sha만 `remote_pytest.py`와 같은 git bundle로 `~/rosy-test/runs/sim-*`에 간다. 끝나면 출력(빌드·설치·임시 디렉터리 제외: 임시 디렉터리에는 실행의 robots.yaml 토큰이 있다)을 `X:\DevTemp`로 가져오고, 자기 scope(`rosy-sim-<이름>.scope`)나 컨테이너(`rosy-sim-<이름>`)만 멈추고 지운다.
- 관제 PC 보호는 시작 때 판정이다. 실행 중 Fleet 부하가 오르면 상한(`--cpus 2`, `--cpu-shares 256`, `nice`)이 Fleet 몫을 지킨다. 실행 중 감시해 끊는 기능은 두지 않는다(필요해지면 더한다).

**5. 같이 쓰는 AI PC.**

- 설치(`--approve sim`)는 소유자가 동의하고 소유자가 직접 sudo로 한다. 설치하지 않은 동안 실행기는 AI PC를 "준비 안 됨"으로 건너뛴다. 설치가 곧 동의의 기록이다.
- 실행기는 남의 프로세스를 멈추거나 우선순위를 바꾸지 않는다. 자기 scope만 정리하고, `pkill`·`kill`을 쓰지 않는다. 같은 `ai` 계정 안의 남의 `gz sim`은 점수에서 한 자리씩 뺀다.
- AI PC 상한은 모델 PC보다 낮다(4코어, 4 GB). 남은 메모리 4 GB 미만이면 거절한다.

### Consequences

- 모델 PC가 바쁘면 AI PC(설치 뒤)나 관제 PC 컨테이너(이미지 빌드 뒤)로 간다. 세션마다 작업공간과 pip 의존성을 손으로 만들지 않는다.
- 세 PC 모두 같은 저장소 커밋에서 colcon으로 빌드하므로 실행마다 빌드 시간(수 분)이 든다. 캐시는 두지 않는다.
- 관제 PC 이미지 빌드(수 GB 내려받기와 colcon)는 운영 시간 밖에 소유자가 한다.
- 실행 결과는 SIM 등급 증거일 뿐이다. 장치·필드 수용을 대신하지 않는다.

### Verification

호스트 pytest: `test/test_remote_sim.py`(가짜 probe 출력으로 nonce·준비·거절·점수·지정 PC·스크립트 구문), `test/test_host_state.py`(apt 줄은 `--approve sim`일 때만 설치, 타이머는 보고만, 관제 PC 매니페스트에는 apt 줄 없음). 실제 `--check` 표는 각 PC README에 날짜와 함께 남긴다. 설치와 실제 벤치 실행은 이 ADR의 증거가 아니며 설치 뒤 각 PC에서 따로 확인한다.

**Related:** [D-434](D-434-model-pc-and-site-pc-roles.md), [D-476 모델 PC Gazebo 검증](../validation/d476-gazebo-model-pc-2026-10-06/result.md), [D-527](D-527-decision-test-host-boundaries.md), [D-530](D-530-host-management-desired-state-and-guard.md), D-553(`remote_pytest.py` 분산).
