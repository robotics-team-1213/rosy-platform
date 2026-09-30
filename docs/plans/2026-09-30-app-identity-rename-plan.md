# 앱 이름 규칙 적용(폴더·패키지·식별자) 단계 계획

**결정:** [D-374](../adr/D-374-app-identity-follows-one-role-name.md) Accepted (2026-09-30). D-370 2항의 "식별자는 그대로"를 대체한다. 사용자 결정: 규칙·대응표 그대로, 관제 화면은 안 B, 폰 재설치·재페어링 1회 수용, 경기 보드·제어 진단·시뮬 라이브 뷰는 지금 바꾸지 않음(아래 열린 질문 1–3 닫힘).

**현재 상태:** 문서만 있다(2026-09-30, main `15a4302f` 기준 조사). 단계마다 별도 브랜치(D-372 이름 규칙: `refactor/app-identity-s<N>-<대상>`)와 별도 병합이다.

**공통 규칙:**
- Windows 호스트는 `python`이다. pytest `--basetemp X:\DevTemp\<session>\pt`.
- 옮기는 것은 모두 `git mv`다. 이동 커밋과 내용 수정 커밋을 나누면 병합 때 이름 바뀜 감지가 잘 된다: 커밋 A = `git mv`만, 커밋 B = 참조 수정.
- 기록 문서(날짜 붙은 `docs/plans`, `docs/adr` 본문, `logs.md`, `docs/validation`, `docs/solutions` 본문)의 옛 경로는 고치지 않는다(D-226). 살아 있는 문서(`AGENTS.md`, `README.md`, `index.md`, `progress.md`, `.claude/skills`)는 고친다.
- 단계 끝마다 잔여 확인: `git grep -n "<옛 이름>" -- ':!docs/adr' ':!docs/plans' ':!docs/validation' ':!docs/solutions' ':!**/logs.md'`. 남은 줄은 3항 "never" 목록에 드는 와이어 이름뿐이어야 한다. 그 목록을 커밋 메시지에 붙인다.
- 단계 끝마다 모듈 `logs.md` 항목 → `python tools/harness/rosy_harness.py generate` → `lint` 0 errors.

## 1. 규칙 요약

역할 id(kebab) = D-370 2항 영어 이름 − `Rosy`, 소문자, `-` 연결. snake(`_`)는 폴더 끝·ROS 패키지·Python 패키지·console script·하네스 모듈·logger. compact(구분자 없음)는 Android id 마지막 마디. 표시 이름은 D-345 4항 그대로. 와이어 계약을 부르는 이름은 와이어를 따른다.

## 2. 옛 → 새 대응표

표시: **now** = 해당 단계에서 바꾼다, **alias** = 새 이름과 옛 이름을 함께 두는 기간이 있다, **never** = 바꾸지 않는다(D-374 3항).

### 2.1 천장 카메라 앱 (`ceiling-camera`) — 단계 1

| 식별자 | 옛 | 새 | 표시 |
|---|---|---|---|
| 폴더 | `src/site/overhead/android` | `src/site/ceiling_camera` | now |
| Gradle `rootProject.name` | `rosy-overhead` (`settings.gradle.kts:17`) | `rosy-ceiling-camera` | now |
| `applicationId` | `io.github.livsbittt.rosy.overhead` (`app/build.gradle.kts:12`) | `io.github.livsbittt.rosy.ceilingcamera` | now (재설치·재페어링) |
| `namespace`·Kotlin 패키지·소스 폴더 | `io.github.livsbittt.rosy.overhead` (`:8`, `app/src/{main,test}/java/io/github/livsbittt/rosy/overhead/`) | `…rosy.ceilingcamera`, `…/rosy/ceilingcamera/` | now |
| Gradle 모듈 | `:app` | `:app` | never (앱이 하나라 이름이 역할을 싣지 않는다) |
| DataStore | `overhead_settings` (`SettingsStore.kt:17`) | `ceiling_camera_settings` | now (새 앱이라 옮길 데이터 없음) |
| 레지스트리 id | `overhead-camera-app` (`surfaces.yaml:157`) | `ceiling-camera` | now |
| 아이콘 | `web_common/icons/overhead-camera-app.svg` (`manifest.json:11`, `web_common/CMakeLists.txt:21`) | `web_common/icons/ceiling-camera.svg` | now |
| `token_copy` 경로 | `…/rosy/overhead/ui/RosyTheme.kt` (`surfaces.yaml:171`) | `…/rosy/ceilingcamera/ui/RosyTheme.kt` | now |
| 표시 이름 `app_name` | `Rosy 천장 카메라` (`strings.xml:3`) | 같음 | never (이미 규칙) |
| 링크 방식 | `rosyov` (`AndroidManifest.xml:42`, `PairingUri.kt:32`) | 같음 | never |
| mDNS 해석 종류 | `_rosy-overhead._tcp.`, `_rosy._tcp.` (`OverheadServiceRecord.kt:10,50`) | 같음 | never |
| WS proto | `rosy-overhead/1` (`link/Protocol.kt:39`) | 같음 | never |
| 와이어 클래스 | `OverheadLink`, `OverheadServiceRecord`, `OverheadServerDiscovery` | 같음 | never (와이어 이름) |
| 시험 속성 | `rosy.overhead.vectors` (`app/build.gradle.kts:39`) | 같음 | never (와이어 벡터) |
| 벡터 파일 | `src/site/overhead/protocol/vectors.json` | `test/fixtures/protocol/overhead-ingest.v1.json` | now (두 소비자가 갈라지므로 D-370 5.1의 공유 자리로 옮긴다) |
| 알림 채널 id | `stream` (`StreamService.kt:267`) | 같음 | never |
| logcat TAG | `CameraController`, `OverheadLink`, `StreamService` | 같음 | never (클래스 이름) |
| 하네스 모듈 | (`overhead` 안) | 새 모듈 `ceiling_camera` (`progress.md`, `logs.md`, `index.md`, `AGENTS.md`) | now |
| CI 경로 | `android.yml:10,16,26` `src/site/overhead/**`, `working-directory: src/site/overhead/android` | `src/site/ceiling_camera/**` | now |

