## D-553 CD 속도 — fleet·sensing CI 샤딩, CI와 나란히 ARM64 빌드, 끝나지 않는 CD 거래 종료, 시험 PC 둘 동시 사용

**Status:** Accepted (2026-10-09, 사용자 지시 "CI/CD를 줄이고 ADR을 쓰고 처리").

잇는 결정: [D-436](D-436-change-scoped-test-tiers.md)(CI 범위·병렬 matrix) · [D-412](D-412-robots-self-update-from-signed-github-releases-when-idle.md)(로봇 자동 업데이트, 카나리) · [D-225](D-225-update-without-reflash-and-faster-card-writes.md)(페이로드 릴리스) · [D-437](D-437-github-hosted-builds-and-offline-local-signing.md)(빌드는 GitHub 러너, 서명은 운영 PC).

### Context

2026-10-09에 잰 시간(main push → 서명된 롤아웃):

| 단계 | 시간 | 병목 |
|---|---|---|
| CI (`ci.yml`, 실행 37876875654) | 11–12분 | `fleet` 한 잡 578 s. 그다음 `sensing` 381 s, `root-test-3of3` 361 s |
| CI 끝 대기 | CI 전체 | `robot_cd.py`가 CI 성공 뒤에야 빌드를 보냄 |
| ARM64 페이로드 빌드 (`build-native-payload.yml`) | 5–6분 | colcon 245 s, apt 66 s |
| 내려받기·서명·게시 | 약 2분 + 카나리 | |

`RosyRobotCD`(운영 PC 예약 작업)는 2026-10-05 18:06 이후 릴리스 045(sha `5bc111a9`)의 `preparing`에 머물렀다. 준비 거부(`RuntimeError`)가 `audit()` 전에 올라가 감사 기록이 남지 않았고, 단계가 끝나지 않아 5분마다 다시 시도했다. 046–056은 손으로 냈다. 045가 통과했다면 로봇의 056보다 오래된 릴리스를 게시했을 것이다.

### Decision

1. **느린 묶음을 파일 단위로 나눈다.** `tools/harness/affected_tests.py`의 `SUITE_SHARDS = {"fleet": 3, "sensing": 2}`. 루트 샤드(`ROOT_SHARDS`)처럼 정렬한 시험 파일을 `i::n`으로 나누고 이름은 `fleet-1of3`처럼 붙인다. 파일이 샤드 수보다 적으면 나누지 않는다. CI 임계 경로가 약 12분에서 약 6–7분이 된다.
2. **빌드는 CI와 나란히 돈다.** `robot_cd.py`는 main이 움직이면 그 sha의 릴리스 번호를 잡고 서명 없는 ARM64 빌드를 곧바로 보낸다. 서명(`preparing`)은 그 sha의 `ci.yml` push 실행이 성공해야 시작한다. 그 실행이 실패로 끝나면 거래는 `failed`가 되고 빌드는 버려지며 잡아 둔 번호는 빈자리로 남는다. 서명 없는 빌드는 비밀을 보지 않으므로 먼저 돌려도 신뢰 경계가 바뀌지 않는다. 약 6분이 준다.
3. **끝나지 않는 거래를 끝낸다.**
   - 서명 전에 번호가 더 큰 `payload-<date>-NNN` 태그가 있으면 `superseded`로 끝낸다. 오래된 릴리스로 로봇을 되돌리지 않는다.
   - 내려받기·준비 실패는 `prepare_failures`와 `last_error`에 남기고, 세 번째에 `failed`로 끝낸다.
   - tick이 예외로 멈추면 `stopped: <종류>: <내용>`을 감사 기록에 남긴 뒤 멈춘다.
4. **로컬 게이트는 시험 PC 둘을 같이 쓴다.** `tools/remote/remote_pytest.py`는 invocation이 둘 이상이면 닿는 호스트(`ROSY_TEST_HOSTS`, 기본 모델 PC·AI PC)에 `k % n`으로 나눠 동시에 돌린다. 호스트마다 커밋을 한 번 보내고 venv를 한 번 만든다. 결과 코드는 invocation 순서로 돌려준다. 한 호스트가 커밋 전송이나 venv에서 실패하면 그 몫은 성공한 호스트가 이어 돌린다. 둘 다 실패해야 게이트가 실패한다. invocation이 하나면 예전처럼 처음 닿는 호스트 하나만 쓴다. pre-push와 `tools/land.py`가 그대로 혜택을 본다.
5. **쓰지 않는 것.**
   - 우리 PC를 GitHub self-hosted 러너로 붙이지 않는다. 저장소가 공개라 포크 PR이 러너에서 코드를 돌릴 수 있고, 페이로드는 ARM64 빌드라 x86 PC로는 줄지 않는다.
   - 현장 PC(robttt)는 시험 호스트에 넣지 않는다. 라이브 Fleet 스택이 돈다.

