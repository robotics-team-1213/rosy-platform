## D-571 모델·AI PC는 시뮬레이션을 미리 갖추고, 실행은 측정한 여유로 고른 PC에 상한을 걸어 보낸다. 관제 PC는 운영 전용이다

**Status:** Proposed (2026-10-09, 사용자 목표 "가제보 같은 것도 미리 준비해서 언제든 처리할 수 있게, 자원을 적절히 분배하도록"과 사용자 결정 "관제 PC는 시뮬레이션에서 제외"(2026-10-09)). 저장소 조각(매니페스트 종류, 실행기, 문서)만 이 브랜치에 있다. 어느 PC에도 아무것도 설치하지 않았다. 설치는 각 PC 소유자가 sudo로 한다. [D-530](D-530-host-management-desired-state-and-guard.md) 위에 선다.

### Context

2026-10-09 읽기 전용 측정(ssh, 출력마다 nonce):

| PC | OS | 코어 | RAM | 시뮬 스택 | 사용 |
| --- | --- | --- | --- | --- | --- |
| 모델 PC | Ubuntu 24.04 | 24 | 15 GB | Jazzy desktop, ros_gz, gz_ros2_control, Nav2 전부 설치 | `remote_pytest.py` 실행기, 다른 세션의 Gazebo·학습. 측정 중 부하 25.5(코어당 1.06), 남은 메모리 1.8 GB, GPU 98 %인 때가 있었다 |
| AI PC | Ubuntu 24.04 | 24 | 15 GB | Jazzy desktop만(ros_gz·Nav2 없음) | 같은 `ai` 계정에서 다른 사람의 nav2/amcl 스택과 Python 작업, `gz sim`이 돈다 |
| 관제 PC | Ubuntu 26.04 | 8 | 14 GB | Jazzy 데비안 패키지 없음 | 운영 Fleet·Vision·Proxy 컨테이너 |

- Gazebo는 이 노트북에서 돌리지 않는다. 지금은 세션마다 모델 PC에 자기 clone과 colcon 작업공간을 만들고, CORE pip 의존성을 손으로 넣었다(D-476 검증 기록). 준비가 세션마다 되풀이되고, 모델 PC가 바쁠 때 다른 PC로 보낼 방법이 없다.
- 모델 PC는 자주 바쁘고 AI PC는 자주 한가하다. 그러나 AI PC는 다른 사람과 같이 쓴다(D-530 6항: 설치는 소유자 동의 뒤). 관제 PC는 한가해도 운영이다.

### Decision

**1. PC별 역할.**

| 일 | 모델 PC | AI PC | 관제 PC |
| --- | --- | --- | --- |
| 호스트 pytest (`remote_pytest.py`) | 첫 번째 | 두 번째 | 하지 않음 |
| 헤드리스 Gazebo (`remote_sim.py`) | 기본, 네이티브 | 소유자가 설치에 동의한 뒤, 네이티브 | **하지 않음** |
| 학습·모델 평가(D-434, D-527) | 맡음 | 하지 않음 | 하지 않음 |
| AI 추론(D-516, D-527) | 하지 않음 | 맡음 | 하지 않음 |
| 운영 Fleet·Vision(D-434) | 하지 않음 | 하지 않음 | 맡음, 전용 |

관제 PC는 운영 전용이고 시뮬레이션 배치에서 빠진다. 사용자 결정: "관제 PC는 시뮬레이션에서 제외"(2026-10-09). 관제 PC에는 ROS, 시뮬 패키지, 시뮬 이미지를 설치하지 않는다. D-434 2항("관제 PC는 사이트 스택만")은 그대로다.

**2. 미리 갖춤은 D-530 매니페스트로 한다.**

- `rosy-host-state`에 종류 `apt <패키지>...`를 더한다. `dpkg-query`로 확인하고 `apt-get install --no-install-recommends`로 설치한다.
- 모델 PC와 AI PC 매니페스트에 `approval=sim apt ...` 한 줄을 둔다. 목록은 `gz_sim`의 의존 닫힘(저장소 `package.xml`을 `gz_sim`까지 따라간 외부 키)이다. `sllidar_ros2`(Jazzy 데비안 없음, 장치 전용), `tf_transformations`, `joint_state_publisher_gui`(벤치 경로 밖)는 뺀다. CORE의 pip 고정(`requirements-core.txt`)은 Ubuntu의 pydantic 1과 맞지 않아 apt로 넣지 않고 실행기가 `~/rosy-test/sim-pydeps/`에 둔다.
- `approval=sim` 줄은 `install <role> --approve sim`일 때만 설치되고, 드리프트 타이머는 보고만 한다(설치하지 않는다).
- 관제 PC 매니페스트에는 apt 줄을 두지 않는다.
- 컨테이너 이미지는 두지 않는다. 남은 두 PC 중 모델 PC의 `rosy` 계정은 docker 소켓 권한이 없고 AI PC에는 docker가 없어, 이미지를 쓸 호스트가 없다.