### 2.2 Site Vision (`site-vision`) — 단계 1

| 식별자 | 옛 | 새 | 표시 |
|---|---|---|---|
| 폴더 | `src/site/overhead` | `src/site/site_vision` | now |
| ROS 패키지 | `overhead` (`package.xml:4`, `setup.py:3`, `resource/overhead`) | `site_vision` | now |
| Python import | `overhead` (`src/site/overhead/overhead/`) | `site_vision` | now (shim 없음) |
| console script | `overhead=overhead.cli:main` (`setup.py:25`), `setup.cfg` `lib/overhead` | `site_vision=site_vision.cli:main`, `lib/site_vision` | now |
| 옛 console script | `overhead` | `overhead=site_vision.cli:main` 함께 둔다 | alias (한 사이트 후보 릴리스, 단계 5에서 삭제) |
| argparse `prog` | `overhead` (`cli.py:178`) | `site_vision` | now |
| logger | `overhead.vision` (`cli.py:32`) | `site_vision` | now |
| Docker 명령 | `python3 -m overhead.cli vision` (`Dockerfile.vision:33`, `compose.yaml:85`) | `python3 -m site_vision.cli vision` | now |
| Docker 경로 | `/opt/rosy/src/site/overhead…` (`Dockerfile.vision:7,14,19,20`, `.dockerignore:4-7`) | `/opt/rosy/src/site/site_vision…` | now |
| 이미지·compose 서비스·SAN | `rosy-site-vision`, `vision` | 같음 | never (이미 규칙과 맞다) |
| WS 경로 | `/overhead/v1/frames` (`protocol.py:21`, `Caddyfile:8`) | 같음 | never |
| REST | `/api/vision/sources/*` (`Caddyfile:15`), `/api/fleet/sightings` | 같음 | never |
| mDNS 종류·TXT | `_rosy-overhead._tcp`, `role=overhead-camera`, `proto=rosy-overhead/1` (`fleet-mdns.py:23,36`, `discovery_txt.py:27,33`) | 같음 | never |
| mDNS 인스턴스 | `ROSY Overhead %h` (`fleet-mdns.py:36`) | `ROSY Site Vision %h` | now (표시용; Kotlin 시험 fixture 문자열도 함께) |
| 광고 유닛 | `rosy-overhead-advertise.service`, `--role overhead` | 같음 | never (와이어 이름) |
| 비밀·환경 변수 | `ROSY_PHONE_CEILING_NORTH`, `ROSY_FLEET_CEILING_NORTH_TOKEN`, `ROSY_VISION_PREVIEW_SECRET` | 같음 | never |
| 하네스 모듈 | `overhead` (`harness.yaml:57-61`) | `site_vision` | now |
| 모듈 결합 예외 | `("overhead", "games")` (`test_module_structure.py:58`) | `("site_vision", "games")` | now |
| 배치 시험 | `"site/overhead"` (`test_target_layout.py:33`) | `"site/site_vision"`, `"site/ceiling_camera"`는 ROS 패키지가 아니므로 목록 밖 | now |
| 역할 시험 | `test_app_roles.py:17-18` (`CAMERA_APP`, `VISION`) | 새 경로 | now |
| CI | `ci.yml:88-89` `src/site/overhead/test` | `src/site/site_vision/test` | now |
| games 관찰자 `overhead` | `games/catalog.py:13`, `games/host/overhead.py` | 같음 | never (games 내부 관찰자 이름, 이 앱이 아니다) |

