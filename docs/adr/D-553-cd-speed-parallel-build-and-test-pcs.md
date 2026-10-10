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

### Addendum 3 (2026-10-10, 사용자 승인: 델타 페이로드·pre-push 재사용·빌더 이미지·브랜치 빌드)

사용자가 2026-10-10에 Addendum 2 표의 C, D, E와 빌더 컨테이너(A)를 승인했다(AskUserQuestion, 네 항목 모두 승인). 조정자가 전한 조건: 모든 페이로드는 같은 키로 서명한다. activator·롤백·CORE readiness는 그대로다. CORE dev overlay는 쓰지 않는다. 브랜치 빌드는 서명된 릴리스에 출처 ref와 sha를 남기고, D-412 자동 업데이트 채널은 main만 받는다. 브랜치 `feat/release-speed`.

1. **델타 페이로드 (E).** `tools/release/make_delta_release.py`.
   - 입력은 이 PC가 이미 준비한 서명된 base 릴리스(`<out>/x/<base>`, 그 tarball)와 커밋 하나다. 로봇은 그 base를 가지고 있어야 한다.
   - 도구는 새 릴리스 전체를 로컬에서 다시 만든다. base 파일에 바뀐 파일을 얹고, 새 `install/.rosy-release`, `source-revision.txt`, `source-ref.txt`를 쓴다. 그 위에 `manifest.json`과 `SHA256SUMS`를 전부 다시 쓰고, `sign_image_release.py`로 같은 키로 서명하고, 전체 트리를 `verify_release_files`로 확인한다. GitHub 빌드와 같은 형식이다. `manifest.json` 키는 바꾸지 않는다(로봇의 옛 activator가 새 키를 거부한다).
   - tarball에는 새 메타데이터, 바뀐 파일, `.rosy-delta-base`(base id, base `SHA256SUMS`의 sha256)만 들어간다.
   - 바뀐 소스 파일은 base 페이로드에서 이름이 같고 base 시점 내용이 바이트 단위로 같은 파일에만 대응한다(그대로 복사된 Python 모듈, launch·config·data, native-runtime 스크립트). 같은 이름·내용의 소스가 둘 이상이면(빈 `__init__.py`) 경로 끝 두 부분까지 같아야 한다.
   - 거부하고 전체 빌드를 요구하는 것: C/C++ 소스·헤더·인터페이스·`CMakeLists.txt`·`package.xml`·`setup.py`·`setup.cfg`, 추가·삭제·이름 바뀐 배포 파일, 대응하는 복사본이 없는 배포 파일. `docs/`, `test(s)/`, `tools/`, `.github/`, `.claude/`, `*.md`와 `--not-shipped <prefix>`로 적은 경로는 무시하고 출력에 남긴다.
   - checked-hash `.pyc`는 그대로 둔다. Python이 소스 해시를 확인하고 바뀐 모듈만 메모리에서 다시 컴파일한다. 운영 PC는 Python 3.14라 로봇(3.12)용 pyc를 만들 수 없다.
   - 로봇 쪽: `rosy-release-unpack.sh`(push가 매번 운영 PC에서 복사해 간다)가 표지를 읽는다. base가 없거나 base `SHA256SUMS`의 해시가 다르면 `DELTA_BASE_MISSING`/`DELTA_BASE_MISMATCH`로 멈춘다. 맞으면 base를 새 임시 폴더로 `cp -a` 하고(하드링크 아님: base는 롤백 대상이다) 델타를 얹은 뒤 표지를 지운다. 활성화는 지금처럼 `native_release.py verify()`가 새 서명으로 전체 트리를 검사한다. 빠진 파일·남는 파일·다른 해시는 모두 거부된다.
   - push 사전 검사(`rosy-release-push.ps1`)는 델타면 `signing.verify_delta_files`로 서명과 실린 파일의 해시만 본다. 나머지는 로봇이 검사한다.
   - `publish_payload_release.py`는 델타를 거부한다. 자동 업데이트 로봇은 base를 갖고 있다는 보장이 없다.
   - 잰 값: 인지 코드 한 파일을 바꾼 커밋과 base 074. tarball 277 KB(전체 24 MB), 만들고 서명하는 데 15 s. 로컬에서 로봇과 같은 재구성(base 복사 + 델타 + 표지 삭제)을 하면 `verify_release_files` 거부 0건이었다. 실제 로봇 push는 하지 않았다.
