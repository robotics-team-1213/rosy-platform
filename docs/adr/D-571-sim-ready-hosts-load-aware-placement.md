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
| 호스트 pytest (`remote_pytest.py`) | D-568 여유 순 | D-568 여유 순 | 다른 PC가 하한을 넘지 못할 때만(D-568 3항) |
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

**3. 배치는 D-568의 잰 여유로 고른다.** (2026-10-13 개정)

- 후보는 `ROSY_SIM_HOSTS`(`user@addr[=role]`), 없으면 gitignore된 `private/lab-hosts.json`의 `sim_hosts`, 그것도 없으면 `remote_pytest.py`의 시험 호스트다. 주소는 공개 저장소에 적지 않는다(D-226). 역할(`model`, `ai`, 기본 `ai`)은 4항의 상한만 고른다.
- 관제 PC는 목록에 적혀 있어도 빠진다. `=site` 역할, 설정된 현장 호스트(`site_host`), `~/rosy-jobs/site` 표시가 있는 호스트(D-568 3항: 라이브 Fleet 호스트에 둔다)는 이름과 관계없이 쓰지 않는다. `--host site`나 현장 호스트 주소를 지정하면 "production only, excluded from simulation (D-571)"로 거절한다.
- 재기와 순위는 `remote_pytest.py`의 `placed_hosts("sim")` 하나다(D-568 2항). 호스트마다 ssh 한 번으로 코어, load, 메모리, `sim` 능력(`ros_gz_sim`·`nav2_bringup`), `~/rosy-jobs`의 잠금·예약, `busy`를 읽고, `sim` 하한(코어 6, 8 GB)을 넘은 호스트를 여유가 큰 순서로 쓴다. 이 실행기는 따로 재지 않는다.
- 예약은 커밋 전송(`remote_pytest.ship`)이 쓰는 `<실행>.resv` 하나다. 값은 pytest 크기(2코어, 6 GB, 최대 75분)라 잠금 전까지는 이 실행의 상한보다 작게 세어진다. 실행이 시작되면 그 예약을 지우고 `~/rosy-jobs/<실행>.lock`(`pid sim 코어 GB`, 4항의 상한 값)을 잡는다. 잠금은 원격 셸이 끝날 때 스스로 지운다. `pick-*` 예약은 쓰지 않는다(같은 일이 두 번 세어져 pytest가 관제 PC로 밀릴 수 있다).
- `--host`로 지정한 PC도 같은 하한을 받는다. 받아 줄 PC가 없으면 호스트마다의 이유를 찍고 실행하지 않는다. `--check`는 그 이유만 찍는다.

**4. 상한.** 실행 하나당 `systemd-run --user --scope -p MemoryMax -p CPUQuota`, `nice -n 10`:

| 역할 | CPU | 메모리 |
| --- | --- | --- |
| 모델 PC | 8코어 | 6 GB |
| AI PC | 4코어 | 4 GB |

- 모든 실행은 벽시계 상한(기본 45분, 컴파일 포함)을 받는다. 실행마다 `GZ_PARTITION`이 다르고, `ROS_DOMAIN_ID`는 1–19 무작위(2026-10-13 개정: Linux 안전 범위 0–101 안, 기본값 0과 로봇 40+N·OMX 30/31/75–77·`run_fleet_sim.sh` 20–79·`fleet_gazebo` 80–99를 피함), `ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST`, `GZ_IP=127.0.0.1`이다.
- 커밋된 sha만 `remote_pytest.py`와 같은 git bundle로 `~/rosy-test/runs/sim-*`에 간다. 끝나면 원격 셸이 먼저 자기 scope(`rosy-sim-<이름>.scope`)만 멈추고 잠금과 빌드·설치·임시 디렉터리(실행의 robots.yaml 토큰이 있다)를 지운다. 그 다음 남은 출력을 `X:\DevTemp`로 가져오고, 가져오기가 성공했을 때만 호스트의 출력 폴더를 지운다. 실패하면 이유를 찍고 폴더를 남긴다.
- scope 안에서 도는 것: CORE pip 의존성 설치, colcon 빌드(`--parallel-workers` = CPU 상한), 벤치. scope 밖에서 도는 것: 커밋 전송, 출력 가져오기(tar), 정리. 이들은 상한 없이 `nice -n 15 ionice -c3`로만 돈다(D-568 4항과 같다). `MemorySwapMax`는 `remote_pytest.py`처럼 두지 않으므로 메모리 상한을 넘으면 swap을 쓸 수 있다.
- 노트북이 사라져도 호스트가 스스로 정리한다. 원격 셸이 끝날 때(늦어도 벽시계 상한에) scope를 멈추고 잠금과 빌드·설치·임시 디렉터리를 지운다. 소스 체크아웃(`runs/sim-*`)과 로그 폴더는 남는다. 이 둘은 노트북의 정리 단계만 지운다.

**5. 같이 쓰는 AI PC.**

- 설치(`--approve sim`)는 소유자가 동의하고 소유자가 직접 sudo로 한다. 설치하지 않은 동안 실행기는 AI PC를 "준비 안 됨"으로 건너뛴다. 설치가 곧 동의의 기록이다.
- 실행기는 남의 프로세스를 멈추거나 우선순위를 바꾸지 않는다. 자기 scope만 정리하고, `pkill`·`kill`을 쓰지 않는다. 같은 `ai` 계정 안의 남의 `gz sim`은 load와 남은 메모리로만 보인다(D-568 Consequences).
- AI PC 상한은 모델 PC보다 낮다(4코어, 4 GB).