### 2.3 Rosy Pilot (`pilot`) — 단계 2

| 식별자 | 옛 | 새 | 표시 |
|---|---|---|---|
| 레지스트리 id | `rosy-pilot` (`surfaces.yaml:93`) | `pilot` | now |
| 폴더·패키지·아이콘 | `src/hmi/pilot`, `pilot`, `icons/pilot.svg` | 같음 | 이미 규칙 |
| 경로·PWA 범위 | `/pilot`, `start_url`·`scope` `/pilot` (`manifest.webmanifest:5-6`), `Service-Worker-Allowed: /pilot` (`api/app.py:254`) | 같음 | never (설치된 PWA가 고아가 된다) |
| 저장소 키 | `rosy.pilot.token`·`.input`·`.recent` (`client.js:5`, `input-state.js:8`, `recent.js:4`) | 같음 | never |
| SW 캐시 이름 | `rosy-pilot-shell-<날짜>` (`sw.js:5`) | 같음 | never (릴리스마다 올리는 값) |

### 2.4 로봇 대시보드 (`robot-dashboard`) — 단계 3 (D-362 게이트)

| 식별자 | 옛 | 새 | 표시 |
|---|---|---|---|
| 폴더 | `src/hmi/dashboard` | `src/hmi/robot_dashboard` | now |
| ROS 패키지·share | `dashboard` (`package.xml:4`, `CMakeLists.txt:2`), `share/dashboard` | `robot_dashboard`, `share/robot_dashboard` | now (이미지 1회) |
| CORE 자산 조회 | `get_package_share_directory("dashboard")`, fallback `parents[4]/"hmi"/"dashboard"` (`api/app.py:84,89`) | `"robot_dashboard"`, `…/"robot_dashboard"` | now |
| `core_api_web` 의존 | `<exec_depend>dashboard</exec_depend>` (`api_web/package.xml:14`) | `robot_dashboard` | now |
| 서빙 예외 | `{"dashboard", "pilot"}` (`test_module_structure.py:410`) | `{"robot_dashboard", "pilot"}` | now |
| 이미지 | `COPY src/hmi/dashboard` (`deploy/robot/pinky_pro/Dockerfile:60`), `--packages-up-to … dashboard pilot` (`:72`), `.dockerignore:25-26` | 새 경로·이름 | now |
| 이미지 탐침 | `get_package_share_directory("dashboard")` (`probe-core-image.py:31`) | `"robot_dashboard"` | now |
| 개발 스크립트 | `tools/sync_rosy.sh:14`, `tools/sync_rosy_fast.sh:11` (`--packages-select … dashboard`) | `robot_dashboard` | now |
| 경로 | `/dashboard`, `/console`, `/setup`, `/device`, `/dashboard/assets/*`; `ui_registry.py:22` `RESERVED` | 같음 | never |
| 저장소 키 | `rosy.dashboard.token`·`.paired` (`client.js:10-11`) | 같음 | never |
| 레지스트리 id·아이콘 | `robot-dashboard`, `/common/icons/robot-dashboard.svg` | 같음 | 이미 규칙 |
| 하네스 모듈 | `dashboard` (`harness.yaml:127-131`) | `robot_dashboard` | now |
| 배치 시험 | `"hmi/dashboard"` (`test_target_layout.py:29`) | `"hmi/robot_dashboard"` | now |
| 스킬 | `.claude/skills/rosy-dashboard-drive/SKILL.md` | 경로만 | now (스킬 이름은 그대로) |

### 2.5 관제 화면 (`site-console`) — 단계 4 (D-362 게이트, 열린 질문 2)

권장안 B: 화면 자산을 자기 패키지로 떼어 낸다. 서버 패키지 `fleet`은 그대로다.

| 식별자 | 옛 | 새 | 표시 |
|---|---|---|---|
| 자산 폴더 | `src/site/fleet/fleet/server/web` | `src/site/site_console` (ament_cmake, `share/site_console`) | now |
| 자산 조회 | `WEB_ROOT = Path(__file__).parent / "web"` (`static_routes.py:17`), `package_data` (`fleet/setup.py:9`) | `get_package_share_directory("site_console")`, fallback `src/site/site_console`, CLI `--console-web`(CORE의 대시보드 조회와 같은 꼴) | now |
| Docker | `COPY src/site/fleet/` (`Dockerfile.fleet:20`) | `site_console`도 `/opt/rosy/site-console`로 복사하고 `--console-web` 전달, `.dockerignore` 허용 | now |
| 레지스트리 id·아이콘 | `fleet-console`, `icons/fleet-console.svg` (`surfaces.yaml:44-49`, `manifest.json:13`) | `site-console`, `icons/site-console.svg` (Fleet `index.html`의 favicon 링크 포함) | now |
| 서버 패키지·CLI·logger | `fleet`, `fleet console`, `fleet.console` (`console.py:46`) | 같음 | never (Fleet 서비스, 앱 아님) |
| 경로 | `/console`, `/console/assets/*` (`static_routes.py:57,89`), `/api/fleet/*` | 같음 | never |
| 저장소 키 | `rosy-console-token` (`console.js:33`), `rosy-console-layers` (`field-layers.js:8`) | 같음 | never |
| compose·이미지·SAN·DB | `fleet`, `rosy-site-fleet`, SAN `fleet`, `fleet.sqlite3` | 같음 | never |
| 하네스 | `fleet` | 그대로 + 새 모듈 `site_console` | now |

