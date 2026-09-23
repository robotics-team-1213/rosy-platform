---
module: deploy
---

# CORE 개발 오버레이 실행 계획 (D-179)

설계: [2026-09-23-core-dev-overlay-design.md](2026-09-23-core-dev-overlay-design.md).
결정: [D-179](../adr/D-179-bench-core-readonly-overlay.md).

시험이 먼저다. 각 과제는 적색 시험을 넣고, 그 시험이 요구하는 코드만 넣는다.
로봇, 제품 이미지, `install-pi.sh`, GitHub 업데이터, `rosy-core.service` 본문,
`runtime-mode.sh`의 기동 파일 목록은 이 계획에서 바꾸지 않는다.

## 반복할 때

아래 세 문장은 Task 2와 Task 5의 시험에 들어간다.

첫 적용은 바인드를 붙이려고 컨테이너를 한 번 다시 만든다. 바인드가 이미 있으면
허용된 파일만 복사하고 `rosy-core`만 재시작한다. 이미 import된 파이썬을 바꾸려면
그 재시작이 필요하다. 이 반복에는 apt, 이미지 빌드, `/opt/rosy` 전체 rsync가 없다.
성공은 `core/__init__.py` 해시 한 번이다. `install-pi.sh`의 90초 헬스와
`--require-internet`은 이 경로가 호출하지 않는다.

재부팅이나 `rosy-runtime` 재시작은 `runtime-mode.sh up`만 실행한다. 그 스크립트는
개발 compose를 읽지 않으므로 프로세스는 이미지 코드로 돌아간다. 마커는 남고
readback은 HOLD다. 수정은 `sync-core-dev.ps1`을 다시 실행하면 돌아온다.
이 동작은 D-179 결정 4의 결과다.

개발 compose 조각에는 `name` 키를 넣지 않는다. 프로젝트는 `compose.yaml`의
`rosy-runtime`이고, 그 프로젝트에서 `rosy-core`만 올린다. 조각이 다른 이름을
주면 최종 `cmd_vel`을 내는 코어가 둘이 된다.

호스트에서 보는 명령:

```text
python -m pytest test/test_core_dev_sync.py test/test_device_readback.py -q
```

## Task 1: 허용 목록과 풀기 거절

**Files:** `deploy/robot/dev/core_dev_overlay.py`, `test/test_core_dev_sync.py`

1. 실패하는 시험: 다섯 패키지와 `tokens.css`, `core_ui_logic.js`만 아카이브 멤버로
   남는다. `__pycache__`, `.pyc`, `.env`, `rosy.yaml`, `interfaces/*.srv`,
   링크, `..`, 절대 경로, 목록 밖 파일은 목적지에 파일을 만들기 전에 거절한다.
2. `stage_overlay(archive, dest)`가 `/var/lib/rosy-dev` 아래만 쓴다.
   dest가 `/opt/rosy`이거나 그 안이면 거절한다.
3. 마커 JSON 스키마 1은 `backend`, `git_revision`, `dirty`, `synced_at`,
   `packages`만 가진다. 토큰 비슷한 키는 거절한다.

## Task 2: 바인드 목적지와 해시 성공

**Files:** `deploy/robot/dev/core_dev_overlay.py`, `test/test_core_dev_sync.py`

1. 실패하는 시험: 발견 함수는 `core.__file__` 부모와 web_common share 경로를
   입력으로 받는다. 패키지 경로가 `/opt/rosy_ws/install/.../site-packages/<name>`
   또는 `/opt/rosy/current/install/.../site-packages/<name>`일 때만 바인드 쌍을
   만든다. `/tmp`, 홈, `/opt/rosy` 루트, 다른 패키지 경로는 거절한다.
2. 성공 함수는 두 바이트 열의 SHA-256이 같을 때만 참이다. 경로 문자열이 같다는
   이유는 성공이 아니다.
3. 만든 compose 조각은 `compose.override.yaml`이라는 이름을 쓰지 않고,
   `--no-build`와 `--no-deps`와 `rosy-core`만 재시작하는 인자만 낸다.
   motor 또는 hardware가 실행 중이라는 probe가 참이면 그 인자를 내기 전에 거절한다.
