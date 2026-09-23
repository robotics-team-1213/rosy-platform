## D-179 벤치 CORE 수정은 설치 트리 위의 읽기 전용 바인드이고, 그 장치는 릴리스로 세지 않는다

**Status:** Accepted (2026-09-23). 루프의 선택이다. 스크립트·readback·drop-in은
[실행 계획](../plans/2026-09-23-core-dev-overlay.md)의 과제가 착지하기 전에 저장소에 없다.
ARTIFACT와 DEVICE는 이 ADR로 오르지 않는다.

**Context:** 벤치에서 CORE를 고치는 현재 경로는 `deploy-from-windows.ps1`다. 이 스크립트는
커밋된 `HEAD`만 `git archive`로 묶어 `scp`하고, 로봇에서 `install-pi.sh`를 처음부터 돌린다.
`-AllowDirty`도 작업 트리의 수정은 올리지 않는다. 설치기는 apt와 Docker를 다시 확인하고
`/opt/rosy`를 `rsync -a --delete`한 뒤 `docker compose build` 안에서 `colcon build`를 한다.
파이썬 한 줄이 이미지에 `COPY`되어 들어가므로, `/opt/rosy`를 고쳐도 컨테이너를 다시 만들기
전에는 실행 중인 코드가 바뀌지 않는다. 같은 rsync는 과거에 기기 `.env`를 지운 적이 있다.

제품 경로는 이 설치기가 아니다. D-161은 Ubuntu 24.04 arm64와 native ROS 2 Jazzy를
`/opt/rosy/current`의 서명 페이로드로 실행하고, D-36과
[릴리스 전달 설계](../plans/2026-09-08-release-delivery-design.md)는 로봇이 `git pull`로
빌드하지 않으며 GitHub에서 받은 번들을 곧 설치하지 않는다고 정했다. 다운로드와 활성화는
 separado, 실패하면 `previous`로 돌아온다. 모터는 그때 자동으로 재개되지 않는다.

빠른 수정과 릴리스를 한 통로로 두면 둘 다 약해진다. 매번 재설치하거나, 서명된 `current`를
현장 트리로 바꿔 장치가 어느 릴리스인지 알 수 없게 된다.

**Decision:**

1. **세 속도는 갈라진 채로 둔다.** 고치는 동안은 이 ADR의 오버레이다. 커밋을 벤치의
   설치 기준으로 다시 깔 때는 기존 `deploy-from-windows.ps1`다. 다른 기기로 넘길 때는
   서명된 GitHub Release다. 뒤의 둘은 이 ADR이 수정하지 않는다.

2. **오버레이의 집은 `/var/lib/rosy-dev`다.** `/opt/rosy`와 `/opt/rosy/current`는
   교체하지 않는다. 허용 목록은 다섯 패키지 디렉터리
   `core`, `core_common`, `core_events`, `core_features`, `core_api_web`과
   share 파일 `web_common/tokens.css`, `web_common/core_ui_logic.js`뿐이다.
   대시보드 HTML·JS·CSS는 `core_api_web`의 package data라 패키지 바인드에 들어간다.
   토큰과 공용 UI 스크립트는 ament share에서 서빙되므로 그 두 파일만 따로 얹는다.
   `.srv`, 새 의존, 엔트리포인트, apt, launch는 재빌드 또는 커밋 재설치 쪽이다.

3. **실행 코드는 읽기 전용 바인드로 고른다.** 적용 직전에 떠 있는 코어에서
   `core.__file__`과 `get_package_share_directory("web_common")`을 읽는다.
   패키지 경로가 `/opt/rosy_ws/install` 또는 `/opt/rosy/current/install` 안의
   site-packages일 때만 그 디렉터리 위에 오버레이를 얹는다. `PYTHONPATH` 선행은
   채택하지 않는다. `setup.bash`가 설치 트리를 다시 앞에 두면 프로세스는 이미지
   코드를 실행하고, `__file__` 경로는 바인드 전후가 같아서 그 사실을 숨긴다.
   성공 판정은 서비스 안에서 읽은 `core/__init__.py`의 SHA-256이
   `/var/lib/rosy-dev/python/core/__init__.py`와 같은 것이다.