### 2.6 범위 밖(바뀌지 않는다)

| 대상 | 이유 |
|---|---|
| Fleet 서비스 `src/site/fleet`·`fleet` | 앱 아님, 와이어 역할과 이미 같은 이름(D-374 2항) |
| CORE `core`·`core_api_web` | API, D-231·D-339 그대로 |
| 로봇 LCD `rosy-boot-display.service`(`native/rosy-boot-display.service:48`), 얼굴 `emotion` | 앱 아님, 장치 이미지 유닛 |
| `web_common` | 라이브러리, 이미 규칙과 같다 |
| 경기 보드 `games`, 제어 진단, 시뮬 라이브 뷰 | D-370 이름표 밖(열린 질문 1) |

## 3. 단계

### 단계 1 — 천장 카메라 앱 + Site Vision

**게이트:** `feat/camera-preview-rectification`(overhead 9파일)과 `feat/d359-theme-ready`(1파일) 주인에게 알린다. 먼저 병합하거나, 이동 뒤 rebase하겠다는 답을 받는다. main 체크아웃 `git status --porcelain -- src/site/overhead`가 비어 있어야 한다.

**커밋 A — 이동만:**
```
git mv src/site/overhead/android src/site/ceiling_camera
git mv src/site/overhead src/site/site_vision
git mv src/site/site_vision/overhead src/site/site_vision/site_vision
git mv src/site/site_vision/resource/overhead src/site/site_vision/resource/site_vision
git mv src/site/site_vision/protocol/vectors.json test/fixtures/protocol/overhead-ingest.v1.json
git mv src/site/ceiling_camera/app/src/main/java/io/github/livsbittt/rosy/overhead src/site/ceiling_camera/app/src/main/java/io/github/livsbittt/rosy/ceilingcamera
git mv src/site/ceiling_camera/app/src/test/java/io/github/livsbittt/rosy/overhead src/site/ceiling_camera/app/src/test/java/io/github/livsbittt/rosy/ceilingcamera
git mv src/hmi/web_common/icons/overhead-camera-app.svg src/hmi/web_common/icons/ceiling-camera.svg
```
(빈 `src/site/site_vision/protocol/`은 지운다.) 모듈 기록: `site_vision`이 `index.md`·`logs.md`·`progress.md`·`AGENTS.md`를 이어받는다. `ceiling_camera`에는 새 네 파일을 만든다. 새 `logs.md` 첫 항목은 "이력은 `src/site/site_vision/logs.md`의 2026-09-30 이전 항목"을 가리킨다.

**커밋 B — 참조:**
- Python: `package.xml`·`setup.py`·`setup.cfg`의 이름, console script와 `overhead` alias, `cli.py` `prog`·logger, import. `test/conftest.py`의 `SITE / "overhead"` → `"site_vision"`. `protocol.py`·시험의 벡터 경로.
- Android: `settings.gradle.kts`, `app/build.gradle.kts`(`namespace`, `applicationId`, 벡터 경로 `rootProject.file("../../../test/fixtures/protocol/…")` — 폴더가 한 단계 얕아진다). 모든 `.kt`의 `package`·`import` 줄. `SettingsStore.kt` DataStore 이름. `ic_launcher_*.xml` 주석과 `LauncherIconParityTest.kt`의 SVG 이름. `OverheadServiceRecordTest.kt`의 인스턴스 이름.
- 배포: `Dockerfile.vision`, `Dockerfile.vision.dockerignore`, `compose.yaml:85`, `fleet-mdns.py:36` 인스턴스 이름, `test/test_site_fleet_mdns.py`, `build_candidate.py`·`verify_candidate.py`(경로가 있으면), `deploy/site/README.md`.
- 레지스트리·시험: `surfaces.yaml`(id, icon, path, ports source `src/site/site_vision/site_vision/cli.py`, token_copy), `manifest.json`, `web_common/CMakeLists.txt`, `test_surface_icons.py:28,35,152`, `test_app_roles.py:17-18`, `test_module_structure.py:58`, `test_target_layout.py:33`, `test/test_site_candidate*.py`, `src/site/games/test/test_overhead.py`(Vision을 import하면).
- 하네스·CI·문서: `harness.yaml`(`overhead` → `site_vision`, 새 `ceiling_camera` 모듈. functional에는 Android JVM 시험을 호스트에서 돌릴 수 없으므로 `functional_kind: host-contract`로 `test_app_roles.py`·`test_surface_icons.py`를 둔다), `ci.yml:86-89`, `android.yml`, `.github/workflows/AGENTS.md`, `README.md:45`, `src/AGENTS.md`, `src/site/AGENTS.md`, `docs/reference/site-lan-discovery-profile.md`(경로만), `docs/index.md`.
- 새 시험 `test/architecture/test_app_identity.py`: `surfaces.yaml`의 `app_name`이 있는 행마다 id ↔ 폴더 끝 ↔ `package.xml` ↔ 아이콘 ↔ `applicationId`를 대조한다. 먼저 빨간 상태로 쓴다(단계 2–4 행은 `pending` 표로 두고, 단계마다 한 줄씩 지운다).