2. **pre-push가 land.py 결과를 다시 쓴다 (D).**
   - `tools/land.py`는 main을 fast-forward 한 뒤 `<git-common-dir>/rosy-land/<sha>.json`을 남긴다. 내용은 착지한 커밋, 시험할 때의 main(base), 통과한 pytest invocation이다.
   - 이 기록은 `--tests auto`일 때만 남긴다. records-only 지름길로 모듈 시험을 건너뛴 회차에서는 남기지 않는다.
   - `tools/hooks/land_record.py owed`는 push할 커밋에서 기록 → base → 기록을 따라가며 origin/main까지 끊기지 않는지 본다.
   - 끊기지 않으면 pre-push는 affected 계층을 건너뛰고, 어느 기록도 돌리지 않은 fast suite만 돌린다. lint, 생성 기록, Safety-Review 경고는 그대로 돈다.
   - 기록이 하나라도 없으면(손으로 착지, `--tests none`) 지금과 똑같이 돈다.
   - 착지 때 known_failures 비교를 통과한 결과를 쓰므로, main에 이미 있는 실패가 push를 막지 않는다.
3. **빌더 이미지 (A).**
   - `build-payload-builder.yml`이 `ghcr.io/<owner>/rosy-payload-builder:<sha>`를 만든다. 입력: digest로 고정한 Ubuntu 24.04, 워크플로 단계에서 그대로 옮긴 `install-ros-build-prereqs.sh`(체크섬 고정 apt source, D-482 스냅샷, 지문 고정 키), colcon root에 대해 rosdep이 푸는 apt 패키지.
   - `build-native-payload.yml`의 job은 `builder_image` 입력(기본값은 고정 digest)의 컨테이너에서 돈다. digest가 아닌 이미지는 첫 단계에서 멈춘다.
   - `build-native-payload.sh`는 여전히 같은 스냅샷에 rosdep install을 돌린다. 그래서 이미지는 새 출처가 아니라 캐시다. 이미지 뒤에 추가된 의존성은 빌드 때 설치된다.
   - 권한은 페이로드 job `packages: read`, 빌더 job `packages: write`이고 job 토큰만 쓴다. 서명은 여전히 운영 PC에서만 한다(D-437).
   - 아직 재지 못했다. 첫 빌더 실행에는 이 브랜치를 origin에 올려야 한다. 그런데 pre-push가 main(`c2a0a5d83`)에 이미 있는 실패 4건으로 막혔다. 기본 digest는 `PENDING`이고, 첫 실행 뒤 그 digest로 바꾸는 커밋이 필요하다. 그 전에는 이 워크플로를 main에 올리지 않는다.
   - 바뀌는 것: `deb-packages.txt`는 GitHub 러너 호스트 전체가 아니라 컨테이너의 패키지 목록이 된다. `ros-packages.txt`(ABI 비교 대상)는 같은 스냅샷이라 같다.
4. **브랜치 빌드 (C).**
   - `build-native-payload.yml`은 어느 브랜치에서든 dispatch할 수 있다. dispatch한 브랜치 이름을 `source-ref.txt`로 페이로드에 쓰고, manifest와 서명이 그 파일을 덮는다. sha는 `source-revision.txt`에 그대로 있다.
   - `prepare_payload_release.py`는 ref를 찍고 브랜치 빌드를 "수동 push 전용"으로 표시한다. `publish_payload_release.py`는 `source-ref.txt`가 `main`이 아니면 거부한다. `robot_cd.py`는 main만 빌드한다.
   - 브랜치 빌드를 push한 로봇은 다음 main 게시가 오면 자동 업데이트로 바뀐다. 벤치 동안에는 `rosy-update-hold.ps1 -Hold`를 건다.
   - 수동 릴리스 번호(full·델타·브랜치)는 `robot_cd`의 `payload-reserved-*` 태그로 잡히지 않는다. 같은 번호를 다시 쓰지 않도록 로봇의 `/opt/rosy/releases`와 태그를 보고 고른다(지금과 같다).
5. **보정 가드.**
   - 두 로봇 모두 CORE API가 8080에서 HTTPS라, 레거시 HTTP 가드는 연결이 닫혀 `UNREACHABLE` 경고만 내고 있었다.
   - 이제 가드는 같은 strict-host-key ssh(호스트명이 증명되면 HostKeyAlias)로 로봇의 `ROSY_API_TLS_HOST`와 공개 CA를 읽고, `calibration_tls_read.py`(CA와 정확한 호스트명 검증)로 한 번 묻는다. 실패하면 이전 경고 그대로다.
   - 8kcn·9dfk에서 읽기만 해서 확인했다. 둘 다 "no active calibration session", 각 3 s.

### Addendum 4 (2026-10-10, 델타 한 줄 배포: `ship.py`, 하드링크 풀기, 카메라만 재시작)

