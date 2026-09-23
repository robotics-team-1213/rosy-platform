---
module: deploy
---

# CORE 개발 오버레이 설계

작성일: 2026-09-23

상태: D-179 Accepted. 정책은 이 문서와 [실행 계획](2026-09-23-core-dev-overlay.md)이다. 스크립트와 readback 변경은 계획의 과제가 착지하기 전에 저장소에 없다.

관련: [D-179](../adr/D-179-bench-core-readonly-overlay.md) · [실행 계획](2026-09-23-core-dev-overlay.md) · [릴리스 전달](2026-09-08-release-delivery-design.md) · [Ubuntu native 런타임](2026-09-21-ubuntu-native-ros-runtime-design.md) (D-161) · [Wi-Fi 배포](2026-09-01-raspberry-pi-wifi-deployment-design.md) · `deploy/robot/deploy-from-windows.ps1` · `deploy/robot/verify/device_readback.py`

## 1. 목표

이미 떠 있는 벤치 로봇의 CORE 파이썬을, 설치기를 다시 돌리지 않고 고친다. 노트북에서 호스트 pytest를 본 뒤 허용된 패키지만 보내고 코어만 재시작한다. 그 로봇은 서명된 릴리스로 보이지 않는다.

세 속도는 그대로 갈라져 있다.

| 속도 | 하는 일 | 기존 도구 |
|---|---|---|
| 고치는 동안 | 허용 패키지 동기화, 코어만 재시작 | 이 설계 |
| 커밋을 벤치 기준으로 다시 깔 때 | `HEAD` 아카이브 전체 설치 | `deploy-from-windows.ps1` |
| 다른 기기에 넘길 때 | 서명된 `rosy-release-<id>.tar.zst` | GitHub Releases, 확인과 설치는 분리 |

## 2. 벤치에 남는 것

오버레이는 `/opt/rosy` 밖이다. `install-pi.sh`의 `rsync --delete`는 이 디렉터리를 지우지 못한다.

```text
/var/lib/rosy-dev/python/
  core/  core_common/  core_events/  core_features/  core_api_web/
/var/lib/rosy-dev/compose.dev.yaml
/etc/rosy/dev-overlay.json          root:rosy 0640, 비밀 없음
```

`compose.dev.yaml`은 `/opt/rosy/deploy/robot/`에 두지 않는다. 그 디렉터리의 `compose.override.yaml`은 `docker compose`가 자동으로 읽으므로, 그 이름은 저장소에도 로봇에도 만들지 않는다. `runtime-mode.sh`는 두 번째 compose 파일을 받지 않는다. 제품 기동은 이미지에 구워진 코드만 실행한다.

Docker 벤치의 기동은 이미 있는 compose 파일에 개발 파일만 더한다.

```text
docker compose --env-file /opt/rosy/deploy/robot/.env \
  -f /opt/rosy/deploy/robot/compose.yaml \
  -f /var/lib/rosy-dev/compose.dev.yaml \
  up -d --no-build --no-deps rosy-core
```

개발 파일이 더하는 것은 읽기 전용 바인드와 `ROSY_DEV_OVERLAY=1`, `PYTHONDONTWRITEBYTECODE=1`뿐이다. 바인드 목적지는 적용 직전에 떠 있는 코어에서 읽는다. `core.__file__`의 부모가 site-packages 아래의 패키지 디렉터리이고, 그 경로가 `/opt/rosy_ws/install` 또는 `/opt/rosy/current/install` 안에 있을 때만 그 위에 오버레이를 얹는다. `tokens.css`와 `core_ui_logic.js`는 `get_package_share_directory("web_common")` 위에 파일 단위로 얹는다.

`PYTHONPATH`를 앞에 두는 방식은 쓰지 않는다. `setup.bash`가 설치 트리를 다시 앞에 넣으면 프로세스는 이미지 코드를 실행하고, 경로 문자열만으로는 그 사실이 드러나지 않는다. 성공은 컨테이너 또는 서비스 안의 `core/__init__.py` 바이트 해시가 `/var/lib/rosy-dev/python/core/__init__.py`와 같을 때다. 해시는 바인드 뒤의 내용이지 `__file__` 경로가 아니다. 바인드는 경로 문자열을 유지한 채 내용만 바꾼다.