**시험:**
```
python -m pytest src/site/site_vision/test -q
python -m pytest src/site/fleet/test src/site/games/test test/architecture test/test_site_fleet_mdns.py test/test_site_candidate.py test/test_site_candidate_verifier.py -q
python -m pytest src/hmi/web_common/test src/contracts/foundation/test/test_discovery_txt_vectors.py -q
cd src/site/ceiling_camera && ./gradlew testDebugUnitTest
python tools/harness/rosy_harness.py generate && python tools/harness/rosy_harness.py lint
```

**장치:**
1. 사이트 호스트: vision 이미지를 다시 빌드한다(`docker compose build vision`). 올린 뒤 `/healthz` ok, `avahi-browse -rtpk _rosy-overhead._tcp`에서 인스턴스 `ROSY Site Vision <host>`와 TXT가 그대로인지 확인한다.
2. 폰: 옛 앱(`io.github.livsbittt.rosy.overhead`) 송출을 멈추고 지운다(`adb uninstall io.github.livsbittt.rosy.overhead`).
3. 새 APK를 설치한다(`./gradlew installDebug`). 런처에 이름 `Rosy 천장 카메라`와 D-370 아이콘이 보여야 한다.
4. 사이트 QR `rosyov://<fqdn>:8443/?t=…&s=<source>&tls=1`로 다시 페어링한다(D-341이 착지했으면 콘솔 승인).
5. 관제 카메라 패널에서 새 프레임 미리보기와 sighting을 확인한다.
6. 옛 폰을 재사용한다면 그 source 토큰을 교체한다.
증거 등급: 1–5 = DEVICE. 사진이나 로그는 공개 저장소 밖(`private/`, D-226)에 둔다.

### 단계 2 — Pilot 레지스트리 id

`surfaces.yaml:93` `rosy-pilot` → `pilot`. id를 키로 쓰는 시험(`test_surface_icons.py`, `test_app_roles.py`, `api_web/test/test_surface_manifest_api.py`)을 고친다. `test_app_identity.py`의 pending 줄을 지운다. `git mv`는 없다.
시험: `python -m pytest src/hmi/web_common/test src/hmi/pilot/test src/runtime/api_web/test test/architecture -q`. 장치 절차 없음.
게이트: `feat/pilot-polish`가 `surfaces.yaml`을 고치는 중이면 그 뒤에 한다.

### 단계 3 — 로봇 대시보드

**게이트(D-362 착지 감지). 모두 참이어야 한다:**
1. `docs/plans/2026-09-30-file-size-budget-and-refactor-queue.md` §7의 모든 행이 "완료"이고, 그 커밋이 main에 있다. 2026-09-30 조사 때 참이었다: P0-1 `b67c9dfc`, P1 `13803932`, ADR D-362 착지.
2. main 체크아웃에서 `git -C "<main>" status --porcelain -- src/hmi/dashboard src/runtime/api_web src/runtime/gateway/test`가 비어 있다. 또 그 경로의 파일 수정 시각이 24시간 이상 지났다(D-372: 최근 수정은 살아 있는 작업이다).
3. `git branch --no-merged main`의 브랜치 가운데 `git diff --name-only main...<b> -- src/hmi/dashboard`가 비어 있지 않은 것(부록 B)은 주인이 "먼저 병합" 또는 "이동 뒤 rebase"로 답했다.
4. 로봇 이미지 릴리스 사이다(D-191). 이 단계는 다음 이미지에 실린다.

