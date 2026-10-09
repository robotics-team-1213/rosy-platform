## D-568 계산 PC 풀 — 시험·시뮬레이션은 모델 PC·AI PC·현장 PC 가운데 여유가 있는 곳이 맡는다

**Status:** Proposed (2026-10-09, 사용자 지시 "서로 용량이 없으면 fleet까지 해서 서로 나눠 쓰도록 ADR로 개선해", "모델 PC가 꼭 시뮬레이션을 다 할 필요는 없어"). SOURCE(`tools/remote/remote_pytest.py`)와 호스트 테스트만이다. 호스트 설치(sudo)와 시뮬레이션 실행은 이 기록이 하지 않는다.

고치는 결정: [D-553](D-553-cd-speed-parallel-build-and-test-pcs.md) 4항(시험 PC는 모델 PC·AI PC 둘, 닿는 순서)과 5항 둘째 줄(현장 PC 제외). 잇는 결정: [D-436](D-436-change-scoped-test-tiers.md)(변경 범위 시험). 노트북은 계속 제외한다(Gazebo·pytest를 노트북에서 돌리지 않는다는 사용자 규칙).

### Context

2026-10-09 19:00 KST쯤 모델 PC(OMEN)가 load 8–35에서 응답을 멈췄다. 여러 세션의 pytest와 Gazebo 한 판이 같이 돌았다. D-559 SIM은 AI PC로 옮겨 갔다(그때 load 15/24, 다른 사람이 쓰는 PC). D-553의 `remote_pytest.py`는 "처음 닿는 호스트"만 보므로 닿기만 하면 이미 꽉 찬 모델 PC에 일을 더 얹는다. Gazebo는 사람이 호스트를 골랐다.

20:02 KST 측정(읽기 전용 ssh, nonce 463700):

| 호스트 | 스레드 | load 1분 | MemAvailable / 전체 | OS | sim 능력(`ros_gz_sim`·`nav2_bringup`) | `/usr/bin/python3` |
|---|---|---|---|---|---|---|
| 모델 PC `rosy@100.98.162.71` | 24 | 9.4 | 2.4 / 15.0 GB | 24.04 | 있음 | 3.12 |
| AI PC `ai@100.108.76.123` | 24 | 5.6 | 10.1 GB | 24.04 | 없음(D-559용 설치 중일 수 있음) | 3.12 |
| 현장 PC `robttt@100.82.51.8` | 8 | 0.3 | 13.1 / 14.8 GB | 26.04 | `ros_gz_sim`만(옛 개발 트리), nav2 없음 | 3.14 |

모델 PC는 닿지만 메모리 2.4 GB만 남아 있었다. 순서로 고르면 이런 호스트가 먼저 뽑힌다.

### Decision

1. **풀과 일의 종류.** 풀은 모델 PC, AI PC, 현장 PC다. 노트북은 넣지 않는다. 일은 셋으로 나눈다.
   - `pytest`(브라우저 시험 포함): 커밋 하나의 pytest invocation.
   - `sim`: Gazebo 한 판. ROS Jazzy, gz, `ros_gz`, nav2가 있어야 한다.
   - `model`: GPU 학습·내보내기. 모델 PC만 한다. 바뀌지 않으며 이 도구가 배치하지 않는다.
2. **순서가 아니라 잰 여유로 고른다.** 일을 줄 때마다 각 호스트를 ssh로 한 번 잰다(5 s 연결 제한, 동시에). 재는 값: `nproc`, 1분 loadavg, `MemAvailable`·`MemTotal`, 능력(`pytest` = `/usr/bin/python3`가 3.12, `sim` = `/opt/ros/jazzy/share/ros_gz_sim`와 `nav2_bringup`이 있음), 작업 잠금, 사용 중 표시.
   - **작업 잠금:** 호스트의 `~/rosy-jobs/<이름>.lock` 한 줄 `pid 종류 코어 GB`. pytest는 `remote_pytest.py`가 쓰고 지운다(`<pid> pytest 2 6`). Gazebo 스크립트는 시작할 때 `echo "$$ sim 6 8" > ~/rosy-jobs/sim-$$.lock`를 쓰고 끝날 때 지운다. pid가 죽은 잠금은 잴 때 지운다.
   - **여유:** 코어 = `nproc − max(load1, 잠금 코어 합)`, 메모리 = `min(MemAvailable, MemTotal − 잠금 GB 합)`. 막 시작해 아직 load에 잡히지 않은 일을 잠금이 메운다.
   - **하한:** `pytest` 코어 2·메모리 6 GB(pytest 한 invocation의 `MemoryMax=6G`와 같다). `sim` 코어 6·메모리 8 GB(Pinky 한 대 Gazebo 서버·센서 렌더링 + Nav2 + CORE를 위한 추정이다. 실측 기록이 없어 첫 측정 뒤 `NEEDS`를 고친다). 하한 아래인 호스트는 고르지 않는다.
   - **순위:** 하한을 넘은 호스트를 `min(코어 여유/코어 하한, 메모리 여유/메모리 하한)`이 큰 순서로 쓴다. 같으면 `ROSY_TEST_HOSTS`의 순서다.
   - invocation이 여럿이면 하한을 넘은 호스트 모두에 `k % n`으로 나눈다(D-553 4항의 분배와 실패 인계는 그대로).