`--no-build`는 이미지 재생성을 막는다. `--no-deps`는 모터·하드웨어 서비스를 같이 올리지 않는다. 적용은 `rosy-motor` 또는 hardware 프로파일 컨테이너가 떠 있으면 거절한다. 코어 모드로 내린 뒤에만 오버레이를 켠다.

네이티브 벤치도 같은 바인드다. drop-in `BindReadOnlyPaths=`가 서비스 마운트 네임스페이스에서만 얹으므로 `ProtectSystem=strict`인 채 `/opt`에 쓰지 않는다. 저장소의 `rosy-core.service`에는 그 줄을 넣지 않는다. drop-in은 적용 스크립트가 `/etc/systemd/system/rosy-core.service.d/dev-overlay.conf`에만 쓴다.

## 3. 허용 목록

동기화하는 소스와 로봇에 놓는 디렉터리는 고정이다.

| 저장소 | 로봇 |
|---|---|
| `src/core/core/core/` | `python/core/` |
| `src/core/core_common/core_common/` | `python/core_common/` |
| `src/core/core_events/core_events/` | `python/core_events/` |
| `src/core/core_features/core_features/` | `python/core_features/` |
| `src/core/core_api_web/core_api_web/` | `python/core_api_web/` |
| `src/core/web_common/tokens.css` | `share/web_common/tokens.css` |
| `src/core/web_common/core_ui_logic.js` | `share/web_common/core_ui_logic.js` |

대시보드 HTML·JS·CSS는 `core_api_web` 패키지 데이터라 패키지 바인드에 포함된다. `tokens.css`와 `core_ui_logic.js`는 ament share에서 서빙되므로 위 두 파일만 따로 얹는다. `src/core/interfaces`의 `.srv`, `package.xml`의 새 의존, `setup.py` 엔트리포인트, apt 패키지, colcon이 `share/`에 설치하는 launch·설정은 이미지 재빌드 또는 `deploy-from-windows.ps1` 쪽이다. 적용 스크립트는 목록 밖 경로가 아카이브에 있으면 복사 전에 실패한다.

아카이브 멤버는 정규 파일이고, 링크가 아니고, `..`가 없고, 목적지 루트 밖으로 풀리지 않는다. `__pycache__`와 `.pyc`는 넣지 않는다. 바인드는 읽기 전용이고 `PYTHONDONTWRITEBYTECODE=1`이라 로봇이 그 트리에 바이트코드를 쓰지 않는다.

## 4. 신원과 표시

동기화는 `ROS_DOMAIN_ID`, `ROSY_NAMESPACE`, `ROSY_ROBOT_NUMBER`, `deploy/robot/.env`, `/etc/rosy/rosy.yaml`, `/var/lib/rosy`를 읽기만 하거나 아예 열지 않는다. 로봇 번호 인자는 없다. SSH는 `deploy-from-windows.ps1`과 같이 호스트 키 확인을 끄지 않는다.

`/etc/rosy/dev-overlay.json` 스키마 1 필드는 `backend`(`docker` 또는 `native`), `git_revision`(커밋이 아니면 `uncommitted`), `dirty`, `synced_at`, `packages`다. 토큰, 비밀번호, 환경 파일 본문은 넣지 않는다.

2단계의 `device_readback`은 다음 중 하나면 `dev_overlay=true`와 `device_runtime=HOLD`를 낸다.

- 실행 중인 코어에 `ROSY_DEV_OVERLAY=1`
- `/etc/rosy/dev-overlay.json`이 있음
- `/etc/systemd/system/rosy-core.service.d/dev-overlay.conf`가 있음

환경 변수가 없는데 마커나 drop-in만 있으면 `dev_overlay_reason=stale`로 같은 HOLD다. 전체 재설치가 컨테이너를 이미지 코드로 되돌려도 마커가 남으면 릴리스로 세지 않기 위해서다. 신원·activation·digest·health 검사는 그대로 두고, 오버레이 조건이 하나라도 참이면 GO가 되지 않는다.