**이동:** `git mv src/hmi/dashboard src/hmi/robot_dashboard`.
**참조:** 2.4 표 전부 + `git grep -n '"dashboard"\|hmi/dashboard\|share/dashboard'`로 찾은 시험(`src/runtime/gateway/test/test_dashboard*.py`, `test_console_layout.py`, `test_first_paint.py`, `test_host_cards.py`, `test_triage_contract.py`, `test_vision_preview.py` 등), `src/runtime/api_web/test/test_ui_*.py`, `test/test_camera_capture_browser.py`, `web_common/test/test_{palette_gates,shared_controls,ui_token_contracts}.py`, `surfaces.yaml:26`, `STATUS.md`(generate), `AGENTS.md`·`src/AGENTS.md`·`src/runtime/AGENTS.md`·`src/runtime/api_web/AGENTS.md`·`src/runtime/gateway/core/AGENTS.md`, `README.md:46`.
**시험:** `python -m pytest src/hmi/robot_dashboard/test src/runtime/gateway/test src/runtime/api_web/test src/hmi/web_common/test test/architecture -q`, 그리고 `ROSY_RUN_BROWSER_TESTS=1 python -m pytest test/test_dashboard_browser.py`. WSL ROS box에서 `colcon build --packages-up-to core_api_web` 뒤 `ros2 pkg prefix robot_dashboard`.
**장치:** 이미지를 빌드하고 `probe-core-image.py`를 통과시킨다. 로봇에서 `/dashboard`, `/console`, `/setup`, `/device`, `/pilot`이 열리는지 본다. 개발 PC는 `install/dashboard`를 지우고 다시 빌드한다.

### 단계 4 — 관제 화면 분리

**게이트:** 단계 3의 1·3번을 `src/site/fleet`에 적용한다. main 체크아웃 `git status --porcelain -- src/site/fleet`가 비어 있어야 한다. 열린 Fleet 브랜치(부록 B: `feat/d355-goal-evidence-verifier` 15파일, `feat/d359-theme-ready` 13파일, `feat/camera-preview-rectification` 9파일 외)의 주인이 답해야 한다. 열린 질문 2의 답(권장 B)도 필요하다.
**이동:** `git mv src/site/fleet/fleet/server/web src/site/site_console`, `git mv src/hmi/web_common/icons/fleet-console.svg src/hmi/web_common/icons/site-console.svg`. `src/site/site_console/{package.xml,CMakeLists.txt}`는 대시보드 것을 본떠 새로 만든다. 모듈 기록 네 파일도 만든다.
**참조:** 2.5 표 + `fleet/setup.py:9` `package_data` 삭제, `static_routes.py` 조회, `fleet/cli.py` `--console-web`, `Dockerfile.fleet`와 그 `.dockerignore`, `compose.yaml` 명령, `test_no_video_relay.py`와 `fleet/test`의 `server/web` 경로(`test_console_palette.py`, `test_grammar_separation.py` 등), `test/test_fleet_console_browser.py`, `test_surface_icons.py:30,36,138`, `surfaces.yaml:44-49`, `manifest.json`, `web_common/CMakeLists.txt`, `harness.yaml`, `test_target_layout.py`, D-362 `SIZE_VERDICTS`의 `site/fleet/fleet/server/web/*` 키(`test_module_structure.py`).
**시험:** `python -m pytest src/site/fleet/test src/site/site_console/test src/hmi/web_common/test test/architecture test/test_site_candidate.py -q`, `ROSY_RUN_BROWSER_TESTS=1 python -m pytest test/test_fleet_console_browser.py`.
**장치:** fleet 이미지를 다시 빌드한다. 사이트 `/console`이 열리고 `/common/icons/site-console.svg` favicon이 보여야 한다. 운용자 로그인이 유지되는지도 본다(저장소 키 불변).

### 단계 5 — 별칭 제거

**게이트:** 단계 1을 담은 사이트 후보가 `build_candidate.py`로 한 번 나가 현장에 올라갔다.
`site_vision/setup.py`에서 `overhead=` 줄을 지운다. `git grep -n "\boverhead receive\|\boverhead vision"`의 운용 문서를 `site_vision`으로 고친다.

## 4. 위험

- **병합 충돌.** 폴더 이동은 열린 브랜치에 이름 바뀜 충돌을 만든다. 커밋 A(이동만)를 분리하면 `merge-ort`가 대부분 따라간다. 단계마다 부록 B를 다시 뽑아 주인에게 알린다.
- **보이지 않는 동시 세션.** D-372 사건처럼 ListAgents 밖 세션이 main 체크아웃을 고칠 수 있다. 게이트 2의 수정 시각 검사가 이것을 잡는다.
- **폰 두 앱 공존.** 옛 앱을 지우지 않으면 `rosyov://` 선택 창과 source 충돌이 생긴다. 장치 절차 2번이 먼저다.
- **이미지 결합.** 단계 3은 CORE 코드와 자산 패키지 이름이 같은 이미지에 있어야 한다. 반쪽 이미지는 `/dashboard` 503이다. `probe-core-image.py`가 막는다.
- **경로 참조 누락.** 잔여 `git grep`과 `test_app_identity.py`, `test_target_layout.py`가 막는다.