3. **현장 PC는 라이브 Fleet가 먼저다.**
   - 맨 뒤다. 다른 호스트가 하나도 하한을 넘지 못할 때만 받는다.
   - 여유를 잴 때 Fleet 몫으로 코어 2개와 4 GB를 먼저 뺀다. 8스레드라 `sim` 하한(6)은 사실상 넘지 못한다.
   - 상한: pytest는 `systemd-run --user --scope -p MemoryMax=6G -p CPUQuota=400%` 안에서 `nice -n 15 ionice -c3`로 돈다.
   - Fleet이 운영 중이면 받지 않는다. Fleet의 읽기 엔드포인트(`/api/fleet/trips` 등)는 토큰이 있어야 하고, 인증 없는 `/healthz`는 살아 있는지만 알려 준다. 그래서 판단은 운영자 표시 파일 `~/rosy-jobs/busy`로 한다. 시연·주행 전에 `touch ~/rosy-jobs/busy`, 끝나면 지운다. 이 파일은 어느 호스트에나 둘 수 있다(AI PC 주인도 쓸 수 있다).
   - `model` 일은 받지 않는다.
   - Wi-Fi만 있다. 커밋 번들(첫 회 전체 이력)과 venv 내려받기가 유선보다 느리다. 하한을 넘는 다른 호스트가 있으면 쓰지 않는 이유 하나다.
4. **AI PC는 다른 사람의 PC다.** 모든 pytest는 `MemoryMax=6G`와 `nice -n 15 ionice -c3` 안에서 돈다. 모델 PC에도 같은 줄을 쓴다. 한 경로가 단순하고, 모델 PC에서도 학습이 우선이다.
5. **`sim` 준비는 사람이 한다.** 도구는 능력만 보고 설치하지 않는다. sudo가 있는 사람이 Ubuntu 24.04 + Jazzy 호스트에 한 번 한다.

   ```bash
   sudo apt install ros-jazzy-ros-gz ros-jazzy-navigation2 ros-jazzy-nav2-bringup \
     ros-jazzy-gz-ros2-control ros-jazzy-robot-state-publisher ros-jazzy-xacro
   ```

   Gazebo 스크립트는 `python tools/remote/remote_pytest.py --pick sim`으로 호스트를 받는다. 표준 출력 한 줄이 호스트, 표준 오류가 호스트마다의 여유와 이유다. 맞는 호스트가 없으면 exit 1이다. 데몬이나 대기열은 만들지 않는다.
6. **배치는 보인다.** 도구는 잰 호스트마다 `호스트: 코어·GB 여유, 고름/뺀 이유`를 찍고, 고른 호스트를 찍는다.
7. **잴 수 없을 때는 예전처럼 한다.** `ROSY_TEST_HOSTS`는 그대로 덮어쓴다(기본 모델 PC, AI PC, 현장 PC). `ROSY_TEST_LOCAL=1`·`--local`도 그대로다. pytest에서 하한을 넘는 호스트가 없으면 닿는 비현장 호스트(python 3.12)를 목록 순서로 쓰고 경고를 찍는다. 게이트가 바쁘다는 이유만으로 멈추지 않게 한다. 현장 PC는 이 대체 경로에 들어가지 않는다. `sim`은 대체하지 않는다.

### Consequences

- 꽉 찬 모델 PC는 pytest를 받지 않고, 여유가 있는 AI PC가 받는다. 시뮬레이션은 능력과 여유가 있는 곳으로 간다.
- 일을 줄 때마다 ssh 잼 한 번(호스트 셋, 동시)이 더 든다. 1–2 s다.
- 잠금은 협조적이다. 이 도구와 잠금을 쓰는 스크립트만 서로 본다. 다른 사람의 일은 load와 MemAvailable로만 보인다.
- load1은 1분 평균이라 늦다. 같은 순간에 시작한 둘이 같은 호스트를 고를 수 있다. 잠금이 그 창을 몇 초로 줄인다.
- `nice`/`ionice` 때문에 바쁜 호스트에서는 pytest가 느려질 수 있다. 시간 제한(`ROSY_TEST_TIMEOUT`)은 그대로다.
- 시험: `test/test_remote_pytest.py`(가짜 잼 값으로 하한·순위·현장 PC 뒤·busy·능력·대체 경로).

### Alternatives

- **정해진 순서(D-553)**: 오늘 사고가 그 결과다. 버린다.
- **GitHub self-hosted 러너**: D-553 5항의 이유(공개 저장소, ARM64)가 그대로다. 쓰지 않는다.
- **스케줄러 데몬·대기열**: 호스트 셋, 일 수십 개에는 과하다. 잴 때마다 고르는 것으로 충분하다.

### Open items

- **현장 PC는 오늘 아무 일도 받지 못한다.** Ubuntu 26.04라 `/usr/bin/python3`가 3.14다. pytest venv는 3.12 휠 해시를 쓴다. 3.12 인터프리터(uv의 `uv python install 3.12`, sudo 불필요)와 `VENV`의 `-p` 변경이 따로 필요하다. Jazzy deb는 24.04용이라 `sim`은 컨테이너로 돌리거나, 확인될 때까지 현장 PC는 pytest 전용이다.
- AI PC의 `sim` 능력은 D-559용 설치가 끝나면 생긴다. 이 도구는 설치를 기다리지 않고 잴 때 본다.
- Fleet 운영 판단을 자동으로(읽기 토큰으로 활성 trip·연결 로봇 수를 보기) 바꾸는 것은 뒤로 미룬다. 지금은 `~/rosy-jobs/busy`다.
- 기존 `run_sim.sh`(증거 폴더)는 고치지 않는다. 새 Gazebo 스크립트가 `--pick sim`과 잠금 줄을 쓴다.