사용자(2026-10-10): "배포 과정 병렬로 해서 개선하고 그러고 속도 향상시켜." 조향 세션이 한 시간에 여러 번 델타를 두 로봇(9dfk 192.168.1.201, 8kcn 192.168.1.202)에 낸다. 그 주행을 멈추지 않고 그 시간을 줄인다. 서명, 로봇의 전체 트리 검증, 실패 시 롤백, CORE가 바뀔 때의 CORE readiness는 그대로다. 브랜치 `feat/fast-ship`.

1. **잰 값 (로그에서, 로봇에 push 하지 않음).** 델타 078–094의 tarball 생성 시각부터 push 로그 마지막 쓰기까지: 9dfk 42–88 s(중앙 약 54 s), 8kcn 71–134 s(중앙 약 80 s). 로그에는 단계별 시각이 없어 단계는 다음으로 나눴다.
   - ssh·scp 한 번에 2.2–3.0 s(이 PC→두 로봇, 읽기 전용으로 잼). push 한 번에 claim, mkdir, scp 둘, chmod, unpack, activate, CORE 확인, readiness, image-layer dry-run·apply, claim 해제로 13번, 보정 가드 ssh 2번 → 연결만 약 35–40 s.
   - unpack의 base `cp -a`: 92 MB, 파일 3170개를 SD 카드에 복사(8kcn이 매번 25 s쯤 더 걸린다).
   - activate: 전체 트리 검증 + runtime 전체 stop/start + CORE readiness(약 13 s). 그 뒤 image-layer 동기화 두 번(바뀐 것 0개).
   - 델타 만들기: 지금 이 PC에서 재면 base 복사 6 s, 봉인 46 s, 서명 50 s, 새 트리 검증 19 s(새로 쓴 3170개 파일을 매번 다시 읽는다). 조용할 때 약 15 s.
2. **`tools/release/ship.py --base <id> --robots 9dfk,8kcn`.** 보정 가드를 로봇마다 먼저 띄우고, `payload-reserved-<id>` 태그로 번호를 잡고(`robot_cd.py` 규칙, 422면 다음 번호), 델타를 만들어 서명하고, 로봇마다 ssh 한 세션으로 동시에 보내고, 요약 한 줄을 찍는다. 로그는 `X:\DevTemp\rosy-release-<id>\ship-<robot>.txt`, 로봇 쪽 단계는 `PHASE <이름> <초>`로 남는다. `--dry-run`은 만들기만 하고 계획을 찍는다. 전체 빌드와 `-Rollback`은 그대로 `rosy-release-push(-many).ps1`이다. 로봇별 설정 overlay는 넣지 않았다. 로봇별 설정은 `/etc/rosy/`(예: `line_observer_overrides`)에 있고 릴리스가 덮지 않는다.
3. **델타는 base의 서명된 메타데이터로 만든다.** `make_delta_release.py`는 base의 `SHA256SUMS` 서명을 확인하고, 바뀌지 않은 파일의 해시는 그 서명된 목록에서 가져온다. 로컬에 base 전체를 복사하거나 다시 해시하지 않는다. 바뀐 파일과 생성 파일 셋, 새 `manifest.json`·`SHA256SUMS`·서명만 쓴다. 릴리스 094를 같은 입력으로 다시 만들면 `SHA256SUMS`와 `manifest.json`이 바이트 단위로 같았다. `x/<id>`에는 그 파일들과 다음 델타용 `.modes.json`(파일 모드)만 남는다. 옛 델타 base는 tarball의 `.rosy-delta-base`를 따라 전체 tarball까지 모드를 모은다. 잰 값 3.2 s.
4. **로봇에서 base를 하드링크로 편다 (Addendum 3의 `cp -a`를 바꿈).** `rosy-release-unpack.sh`가 `cp -al`을 쓴다. Addendum 3은 base가 롤백 대상이라 하드링크를 피했다. 바꾼 근거: 릴리스 폴더는 제자리에서 쓰지 않는다. GNU tar는 델타 파일을 풀기 전에 그 경로를 unlink 하므로 base의 inode는 그대로다(`test_a_delta_is_laid_over_a_copy_of_its_base`가 base 내용을 확인). 이후 chown/chmod는 base에서 이미 맞춘 값이라 바뀌는 것이 없다. 누가 한쪽을 제자리에서 고치면 양쪽이 같이 바뀌지만, 활성화·롤백 때 `native_release.py verify()`가 전체를 다시 해시하므로 조용히 넘어가지 않고 거부된다.
5. **카메라만 재시작 (활성화 변경).** `native_release.py activate --release-id <id> --restart-unit rosy-camera.service`.
   - 링크 교체, 저널, 실패 시 롤백은 전체 활성화와 같다. 차이는 runtime 전체 대신 `rosy-camera.service`만 stop/start 한다는 것뿐이다. start 뒤 3 s 지나 `is-active`가 아니면 링크를 되돌리고 옛 카메라를 다시 띄운다. 허용 유닛은 `rosy-camera.service` 하나다.
   - `ship.py`가 이 모드를 고르는 조건: 바뀐 페이로드 파일이 모두 `control/sensing/perception/` 아래이거나 `camera_preview.launch.py`가 띄우는 노드 모듈(`line_observer_node` 등 7개)이다. CORE는 `control`을 import 하지 않고, rosy-io의 `ir_adc_node`는 `perception/`을 import 하지 않는다(`test/test_ship.py`가 정적 import로 고정).
   - 로봇 쪽(`tools/release/ship_remote.sh`, `tools/` 아래라 델타의 배포 파일로 세지 않는다)은 다음이면 전체 활성화로 돌아간다: 설치된 activator가 이 옵션을 모를 때, 현재 릴리스가 델타의 base가 아닐 때, CORE가 안 돌 때, `rosy-navigation`(control 노드를 띄운다)이 돌 때.
   - 그래서 CORE는 base 이전 릴리스 폴더를 작업 폴더로 둔 채 계속 돈다. 그 폴더의 CORE 코드는 새 릴리스와 바이트 단위로 같다(base가 현재 릴리스일 때만 허용하므로 연쇄해도 같다). CORE는 import를 `/opt/rosy/current` 경로로 하므로, 자동 업데이트의 정리가 옛 폴더를 지워도 작업 폴더만 사라진다. CORE가 다음에 재시작하면 현재 릴리스로 뜬다. CORE가 알리는 릴리스 번호는 그 사이 이전 값일 수 있다.
   - 이 activator는 image layer라, 이 변경이 든 릴리스가 한 번 동기화된 뒤부터 쓰인다. 그 전에는 위 규칙대로 전체 활성화가 된다.