## 부록 A — 조사 표 (2026-09-30, main `15a4302f`)

| 앱 | 폴더 | ROS/colcon | Python import | console script | Android | 웹 경로 | 서빙 자산 | 제목 | manifest/PWA | systemd | Docker/compose | mDNS 종류·인스턴스 | 로그·모듈 기록 | 문서·시험 참조 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 천장 카메라 | `src/site/overhead/android` (`COLCON_IGNORE`) | 없음 | 없음 | 없음 | ns·id `io.github.livsbittt.rosy.overhead` (`app/build.gradle.kts:8,12`), `rootProject.name "rosy-overhead"` (`settings.gradle.kts:17`), `:app`, DataStore `overhead_settings` (`SettingsStore.kt:17`) | 없음(클라이언트: `/overhead/v1/frames`) | 아이콘 `/common/icons/overhead-camera-app.svg` (`manifest.json:11`) | 네이티브 `app_name` `Rosy 천장 카메라` (`strings.xml:3`) | 해당 없음 | 없음 | 없음 | 해석 `_rosy-overhead._tcp.`·`_rosy._tcp.` (`OverheadServiceRecord.kt:10,50`) | 하네스 `overhead` 모듈에 포함 (`harness.yaml:57`), TAG `OverheadLink` 등 | `surfaces.yaml:157-174`, `test_app_roles.py:17`, `test_surface_icons.py:28,35,152`, `android.yml:10,16,26` |
| Site Vision | `src/site/overhead` | `overhead` (`package.xml:4`) | `overhead` | `overhead` (`setup.py:25`; 하위 `receive`·`vision`, `cli.py:181,194`) | — | WS `/overhead/v1/frames` (`protocol.py:21`), `/api/vision/sources/*`, `/healthz` | 미리보기 JPEG | 없음(화면 없음) | 없음 | `rosy-overhead-advertise.service` (광고) | `rosy-site-vision`, 서비스 `vision`, `python3 -m overhead.cli vision` (`compose.yaml:75-85`, `Dockerfile.vision:33`) | 광고 `_rosy-overhead._tcp`, `ROSY Overhead %h`, `role=overhead-camera`, `proto=rosy-overhead/1` (`fleet-mdns.py:23,36`) | logger `overhead.vision` (`cli.py:32`), 모듈 `overhead` | `ci.yml:88-89`, `test_module_structure.py:58`, `test_target_layout.py:33`, `test_app_roles.py:18` |
| 관제 화면 | `src/site/fleet/fleet/server/web` | (`fleet` 안) | (`fleet` 안) | `fleet console` (`fleet/cli.py:64`) | — | `/console`, `/console/assets/*`, `/common/*` (`static_routes.py:57,67,89`), API `/api/fleet/*` | `index.html`·`*.css`·`*.js` (`fleet/setup.py:9`) | `Rosy 사이트 — 관제` | 없음(향후 PWA) | `rosy-fleet-advertise.service`, `rosy-site-stack.service` | `rosy-site-fleet`, 서비스 `fleet`, `python3 -m fleet.cli console` (`compose.yaml:2-11`, `Dockerfile.fleet:32`) | `_rosy-fleet._tcp`, `ROSY Fleet %h`, `role=fleet`, `proto=site-v1` (`fleet-mdns.py:19-32`) | logger `fleet.console` (`console.py:46`), 모듈 `fleet` | `surfaces.yaml:44-59`, `test_surface_icons.py:30,36,138`, `ci.yml:73,84` |
| 로봇 대시보드 | `src/hmi/dashboard` | `dashboard` (ament_cmake) | 없음 | 없음 | — | `/dashboard`, `/console`, `/setup`, `/device`, `/dashboard/assets/*` (`api/app.py:185-195`) | `share/dashboard` (`api/app.py:84`) | `Rosy 로봇 — 대시보드`, `Rosy 로봇 — {{title}}` | 없음 | 로봇 CORE 유닛(이미지) | 로봇 이미지 `Dockerfile:60,72` | 로봇 `_rosy._tcp`, `ROSY %h` (`rosy-boot-status.py:271`) | 모듈 `dashboard` (`harness.yaml:127`) | `surfaces.yaml:21-42`, `probe-core-image.py:31`, `.dockerignore:25-26`, `tools/sync_rosy*.sh` |
| Rosy Pilot | `src/hmi/pilot` | `pilot` | 없음 | 없음 | — | `/pilot`, `/pilot/assets/*` (`api/app.py:231,246`) | `share/pilot` (`api/app.py:97`) | `Rosy 로봇 — 조종` | `name`·`short_name` `Rosy Pilot`, `start_url`·`scope` `/pilot` | 로봇 CORE | 로봇 이미지 `Dockerfile:62,72` | (로봇) | 모듈 `pilot` (`harness.yaml:132`) | `surfaces.yaml:93-113`(id `rosy-pilot`) |
| 로봇 LCD | `deploy/robot/pinky_pro/native/rosy-boot-display.py` + `src/hmi/face`(`emotion`) | `emotion` | `emotion` | `emotion`, `emotion_server` | — | 없음 | 없음 | 없음 | 없음 | `rosy-boot-display.service` | 로봇 이미지 | 없음 | 모듈(face) | `surfaces.yaml:144-155` |
| `web_common` | `src/hmi/web_common` | `web_common` | 없음 | 없음 | — | `/common/*` (CORE·Fleet·games) | `manifest.json` 허용 목록 | `template.html` 참조용 | 없음 | 없음 | `/opt/rosy/web-common` | 없음 | 모듈 `web_common` | `surfaces.yaml:115-127` |
| CORE API | `src/runtime/api_web` | `core_api_web` | `core_api_web` | 없음 | — | `/api/v1/*`, `/ws`, `/docs` | 대시보드·Pilot 서빙 | 없음 | 없음 | CORE | 로봇 이미지 | 로봇 | 모듈 | 사람이 여는 앱이 아니다 |
| 경기 보드 | `src/site/games/games/web` | `games` | `games` | `games` | — | `/board`, `/common/*` | 보드 자산 | `Rosy 사이트 — 경기 보드` | 없음 | 없음 | 없음 | 없음 | 모듈 `games` | `surfaces.yaml:61-72` |
| 제어 진단 | `src/runtime/sensing/web/diagnostic.html` | `control` | — | — | — | 28181/28182 | — | `Rosy 로봇 — 제어 진단` | — | — | — | — | — | PARKED(D-266) |
| 시뮬 라이브 뷰 | `src/sim/gz_sim/scripts/lane_live_view.html` | `gz_sim` | — | — | — | 28183 | — | `Rosy 시뮬 — 라이브 미션` | — | — | — | — | — | 제품 표면 아님 |