**3. 배치는 측정한 여유로 고른다.**

- 후보는 `ROSY_SIM_HOSTS`(기본 모델 PC, AI PC)다. 관제 PC는 목록에 적혀 있어도 빠지고, `--host site`나 관제 PC 주소를 지정하면 "production only, excluded from simulation (D-571)"로 거절한다. Fleet 컨테이너가 도는 호스트는 이름과 관계없이 같은 이유로 거절한다. `--check` 표는 관제 PC를 이 문구로 한 줄 보여 준다.
- `tools/remote/remote_sim.py`가 후보 PC마다 ssh로 nonce를 붙여 읽는다: 준비(네이티브 ros_gz·Nav2·gz_ros2_control), 코어당 부하, `MemAvailable`, `nvidia-smi` 사용률, 돌고 있는 `gz sim` 수, 누적 CPU 50 % 이상인 프로세스 수.
- 거절 조건(어느 하나라도): 준비 안 됨, 코어당 부하 0.9 초과, 남은 메모리 4 GB 미만.
- 점수 = min(남은 코어 ÷ 실행당 CPU 상한, 남은 메모리 ÷ 실행당 메모리 상한) − 돌고 있는 `gz sim` 수 − (GPU 90 % 이상이면 1). 점수가 0 이하이면 거절한다. 무거운 프로세스는 표에 보이지만 점수에는 부하 평균으로만 들어간다.
- 가장 높은 점수의 PC, 또는 `--host`로 지정한 PC로 보낸다. 지정한 PC도 거절 조건을 그대로 받는다. 받아 줄 PC가 없으면 표를 보여 주고 실행하지 않는다.
- `--check`는 표만 출력한다.

**4. 상한.** 실행 하나당 `systemd-run --user --scope -p MemoryMax -p CPUQuota`, `nice -n 10`:

| 역할 | CPU | 메모리 |
| --- | --- | --- |
| 모델 PC | 8코어 | 6 GB |
| AI PC | 4코어 | 4 GB |

- 모든 실행은 벽시계 상한(기본 45분, 컴파일 포함)을 받는다. 실행마다 `GZ_PARTITION`이 다르고, `ROS_DOMAIN_ID`는 120–219 무작위, `ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST`, `GZ_IP=127.0.0.1`이다.
- 커밋된 sha만 `remote_pytest.py`와 같은 git bundle로 `~/rosy-test/runs/sim-*`에 간다. 끝나면 출력(빌드·설치·임시 디렉터리 제외: 임시 디렉터리에는 실행의 robots.yaml 토큰이 있다)을 `X:\DevTemp`로 가져오고, 자기 scope(`rosy-sim-<이름>.scope`)만 멈추고 지운다.

**5. 같이 쓰는 AI PC.**

- 설치(`--approve sim`)는 소유자가 동의하고 소유자가 직접 sudo로 한다. 설치하지 않은 동안 실행기는 AI PC를 "준비 안 됨"으로 건너뛴다. 설치가 곧 동의의 기록이다.
- 실행기는 남의 프로세스를 멈추거나 우선순위를 바꾸지 않는다. 자기 scope만 정리하고, `pkill`·`kill`을 쓰지 않는다. 같은 `ai` 계정 안의 남의 `gz sim`은 점수에서 한 자리씩 뺀다.
- AI PC 상한은 모델 PC보다 낮다(4코어, 4 GB).

### Consequences

- 모델 PC가 바쁘면 AI PC(설치 뒤)로 간다. 둘 다 바쁘면 기다린다. 관제 PC로 넘기지 않는다. 세션마다 작업공간과 pip 의존성을 손으로 만들지 않는다.
- 같은 저장소 커밋에서 colcon으로 빌드하므로 실행마다 빌드 시간(수 분)이 든다. 캐시는 두지 않는다.
- 실행 결과는 SIM 등급 증거일 뿐이다. 장치·필드 수용을 대신하지 않는다.

### Verification

호스트 pytest: `test/test_remote_sim.py`(가짜 probe 출력으로 nonce·준비·거절·점수·지정 PC, 관제 PC 제외와 `--host site` 거절, 스크립트 구문), `test/test_host_state.py`(apt 줄은 `--approve sim`일 때만 설치, 타이머는 보고만, 관제 PC 매니페스트에는 apt 줄 없음). 2026-10-09 모델 PC에서 실행기로 `gz_sim` 빌드와 헤드리스 `gz_multi` 한 대 spawn까지 확인했고, 실행 뒤 남은 scope·프로세스·폴더는 없었다. 설치와 실제 벤치 실행 결과는 이 ADR의 증거가 아니며 설치 뒤 각 PC에서 따로 확인한다.

**Related:** [D-434](D-434-model-pc-and-site-pc-roles.md), [D-476 모델 PC Gazebo 검증](../validation/d476-gazebo-model-pc-2026-10-06/result.md), [D-527](D-527-decision-test-host-boundaries.md), [D-530](D-530-host-management-desired-state-and-guard.md), D-553(`remote_pytest.py` 분산).