6. **image-layer 동기화는 델타가 `deploy/robot/native/` 파일을 바꿀 때만 돈다.** 동기화는 릴리스 안의 그 폴더를 기준으로 하므로, 그 폴더가 base와 같으면 할 일이 없다.
7. **기대 시간.** 카메라 모드: 번호·가드 약 3–5 s(동시), 만들기 3–5 s, 로봇마다 ssh 한 번 약 3 s + 풀기 1–2 s + 전체 검증 2–4 s + 카메라 재시작과 3 s 확인 약 5 s → 한 번에 약 20–25 s, 두 로봇 동시. 전체 모드는 CORE stop/start와 readiness로 15–20 s를 더해 약 35–45 s. 첫 실제 사용은 사용자가 조향 세션의 주행 틈에 정한다.
8. **시험.** `test/test_ship.py`(재시작 범위, import 고정, 임시 root에서 실제 unpack·verify·링크 교체: 카메라 모드, 카메라 실패 롤백, 전체 모드, base가 현재가 아닐 때 전체로 돌아감), `test/test_native_release_activation.py`(카메라만 활성화·롤백·허용 유닛), `test/test_make_delta_release.py`(모드 연쇄), `test/test_release_unpack_helper.py`(하드링크 뒤 base 유지).

### Consequences

- push → 서명 롤아웃이 약 18–20분에서 약 7–8분(+카나리)이 된다.
- CI가 실패한 sha마다 ARM64 빌드 한 번과 번호 하나가 버려진다(공개 저장소 러너라 비용 없음). CI 실패는 그 sha에 대해 끝이다. 같은 sha의 CI를 다시 돌려 초록이 되어도 그 sha로는 다시 릴리스하지 않고, 다음 main 커밋을 기다린다. 서명이 끝난 `publishing` 단계는 CI 재실행 결과로 끝내지 않는다(카나리 감시를 버리지 않는다).
- 설치된 서명 스냅샷은 고정이라, 이 변경은 착지 뒤 `install_robot_cd.ps1`로 새 스냅샷을 설치해야 동작한다. 새 스냅샷의 첫 tick이 멈춘 045를 `superseded`로 끝낸다.
- 시험 PC 둘을 동시에 쓰면 AI PC가 다른 일로 바쁠 때 그쪽 invocation이 느려질 수 있다. `ROSY_TEST_HOSTS`로 한 호스트만 줄 수 있다.
- 시험: `test/test_affected_tests.py`(샤드), `test/test_robot_cd.py`(CI와 나란한 빌드, CI 실패·superseded·세 번 실패 종료), `test/test_remote_pytest.py`(호스트 분배·순서).
