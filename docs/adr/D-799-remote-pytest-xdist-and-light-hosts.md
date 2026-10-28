## D-799 원격 pytest를 호스트 안에서 병렬로 돌리고, 메모리 하한 아래 호스트도 가벼운 일을 받는다

**Status:** Proposed (2026-10-18, 사용자 지시 "로컬 착지 시험을 빠르게 해라"). SOURCE(`tools/remote/remote_pytest.py`, `xdist_plan.py`, `serial_suites.txt`, `remote_job.py`, `work_queue.py`)와 호스트 테스트만이다. 시험 PC에서 직렬과 `-n`을 비교한 측정은 아직 없다. D-568 2항(하한)과 D-553(공유 큐)을 고친다. D-584(노트북에서 돌리지 않음)와 D-568 3항(현장 PC는 맨 뒤), 7항(대체 경로)은 그대로다.

### Context

- 2026-10-18 착지에서 invocation 하나(7,151개 시험: gateway, events, services, shared/web, contracts/foundation, Pinky·OMX profile)가 16코어 모델 PC에서 직렬로 722초 걸렸다. 저장소 어디에도 pytest-xdist가 없었다.
- AI PC(18코어)는 여유 메모리가 약 5 GB라 pytest 하한 2코어/6 GB에 걸려 한 번도 고르지 않았다. 모든 invocation이 한 호스트에서 돌았다.

### Decision

1. **원격 venv에 `pytest-xdist==3.8.0`을 깐다.** VENV 설치 줄이 바뀌므로 입력 해시가 바뀌고 호스트마다 venv를 한 번 다시 만든다. CI(`ci.yml`)는 바꾸지 않는다. CI는 이미 matrix로 나눠 돌고, 플러그인은 `-n`이 없으면 시험 결과를 바꾸지 않는다.
2. **안전한 invocation만 `-n W --dist loadfile`로 돈다.** W는 그 호스트의 잰 여유 코어, 여유 GB(워커당 1 GB로 가정), job의 `MemoryMax=6G`(최대 6), 현장 PC의 `CPUQuota=400%`(최대 4) 가운데 가장 작은 값이다. 2보다 작으면 직렬이다. `loadfile`은 파일 하나를 한 워커에 두어 파일 안 순서와 module fixture가 직렬과 같다. 노트북의 `ROSY_TEST_WORKERS=n`이 W를 덮는다(측정용, 0·1은 직렬).
3. **직렬로 남기는 것.** 브라우저 job(`ROSY_RUN_BROWSER_TESTS=1`), node id를 적은 invocation(격리 재실행, D-790 부하성 재실행), 경로가 없는 것, 스스로 `-n`/`-p no:xdist`를 적은 것, `tools/remote/serial_suites.txt`의 접두 경로 아래나 위를 적은 것. 그 목록은 rclpy·`ROS_DOMAIN_ID`·고정 포트·playwright·저장소 안 git·홈 디렉터리를 쓰는 묶음(루트 `test/`, perception, Gazebo, Fleet, overhead 등)으로 시작한다. 한 줄은 시험 PC에서 직렬과 `-n`의 실패가 같다는 것을 본 뒤에만 뺀다.
4. **job 잠금은 실제 몫을 적는다.** xdist job은 `ROSY_JOB_CORES=W`로 `~/rosy-jobs/<run>.lock`에 W코어를 적어 다른 세션의 배치가 그만큼 뺀다. 격리 재실행도 같은 몫을 유지한다(직렬이라 넉넉하게 센다).
5. **가벼운 호스트.** pytest 여유 메모리가 4 GB 이상 6 GB 미만이면 그 호스트는 가볍다. 하한을 넘는 호스트 뒤, 현장 PC 앞에 놓는다. 공유 큐의 작은 쪽(맨 뒤)부터 가져가고, 직렬로 돌며, `MemoryMax`를 자기 여유 GB(정수)로 낮춘다(`ROSY_JOB_MEM_GB`). 그래서 다른 사용자가 쓰는 AI PC의 메모리를 넘지 못하고, 넘으면 그 invocation이 OOM으로 빨갛게 끝난다(조용한 통과가 아님). `sim`에는 가벼운 등급이 없다. 현장 PC는 다른 호스트(가벼운 호스트 포함)가 하나도 없을 때만 받는다.

### 일부러 하지 않는 것

- ROS 시험에 워커별 `ROS_DOMAIN_ID`를 주지 않는다. 원격 venv에는 rclpy가 없고(ROS를 source하지 않음), rclpy를 쓰는 묶음은 직렬 목록에 있다.
- invocation 크기로 xdist를 끄지 않는다. 작은 invocation은 워커 기동(수 초)만큼 손해를 볼 수 있다. 측정 뒤 정한다.
- 워커당 1 GB는 측정값이 아니다. 측정 계획의 실제 RSS로 고친다.

### 검증

- `test/test_remote_pytest.py`: 가벼운 호스트 순위와 현장 PC, 작은 쪽부터 가져가기와 메모리 상한, 워커 수, 직렬 목록·규칙, 재실행에 `-n` 없음, VENV 고정, job 잠금 몫(Linux).
- `test/test_known_failures.py`: xdist 3.8.0 실제 출력(`[gwN]` 진행 줄, 워커 crash, `N workers [0 items]`)에서 실패 id를 한 번씩 읽는다.
- 시험 PC에서의 직렬 대 `-n` 비교는 열린 항목이다.