## 부록 B — 앱 폴더를 고치는 열린 브랜치 (2026-09-30)

`git diff --name-only main...<b>` 파일 수. 단계 시작 때 다시 뽑는다.

| 브랜치 | overhead | fleet | dashboard | pilot |
|---|---|---|---|---|
| `feat/camera-preview-rectification` | 9 | 9 | 0 | 0 |
| `feat/d359-theme-ready` | 1 | 13 | 48 | 0 |
| `feat/d355-goal-evidence-verifier` | 0 | 15 | 0 | 0 |
| `refactor/d362-p0-1-fleet-app-routes` | 0 | 10 | 0 | 0 |
| `refactor/d362-p1-dashboard-split` | 0 | 0 | 11 | 0 |
| `docs/ui-boundaries-d322` | 0 | 4 | 6 | 0 |
| `release/floor-g4-minimal` | 0 | 0 | 7 | 0 |
| `feat/camera-frame-direct-manipulation` | 0 | 3 | 0 | 0 |
| `ui/fleet-empty-event-state` | 0 | 3 | 0 | 0 |
| `feat/camera-ux-final-polish` | 0 | 2 | 0 | 0 |
| `uiux/host-console-readback-evidence` | 0 | 0 | 2 | 0 |
| `uiux/mobile-acceptance` | 0 | 0 | 2 | 0 |
| `refactor/web-transport` | 0 | 1 | 1 | 0 |

`refactor/d362-*` 두 브랜치는 D-372 보존 백업이다. 같은 내용이 `b67c9dfc`·`13803932`로 main에 있다.

## 열린 질문

1. 경기 보드(`games`)·제어 진단·시뮬 라이브 뷰도 이 규칙으로 바꿀까? 권장: 아니다. D-370 이름표 밖이고 앱 이름이 없다. **닫힘(2026-09-30): 지금 바꾸지 않는다.**
2. 관제 화면: 권장안 B(화면 자산만 `site_console` 패키지로 떼고 Fleet 서비스 `fleet`은 유지)와 A(`fleet` 패키지 전체를 `site_console`로) 중 어느 쪽인가? **닫힘(2026-09-30): 안 B.**
3. 폰 applicationId 변경과 재페어링 1회를 지금 받아들이나? 설치된 폰이 적은 지금이 가장 싸다. **닫힘(2026-09-30): 받아들인다.**
4. compose 서비스·이미지 `fleet`/`rosy-site-fleet`을 언젠가 인증서 재발급과 함께 바꿀 생각이 있나? 권장: 바꾸지 않는다.