### Addendum (2026-10-09, first live run)

- 045가 멈춘 실제 원인은 Windows MAX_PATH였다. 상태 폴더가 95자라 `install/include/...visibility_control.h` 풀기가 260자를 넘어 실패했다. `load_config`는 64자를 넘는 `state_dir`를 거부한다(가장 깊은 페이로드 파일 약 120자 + `<id>/attempt-N/x/.<id>.partial-*` 약 60자). 운영 PC의 상태 폴더는 `X:\DevTemp\robot-cd`로 옮겼다.
- 예약 작업 안에서 Windows OpenSSH `-J`가 상속된 stdin 때문에 두 번째 로봇에서 60 s 동안 멈췄다. `run_ssh`는 `stdin=DEVNULL`로 부른다.
- `install_robot_cd.ps1`은 작업 출력을 `<state_dir>/task-output.log`에 남긴다. 준비 거부 이유는 그 출력에만 찍힌다.

### Addendum 2 (2026-10-10, 손으로 낸 릴리스 072의 시간과 줄일 곳)

사용자 요청 "병렬로 로봇 릴리즈 시간 더 줄일 수 있는 것도 봐 주면 좋겠어"(2026-10-10). 드라이버블 조향을 두 대(9dfk, 8kcn)에서 고치는 동안 한 번 고칠 때마다 릴리스 한 번을 기다린다. 072를 잰 값(UTC, 2026-10-09):

| 단계 | 시각 | 걸린 시간 | 근거 |
|---|---|---|---|
| main push(pre-push 생략) → 빌드 dispatch | 22:06:35 → 22:07:42 | 67 s | `ci` push 실행 생성 시각, 빌드 실행 생성 시각 |
| ARM64 빌드 (`build-native-payload.yml` 37997483677) | 22:07:42 → 22:12:04 | 262 s | 아래 줄 |
| └ apt·ROS 준비 단계 | | 67 s | 단계 시각 |
| └ rosdep 일괄 apt (949개, 523 MB, 받기 21 s) | 22:09:06 → 22:10:57 | 111 s | 실행 로그 |
| └ colcon build | 22:10:58 → 22:11:45 | 47 s | 실행 로그 |
| └ 조립·확인·올리기 | | 17 s | 단계 시각 |
| 빌드 끝 → 준비 시작(사람·에이전트 대기) | 22:12:04 → 약 22:13:48 | 약 104 s | 아티팩트 zip mtime − 받기 7.4 s |
| `prepare_payload_release.py` | → 22:14:26 | 38 s | 받기 7.4, ABI 4.9, 풀기 5.3, 서명 8.3, 묶기 11.7 |
| 8kcn push(로컬 검증·보정 가드 → claim 해제) | 22:14:4x → 22:17:26 | 약 160 s | 로봇 journal |
| └ scp 24 MB | 22:15:09 → 22:16:04 | 55 s (약 0.45 MB/s) | sshd 세션 |
| └ 로봇에서 풀기(`rosy-release-unpack.sh`) | 22:16:15 → 22:17:02 | 47 s | sshd 세션 |
| └ activate·CORE 재시작·readiness | 22:17:03 → 22:17:16 | 13 s | journal |
| 두 로봇 사이 대기 | 22:17:26 → 22:21:17 | 231 s | 로그 mtime·journal |
| 9dfk push | 22:21:17 → 22:22:54 | 97 s (scp 44 s) | journal |
| **합계** | 22:06:35 → 22:22:54 | **약 16분 20초** | |

로봇 쪽 readiness 폴링은 이미 1 s 간격이라 줄일 것이 없다.

**이번에 한 것(신뢰 경계·서명·출처는 그대로):**

1. `deploy/robot/pinky_pro/rosy-release-push-many.ps1`이 로봇마다 바뀌지 않은 `rosy-release-push.ps1`을 동시에 하나씩 띄운다. claim, 보정 가드, readiness, 자동 롤백은 로봇마다 그대로다. 로그는 로봇마다 하나다. 하나라도 실패하면 exit 1이다. `prepare_payload_release.py`는 `--robot`이 둘 이상이면 이 한 줄을 같이 찍는다. 두 로봇 사이 대기(231 s)와 두 번째 push(97 s)가 없어진다. 업로드는 운영 PC 한 회선을 나눠 쓰므로 scp는 조금 길어질 수 있다. 줄어드는 몫은 약 4–5분이다.
2. 스킬 `rosy-release-push`: dispatch 직후 실행 번호를 제목으로 찾고, `gh run watch --interval 10`과 준비를 한 명령줄에 잇는다. push → dispatch(67 s)와 빌드 끝 → 준비(104 s) 대기가 약 10–20 s로 준다.