### Consequences

- 모델 PC가 바쁘면 AI PC(설치 뒤)로 간다. 둘 다 바쁘면 실행하지 않고 끝난다(D-568 7항: `sim`은 대체하지 않는다). 관제 PC로 넘기지 않는다. 세션마다 작업공간과 pip 의존성을 손으로 만들지 않는다.
- 같은 저장소 커밋에서 colcon으로 빌드하므로 실행마다 빌드 시간(수 분)이 든다. 캐시는 두지 않는다.
- 실행 결과는 SIM 등급 증거일 뿐이다. 장치·필드 수용을 대신하지 않는다.

### Verification

호스트 pytest: `test/test_remote_sim.py`(후보 출처와 역할, 가짜 잼 값으로 D-568 하한·순위·잠금·busy, 관제 PC 제외와 `--host site` 거절, 작업 잠금 줄, 스크립트 구문), `test/test_host_state.py`(apt 줄은 `--approve sim`일 때만 설치, 타이머는 보고만, 관제 PC 매니페스트에는 apt 줄 없음). 2026-10-09에 "모델 PC에서 실행기로 `gz_sim` 빌드와 헤드리스 `gz_multi` 한 대 spawn까지 확인했다"고 적었으나, 그 확인은 `swarm_bench` 경로에서 나올 수 없다. 같은 대기 루프가 그때 코드에도 있었고 `set -eo pipefail` 아래 첫 반복에서 끝난다(2026-10-13 검토에서 재현). 어느 경로였는지 기록이 없으므로 증거로 세지 않는다. 설치와 실제 벤치 실행 결과는 이 ADR의 증거가 아니며 설치 뒤 각 PC에서 따로 확인한다. 지금 실행기(D-568 배치, 작업 잠금, 원격 정리, 가져오기 순서)는 호스트 pytest만 거쳤다. 실제 PC에서 ssh로도 Gazebo로도 한 번도 돌리지 않았다.

### 2026-10-13 개정 (main 합류)

이 브랜치가 쓰인 뒤 main에 [D-568](D-568-compute-pool-headroom-placement.md)(잰 여유 배치, `~/rosy-jobs` 잠금·예약), [D-584](D-584-tests-never-run-on-operator-laptop.md)(시험은 노트북에서 돌리지 않는다), D-226의 호스트 주소 분리(`private/lab-hosts.json`)가 들어왔다. 겹치는 곳은 main의 규칙을 따른다.

- 1항 표의 pytest 줄: "관제 PC는 하지 않음"을 D-568 3항(맨 뒤, Fleet 몫 제외)으로 고쳤다. 관제 PC의 시뮬레이션 제외는 그대로다.
- 3항: 실행기의 자체 probe와 점수(nonce, `gz_ros2_control` 확인, Fleet 컨테이너 감지, `gz sim` 수·GPU 감점, 코어당 부하 0.9·4 GB 거절)를 없애고 D-568의 재기 하나를 쓴다. 준비 여부는 D-568의 `sim` 능력(`ros_gz_sim`·`nav2_bringup`)으로 본다. `gz_ros2_control`이 빠진 PC는 실행 중 launch 오류로 드러난다. Fleet 호스트는 `~/rosy-jobs/site` 표시로 가린다.
- 기본 호스트 주소를 코드에서 빼고 `sim_hosts`(D-226)로 옮겼다.
- 4항의 상한(모델 8코어·6 GB, AI 4코어·4 GB)은 그대로다. 하한은 D-568의 `sim` 값(코어 6, 8 GB)이라 상한과 숫자가 다르다. 잠금에는 상한을 적는다.
- 검토 뒤 고친 것(같은 날): `swarm_bench` 대기 루프, scope를 멈춘 뒤 출력 가져오기, `pick-*` 예약 삭제, 원격 셸의 자체 정리, 실패한 pip 설치를 캐시하지 않기, `ROS_DOMAIN_ID` 1–19. `apt` 줄은 빠진 패키지만 `--no-upgrade --no-remove`로 설치하고 approval 정책에서만 받는다.
- `remote_pytest.py --pick sim`(D-568 5항)은 바꾸지 않았다. 관제 PC가 `sim` 능력과 하한을 갖추면 그 경로는 관제 PC를 고를 수 있다. 지금은 8스레드와 nav2 부재로 넘지 못한다(D-568 3항).

**Related:** [D-434](D-434-model-pc-and-site-pc-roles.md), [D-476 모델 PC Gazebo 검증](../validation/d476-gazebo-model-pc-2026-10-06/result.md), [D-527](D-527-decision-test-host-boundaries.md), [D-530](D-530-host-management-desired-state-and-guard.md), D-553(`remote_pytest.py` 분산), [D-568](D-568-compute-pool-headroom-placement.md), [D-584](D-584-tests-never-run-on-operator-laptop.md).

**정정 (2026-10-27):** 4항의 실행당 상한은 [D-867](D-867-ai-pc-sim-caps-for-vla-probes.md)이 바꿨다(AI PC 12코어·10GB, 모델 PC 16코어·10GB). 배치 규칙과 관제 PC 제외는 이 ADR 그대로다.