4. `runtime-mode.sh` 소스에 `core-dev` 또는 `compose.override.yaml`이 없음을
   같은 시험 파일이 읽어서 확인한다.
5. 렌더한 compose 조각에는 `name` 키가 없다. 실행 인자의 프로젝트는
   `rosy-runtime`이고, `-f`는 제품 `compose.yaml`과
   `/var/lib/rosy-dev/compose.dev.yaml`이며, 서비스는 `rosy-core`뿐이다.
6. 바인드가 이미 붙어 있으면 렌더는 파일 복사 뒤 `rosy-core` 재시작만 낸다.
   컨테이너를 다시 만드는 인자는 바인드가 없을 때만 낸다.
7. 성공 판정 명령에 `verify-pi.sh`, `--require-internet`, 90초 대기가 없다.
   해시는 `core/__init__.py` 한 파일이다.

## Task 3: readback HOLD

**Files:** `deploy/robot/verify/device_readback.py`, `test/test_device_readback.py`

1. 실패하는 시험: 신원·digest·health가 맞아도 다음 중 하나면
   `device_runtime`은 `HOLD`이고 `dev_overlay`는 true다.
   코어 환경 `ROSY_DEV_OVERLAY=1`, 마커 파일, drop-in 경로.
2. 환경 변수가 없고 마커 또는 drop-in만 있으면 `dev_overlay_reason`은 `stale`이다.
3. 셋 다 없으면 기존 GO 조건은 그대로다. 오버레이 필드는 false다.

## Task 4: 네이티브 drop-in은 호스트 상태

**Files:** `deploy/robot/dev/core_dev_overlay.py`, `test/test_core_dev_sync.py`,
`test/test_native_systemd_contract.py`

1. 실패하는 시험: `render_native_dropin`은 Task 2의 바인드 쌍으로
   `BindReadOnlyPaths=` 줄만 만든다. `ExecStart`와 `WorkingDirectory`를
   바꾸지 않는다.
2. 저장소의 `deploy/robot/native/rosy-core.service`에는 `rosy-dev`와
   `BindReadOnlyPaths`가 없다. 기존 네이티브 유닛 계약 시험이 계속 통과한다.
3. `clear_overlay`는 마커, drop-in, `/var/lib/rosy-dev/compose.dev.yaml`만
   지운다. `/opt/rosy`, `.env`, `rosy.yaml`은 남긴다.

## Task 5: Windows 호출부

**Files:** `deploy/robot/dev/sync-core-dev.ps1`, `deploy/robot/dev/apply-core-dev.sh`,
`deploy/robot/dev/clear-core-dev.sh`, `test/test_core_dev_sync.py`

1. 스크립트 본문 시험: `sync-core-dev.ps1`은 `-PiHost`, `-PiUser`,
   `-Backend`만 받고 `RobotNumber`를 받지 않는다. `install-pi.sh`, `apt-get`,
   `docker compose build`, `reboot`, `git pull`, `StrictHostKeyChecking=no`,
   `rsync --delete`가 없다.
2. `apply-core-dev.sh`와 `clear-core-dev.sh`는 `python3 -B`로
   `core_dev_overlay.py`만 호출한다. `-Backend native` 분기는 Task 4의
   drop-in 렌더를 호출하고, docker 분기는 Task 2의 compose 인자를 호출한다.
3. 이 과제가 끝나도 로봇 실행 증거는 없다. DEVICE는 HOLD다.
4. 적용 출력에는 다음 문장이 있다. 재부팅과 `rosy-runtime` 재시작은 이미지
   코드로 돌아가고 마커 HOLD가 남으니, 같은 동기화를 다시 실행한다.
   스크립트는 `reboot`와 `systemctl restart rosy-runtime`을 호출하지 않는다.

## 착지 후 확인

```text
python -m pytest test/test_core_dev_sync.py test/test_device_readback.py test/test_native_systemd_contract.py -q
python tools/harness/rosy_harness.py lint
```