두 로봇을 같이 올리면 나쁜 릴리스가 두 대를 같이 멈춘다. activate의 readiness 실패 자동 롤백은 로봇마다 그대로 돈다. 주행을 망칠 수 있는 변경은 한 대 먼저(카나리) 올린다.

**사용자 결정이 필요한 것(구현하지 않음):**

| 안 | 줄어드는 시간 | 바뀌는 것 | 필요한 것 |
|---|---|---|---|
| A. 빌드 의존성을 미리 깐 ARM64 빌드 컨테이너(같은 스냅샷·잠금에서 만든 이미지, digest 고정) | 약 150–170 s (apt 67 + rosdep 111 중 대부분) | 빌드 입력에 컨테이너 이미지가 들어온다(D-437·D-482 출처) | 사용자 결정, D-437 addendum, 이미지 빌드·digest 갱신 절차 |
| B. 빌드 쪽 rosdep apt에 `--no-install-recommends` | 추정 40–70 s (949개 중 글꼴·avahi·ghostscript 등 추천 패키지) | 빌드 호스트에 깔리는 집합. 선택 의존성을 `find_package(QUIET)`로 찾는 패키지는 결과물이 달라질 수 있다 | 검증 빌드 1회, `ros-packages.txt`·설치 트리 diff 비교 |
| C. 벤치 반복용으로 브랜치 ref에서 빌드·서명 | pre-push·착지 대기 전부(그날 pre-push는 97커밋 차이로 길었다) | main 아닌 커밋이 서명된다. 지금 `prepare_payload_release.py`는 실행의 브랜치를 보지 않는다 | 사용자 결정, D-225·D-437 addendum(서명 대상 규칙, 릴리스 번호, D-412 자동 업데이트와의 순서) |
| D. `land.py`가 이미 같은 sha로 돌린 affected 시험을 pre-push가 다시 쓰기 | pre-push 대부분 | D-346·D-584 게이트 | 사용자 결정. 그 전에는 origin을 main 가까이 자주 push해서 affected 범위를 작게 둔다 |
| E. 파이썬만 바뀐 경우의 서명된 delta 페이로드(같은 activator) | 빌드 대부분, scp 24 MB → 수백 KB | 새 릴리스 형식(D-225) | 새 ADR. CORE dev overlay는 쓰지 않는다 |
| F. 로봇 풀기 47 s를 한 번의 읽기로(검사와 풀기를 같은 tarfile 순회에서) | 약 15–20 s/로봇 | 보안 검사 스크립트(`rosy-release-unpack.sh`) | 검토와 시험 |
| G. 운영 PC 업로드(0.45 MB/s) 대신 로봇이 GitHub Release에서 받기(D-412 게시 + `rosy-auto-update.service` 즉시 시작) | scp 44–55 s/로봇 | 반복 빌드도 공개 Release로 게시된다 | 사용자 결정 |

같이 본 것: 072의 두 push 모두 `CALIBRATION CHECK UNREACHABLE ... connection was closed` 경고가 났다. 레거시 HTTP 모드라 경고만 하고 진행했다. 보정 가드가 이 두 로봇에서 실제로 돌지 않는다는 뜻이다. 속도와 별개로 확인이 필요하다.

### Consequences

- push → 서명 롤아웃이 약 18–20분에서 약 7–8분(+카나리)이 된다.
- CI가 실패한 sha마다 ARM64 빌드 한 번과 번호 하나가 버려진다(공개 저장소 러너라 비용 없음). CI 실패는 그 sha에 대해 끝이다. 같은 sha의 CI를 다시 돌려 초록이 되어도 그 sha로는 다시 릴리스하지 않고, 다음 main 커밋을 기다린다. 서명이 끝난 `publishing` 단계는 CI 재실행 결과로 끝내지 않는다(카나리 감시를 버리지 않는다).
- 설치된 서명 스냅샷은 고정이라, 이 변경은 착지 뒤 `install_robot_cd.ps1`로 새 스냅샷을 설치해야 동작한다. 새 스냅샷의 첫 tick이 멈춘 045를 `superseded`로 끝낸다.
- 시험 PC 둘을 동시에 쓰면 AI PC가 다른 일로 바쁠 때 그쪽 invocation이 느려질 수 있다. `ROSY_TEST_HOSTS`로 한 호스트만 줄 수 있다.
- 시험: `test/test_affected_tests.py`(샤드), `test/test_robot_cd.py`(CI와 나란한 빌드, CI 실패·superseded·세 번 실패 종료), `test/test_remote_pytest.py`(호스트 분배·순서).