지우기는 별도 명령이다. 마커와 drop-in을 지우고, 개발 compose 파일 없이 `rosy-core`만 다시 띄운다. 모터는 그때도 자동으로 켜지 않는다.

## 5. 도구

| 파일 | 역할 |
|---|---|
| `deploy/robot/dev/core_dev_overlay.py` | 허용 목록, 경로 거절, 바인드 목적지, 해시 비교, 마커, drop-in 렌더 |
| `deploy/robot/dev/sync-core-dev.ps1` | Windows에서 허용 목록만 tar로 묶어 `scp`/`ssh` |
| `deploy/robot/dev/apply-core-dev.sh` | `python3 -B core_dev_overlay.py`로 적용 |
| `deploy/robot/dev/clear-core-dev.sh` | 같은 모듈로 마커·drop-in·개발 compose만 제거 |

`sync-core-dev.ps1` 인자는 `-PiHost`, `-PiUser`, `-Backend docker|native`다. `-Backend native`는 3단계 전에는 원격 적용을 거절한다. 스크립트는 `install-pi.sh`, `apt-get`, `docker compose build`, `systemctl reboot`, `git pull`을 호출하지 않는다. 목적지에 `/opt/rosy`를 쓰지 않고 `rsync --delete`를 쓰지 않는다.

하루 순서:

1. 노트북에서 해당 패키지 호스트 pytest.
2. 벤치가 코어만 떠 있는지 확인.
3. `sync-core-dev.ps1 -PiHost <host> -PiUser rosy -Backend docker`
4. 로그는 `docker logs` 또는 이후 네이티브의 `journalctl -u rosy-core`. 상태는 대시보드. DDS 인터페이스는 loopback으로 둔다.
5. 수정이 확정되면 커밋하고 로컬 `main`에 합친다. 푸시는 하지 않는다.
6. 그 커밋을 벤치의 설치 기준으로 올릴 때만 `deploy-from-windows.ps1`.
7. 다른 기기로 넘길 때는 서명된 GitHub Release. 로봇의 확인 타이머는 설치하지 않는다.

## 6. 단계

실행 순서와 시험은 [2026-09-23-core-dev-overlay.md](2026-09-23-core-dev-overlay.md)가 소유한다. 호스트 계약, readback HOLD, 네이티브 drop-in 순이다. 제품 이미지, 서명, Host Agent, GitHub 업데이터, `install-pi.sh`는 그 계획에서도 수정하지 않는다.

## 7. 그대로 두는 경로

- `deploy-from-windows.ps1`는 커밋된 `HEAD`만 올리고 `install-pi.sh`로 전체 설치한다. `-AllowDirty`도 작업 트리를 보내지 않는다. 이 스크립트는 재설치 버튼으로 둔다.
- `install-pi.sh`의 apt, Docker 설치, `/opt/rosy` rsync, `docker compose build`는 첫 설치와 커밋 재설치에 남긴다.
- D-161 제품 런타임은 `/opt/rosy/current`의 서명 페이로드다. 오버레이는 `current`를 교체하지 않는다.
- GitHub Releases는 서명된 번들의 게시 위치다. 다운로드는 설치 권한이 아니고, 실패 시 `previous`로 돌아온다.
- 모터·navigation 유닛과 UART는 이 루프에서 재시작하지 않는다.

## 8. 수용

- 허용 목록의 `.py` 한 파일을 바꾼 동기화가 `docker compose build`와 `install-pi.sh` 없이 `rosy-core`만 재시작한다.
- 동기화 직후 readback은 `device_runtime=HOLD`이고 `dev_overlay=true`다.
- `clear-core-dev.sh` 이후 코어 환경에 `ROSY_DEV_OVERLAY`가 없고 마커와 drop-in이 없다.
- `/etc/rosy/rosy.yaml`과 `deploy/robot/.env`의 바이트는 동기화 전후가 같다.
- 목록 밖 경로, 링크, `..`가 들어 있는 아카이브는 목적지에 파일을 만들기 전에 실패한다.