4. **제품 유닛과 제품 compose는 오버레이를 자동으로 읽지 않는다.**
   `compose.override.yaml`이라는 이름은 만들지 않는다. `runtime-mode.sh`는 개발
   compose 파일을 받지 않는다. 네이티브 drop-in은
   `/etc/systemd/system/rosy-core.service.d/dev-overlay.conf`에만 쓰고,
   저장소의 `rosy-core.service`에는 `BindReadOnlyPaths`를 넣지 않는다.
   바인드는 서비스 마운트 안에서만 보이므로 `ProtectSystem=strict`인 채 `/opt`에
   쓰지 않는다. 적용은 `--no-build --no-deps`로 `rosy-core`만 재시작하고,
   motor 또는 hardware가 떠 있으면 거절한다.

5. **오버레이가 남아 있으면 그 장치는 릴리스가 아니다.** 실행 중인 코어의
   `ROSY_DEV_OVERLAY=1`, `/etc/rosy/dev-overlay.json`, 또는 위 drop-in 중 하나면
   `device_readback`은 `dev_overlay=true`와 `device_runtime=HOLD`를 낸다.
   환경 변수 없이 마커나 drop-in만 있으면 `dev_overlay_reason=stale`로 같은 HOLD다.
   신원·activation·digest·health 검사는 유지하고, 오버레이 조건이 참이면 GO가 되지
   않는다. 마커에는 토큰, 비밀번호, 환경 파일 본문을 넣지 않는다.
   동기화는 `.env`, `/etc/rosy/rosy.yaml`, `/var/lib/rosy`, 로봇 번호를 쓰지 않는다.

6. **로봇 쪽 판단은 Python으로 둔다.** 경로 탈출, 링크, 목록 밖 멤버, 바인드 목적지,
   해시 비교, 마커 기록은 `deploy/robot/dev/core_dev_overlay.py`가 한다. Windows
   pytest가 bash 없이 그 판단을 돌린다. PowerShell은 허용 목록만 묶어 SSH로 그
   모듈을 호출한다. 호스트 키 확인은 `deploy-from-windows.ps1`과 같이 끄지 않는다.

**Alternatives:**

- `install-pi.sh`에서 apt와 이미지 빌드만 빼기: 한 줄 수정이 여전히 전체 트리 rsync와
  설치기 실패 경로를 탄다. `.env`를 지운 경로와 같다.
- 로봇에서 `git pull` 후 colcon: D-36이 이미 빼 두었다. 실행 중인 리비전과 롤백이
  불명확해진다.
- `PYTHONPATH`만 앞에 두기: setup이 설치 트리를 다시 앞에 놓으면 오버레이가 조용히
  무시된다.
- `/opt/rosy/current`를 개발 트리로 바꾸기: 서명 digest와 실행 코드가 어긋난 채
  readback이 GO가 될 수 있다.

**Consequences:** 벤치 한 대는 오버레이 동안 릴리스 증거가 아니다. 지우기 명령이
마커, drop-in, 개발 compose를 제거한 뒤에야 readback의 오버레이 조건이 거짓이 된다.
모터는 지우기에서도 자동으로 켜지지 않는다. 해시가 다르면 적용은 실패로 끝나고
마커는 남아 HOLD를 유지한다. 구현 순서는 실행 계획이 정한다.

**구현·처리 계획:**
[설계](../plans/2026-09-23-core-dev-overlay-design.md) ·
[실행 계획](../plans/2026-09-23-core-dev-overlay.md).

**Validation:** 호스트 pytest가 허용 목록, 경로 거절, 해시 불일치 실패, readback HOLD,
제품 유닛에 drop-in이 없음을 본다. 로봇에서 한 줄이 실제로 바뀌는 증거는 그 시험의
범위 밖이며 DEVICE를 올리지 않는다.
