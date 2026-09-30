## D-374 앱의 폴더·패키지·식별자·표시 이름은 역할 이름 하나에서 나온다 — 와이어 계약 이름은 바꾸지 않는다

**Status:** Accepted (2026-09-30, 사용자 결정 아래 참조). 이름 규칙, 앱별 옛→새 대응표, 바꾸지 않는 와이어 식별자 목록, 단계 순서만 정한다. 이 ADR 자체는 코드·리소스를 바꾸지 않는다. 실행은 [2026-09-30 app identity rename plan](../plans/2026-09-30-app-identity-rename-plan.md)이 단계별로 한다. 단계 3·4·5는 계획의 게이트를 그대로 따른다.

**부분 대체됨 (2026-09-30):** [D-377](D-377-app-names-rosy-plus-one-english-word.md)이 1항 규칙과 2항 대응표를 "Rosy + 영어 한 단어"로 대체한다(`ceiling-camera`·`site-vision`·`site-console`·`robot-dashboard` → `cam`·`vision`·`console`·`robot`, 패키지 `rosy_<word>`). 3·4·5항은 그대로다.

**사용자 결정 — Accepted (2026-09-30):**
1. 1항 규칙과 2항 대응표를 제안대로 적용한다.
2. Fleet 관제 화면은 **안 B**다. 화면 자산만 `site_console` 패키지로 떼어 내고, 서비스 패키지 `fleet`은 그대로 둔다(열린 질문 2 닫힘).
3. 새 applicationId 때문에 폰 재설치와 재페어링을 한 번 하는 것을 받아들인다(4항, 열린 질문 3 닫힘).
4. 경기 보드(`games`), 제어 진단, 시뮬 라이브 뷰는 지금 바꾸지 않는다(열린 질문 1 닫힘).

Validation 절의 "단계 1이 main에서 녹색이면 Accepted" 조건은 사용자가 위 결정으로 앞당겼다. 단계 1의 녹색은 여전히 단계 1 병합의 조건이다.

**부분 대체:**
- [D-370](D-370-site-app-roles-names-and-shared-link.md) 2항의 "패키지·폴더·applicationId·서비스 종류 이름은 바꾸지 않는다(D-231, D-339 1항)"를 대체한다. 이 ADR 이후에는 **앱**의 폴더·패키지·applicationId가 아래 규칙을 따른다. **서비스 종류(mDNS)와 그 밖의 와이어 이름은 여전히 바꾸지 않는다**(3항).
- [D-339](D-339-surface-and-folder-role-names.md) 1항("패키지 이름은 그대로다")과 [D-231](D-231-layered-source-roots-keep-package-names.md) 2항(기존 패키지 이름 유지)은 **2항의 적용 범위에 든 앱 패키지에 한해** 대체한다. CORE·런타임·장치·계약 패키지(`core`, `control`, `core_features`, `core_api_web`, `core_common`, `emotion`, `web_common` 등)에는 그대로 적용된다.

**사용자 결정 (2026-09-30):** "모든 앱을 규칙에 따라 이름을 바꾼다." 표시 이름만이 아니라 폴더·패키지·식별자까지 바꾼다. D-370 2항의 "식별자는 그대로" 줄을 뒤집는다.

잇는 결정: [D-147](D-147-src-6.md) · [D-191](D-191-pinky-pro-device-readiness-matrix.md) · [D-226](D-226-document-placement-and-publication-criteria.md) · [D-231](D-231-layered-source-roots-keep-package-names.md) · [D-243](D-243-operator-screens-live-in-hmi.md) · [D-257](D-257-site-lane-map-and-overhead-sightings.md) · [D-261](D-261-overhead-camera-app-skeleton.md) · [D-315](D-315-source-folder-responsibility-and-runtime-authority.md) · [D-323](D-323-rosy-pilot-teleop-app.md) · [D-339](D-339-surface-and-folder-role-names.md) · D-341(브랜치 `docs/d341-overhead-console-pairing`) · [D-345](D-345-design-philosophy-reaches-every-surface.md) · [D-362](D-362-per-code-type-file-size-budget.md) · [D-370](D-370-site-app-roles-names-and-shared-link.md) · [D-372](D-372-topic-branch-names-and-shared-checkout-wip.md).

### Context

2026-09-30 main `15a4302f`을 읽기 전용으로 조사했다. 전체 표(파일:줄 인용)는 실행 계획의 부록 A다. 요점은 다음과 같다.

**한 앱의 이름이 자리마다 다르다.**

| 앱 | 표시 이름(D-370 2항) | 레지스트리 id | 폴더 | 패키지·모듈 | 기타 |
|---|---|---|---|---|---|
| 천장 카메라 앱 | Rosy 천장 카메라 / Rosy Ceiling Camera | `overhead-camera-app` | `src/site/overhead/android` | applicationId·namespace `io.github.livsbittt.rosy.overhead`(`app/build.gradle.kts:8,12`), `rootProject.name = "rosy-overhead"`(`settings.gradle.kts:17`) | DataStore `overhead_settings`(`SettingsStore.kt:17`) |
| Site Vision | 사이트 비전 / Site Vision | 없음 | `src/site/overhead` | ROS·Python `overhead`, 실행 파일 `overhead`(`setup.py:25`), logger `overhead.vision`(`cli.py:32`) | 이미지 `rosy-site-vision`, compose `vision` |
| Fleet 관제 화면 | Rosy 관제 / Rosy Site Console | `fleet-console` | `src/site/fleet/fleet/server/web` | `fleet` 패키지 안의 자산(`setup.py:9`, `static_routes.py:17`) | 경로 `/console` |
| 로봇 대시보드 | Rosy 로봇 대시보드 / Rosy Robot Dashboard | `robot-dashboard` | `src/hmi/dashboard` | ROS `dashboard`(`CMakeLists.txt:2`), CORE가 `get_package_share_directory("dashboard")`로 찾는다(`api/app.py:84,89`) | 경로 `/dashboard`·`/console`·`/setup`·`/device` |
| Rosy Pilot | Rosy Pilot | `rosy-pilot` | `src/hmi/pilot` | ROS `pilot` | PWA `start_url`·`scope` `/pilot`(`manifest.webmanifest:5-6`) |

- 폴더와 패키지가 같은 이름을 쓰는 앱(`pilot`)도 레지스트리 id는 다르다(`rosy-pilot`).
- 천장 카메라 앱과 Site Vision은 역할이 다른 두 참여자다(D-370 1항). 그런데 한 폴더 `src/site/overhead`와 한 이름 `overhead`를 함께 쓴다.
- Fleet 관제 화면은 D-315 4항("사이트 console은 Fleet 서버가 제공한다")에 따르면 Fleet 서비스가 **서빙하는 표면**이다. 그런데 소스는 서버 패키지 안의 `server/web`에 있어 자기 이름이 없다. 로봇 쪽은 이미 서버(`core_api_web`)와 표면 패키지(`dashboard`, `pilot`)가 나뉘어 있다.

**와이어·배포 이름은 앱 이름과 따로 퍼져 있다.** 앱 이름을 바꾸면 다음을 끊을 위험이 있다.
- mDNS: `_rosy-overhead._tcp`, `_rosy-fleet._tcp`, `_rosy._tcp`. TXT `role`·`proto` 값이 로봇 이미지(`rosy-boot-status.py`), 사이트 호스트(`fleet-mdns.py:19-36`), 폰(`OverheadServiceRecord.kt:10,50`), 공유 벡터(`test/fixtures/protocol/discovery-txt.v1.json`)에 있다.
- WS 프로토콜 `rosy-overhead/1`과 경로 `/overhead/v1/frames`(`protocol.py:20-21`, `Caddyfile:8`).
- REST `/api/fleet/*`, `/api/vision/*`.
- 설치된 QR 링크의 `rosyov://`(`PairingUri.kt:32`, `AndroidManifest.xml:42`).
- 브라우저 경로와 PWA 범위, 브라우저 저장소 키(`rosy.dashboard.token`, `rosy.pilot.token`, `rosy-console-token`).
- compose 서비스 이름. 이것이 곧 컨테이너 호스트 이름, 사이트 인증서 SAN(`deploy/site/README.md:101-103`), 이미지 이름(`build_candidate.py:95`)이다.

**진행 중 작업.** D-362 P0-1(Fleet `app.py` 라우터 분리)과 P1(대시보드 `app.js` 분할)은 이 조사 도중 main에 착지했다(`b67c9dfc`, `13803932`). 착지 전에는 main 체크아웃에 미커밋으로 있었다. 그 밖에도 열린 브랜치가 Fleet·대시보드·overhead 폴더를 고치고 있다(부록 B). 폴더를 옮기는 커밋은 이들과 병합 충돌을 만든다.

### Decision

#### 1. 규칙 — 역할 이름 하나, 표기 넷

앱마다 **역할 id**를 하나 정한다. 역할 id는 D-370 2항의 영어 이름에서 `Rosy`를 떼고 소문자로 쓰고 낱말을 `-`로 잇는다. 나머지 이름은 모두 이 id에서 기계적으로 나온다.

| 표기 | 만드는 법 | 쓰는 곳 |
|---|---|---|
| **kebab** (역할 id) | `ceiling-camera` | `surfaces.yaml` `id`, 아이콘 `src/hmi/web_common/icons/<id>.svg`, Gradle `rootProject.name = "rosy-<id>"` |
| **snake** | `-` → `_` : `ceiling_camera` | 폴더 끝 이름, ROS/colcon 패키지, Python import 패키지, console script(D-345 6항: 실행 파일 = 패키지 이름), 하네스 모듈 이름, logger 뿌리 |
| **compact** | `-` 제거 : `ceilingcamera` | Android `applicationId`·`namespace`·Kotlin 패키지의 마지막 마디 `io.github.livsbittt.rosy.<compact>` |
| **표시** | D-345 4항 `Rosy <이름>`, D-339 4항 탭 제목 | 런처·PWA `name`·`short_name`, `<title>` (바뀌지 않는다) |

- 폴더는 `src/<영역>/<snake>`다. 사이트 앱은 `src/site/`, 로봇 화면은 `src/hmi/`에 둔다(D-243, D-315). **폴더 끝 이름과 패키지 이름이 같다.** 그래서 앱은 D-339 1항의 폴더↔패키지 대응표(`test_module_structure.py` `ROLE_DIR`)에 오르지 않는다. 영역 폴더는 분류일 뿐 신원이 아니다(D-315). 그래서 `src/site/site_vision`처럼 겹쳐 읽혀도 받아들인다.
- ROS 제약: snake는 소문자·숫자·`_`만 쓰고 글자로 시작한다(REP-144). `rosy_` 접두를 붙이지 않는다(D-147).
- Android 제약: 마디마다 소문자 글자로 시작하고 `_`와 `-`를 쓰지 않는다. 그래서 compact 표기를 쓴다.
- **와이어 계약을 부르는 이름은 앱이 아니라 와이어를 따른다.** mDNS 서비스 종류를 광고하는 파일·유닛, 프로토콜을 구현하는 클래스, 프로토콜 벡터가 여기에 든다(3항).

#### 2. 적용 범위와 역할 id

| 참여자 | 역할 id | 폴더 | 패키지 | 비고 |
|---|---|---|---|---|
| 천장 카메라 앱 | `ceiling-camera` | `src/site/ceiling_camera` | (ROS 패키지 아님, `COLCON_IGNORE`) applicationId `io.github.livsbittt.rosy.ceilingcamera` | `src/site/overhead/android`에서 떼어 낸다 |
| Site Vision | `site-vision` | `src/site/site_vision` | `site_vision` | `src/site/overhead`의 Python 쪽 |
| Fleet 관제 화면 | `site-console` | `src/site/site_console` | `site_console` (ament_cmake, 자산만) | `fleet/server/web`을 떼어 낸다. 서버 패키지 `fleet`이 서빙한다(대시보드와 같은 꼴) |
| 로봇 대시보드 | `robot-dashboard` | `src/hmi/robot_dashboard` | `robot_dashboard` | 레지스트리 id는 이미 맞다 |
| Rosy Pilot | `pilot` | `src/hmi/pilot` (그대로) | `pilot` (그대로) | 레지스트리 id `rosy-pilot` → `pilot`만 바뀐다 |

**범위 밖이고 이유가 있는 것:**
- **Fleet 서비스(`src/site/fleet`, 패키지 `fleet`).** 앱이 아니라 사이트 서비스다. Mission 원장, hub, 대형·릴레이, 스케줄러를 소유한다(D-315 4항). 이름 "Fleet"은 이미 와이어 역할(`role=fleet`, `_rosy-fleet._tcp`, `/api/fleet`)과 같다. 그러니 규칙을 이미 만족한다. 패키지 전체를 `site_console`로 바꾸면 화면이 아닌 코드 백여 파일에 화면 이름이 붙는다(대안 절).
- **CORE와 `core_api_web`.** 사람이 여는 앱이 아니라 API다(D-231·D-339 그대로).
- **로봇 LCD(`rosy-boot-display`)와 얼굴(`emotion`).** D-370 2항이 "앱이 아니라 아이콘이 없다"고 정했다. 장치 이미지·systemd 유닛 이름이다.
- **`web_common`.** 라이브러리이고 id·폴더·패키지가 이미 같다.
- **경기 보드(`games`), 제어 진단, 시뮬 라이브 뷰.** D-370 2항 이름표 밖이다(D-370 8항). 사용자가 2026-09-30에 "지금은 바꾸지 않는다"고 정했다(사용자 결정 4). 나중에 원하면 새 ADR 없이 이 규칙으로 행을 더한다.

#### 3. 바꾸지 않는 것과 별칭 기간

**절대 바꾸지 않는다(never).** 이것들은 이미 설치된 로봇 이미지, 사이트 호스트, 폰, 인쇄한 QR, 브라우저 즐겨찾기가 부르는 계약이다. 바꾸려면 새 프로토콜 버전과 이중 광고가 필요하다. 이 ADR의 범위가 아니다.
- mDNS 서비스 종류 `_rosy-overhead._tcp`, `_rosy-fleet._tcp`, `_rosy._tcp`. TXT 값 `role=overhead-camera|fleet|robot`, `proto=rosy-overhead/1|site-v1|core-v1`. 이것들을 광고하는 `fleet-mdns.py`, `rosy-overhead-advertise.service`, `rosy-fleet-advertise.service`, `/etc/avahi/services/rosy-*.service`, 그리고 `--role overhead` 인자도 바꾸지 않는다.
- WS 프로토콜 `rosy-overhead/1`, 경로 `/overhead/v1/frames`, `ROF1` 헤더. Kotlin 클래스 `OverheadLink`·`OverheadServiceRecord`·`OverheadServerDiscovery`, Python `protocol.py` 상수, 시험 속성 `rosy.overhead.vectors`도 와이어를 부르는 이름이라 그대로 둔다.
- REST `/api/fleet/*`(`/api/fleet/sightings`, `/api/fleet/vision/*` 포함)와 `/api/vision/*`.
- 링크 방식 `rosyov://`. 새 앱도 같은 방식을 등록한다.
- 웹 경로 `/dashboard`, `/console`, `/setup`, `/device`, `/pilot`(PWA `start_url`·`scope`·Service Worker 범위), Fleet `/console`, `/common/*`, `/board`. 자산 경로 `/dashboard/assets/*`, `/console/assets/*`, `/pilot/assets/*`도 그대로다. 예외는 `/common/icons/<id>.svg` 하나다. 이 파일 이름은 레지스트리 id를 따르고, 링크하는 HTML이 같은 커밋에서 바뀐다.
- 로봇 쪽 설정 키(`rosy_default.yaml`의 `fleet:`, `vision:`, `fleet_loss_policy`; SD `provision.schema.json`의 `fleet`)와 비밀·환경 변수 이름(`ROSY_PHONE_*`, `ROSY_FLEET_*`, `ROSY_VISION_PREVIEW_SECRET`).
- 브라우저 저장소 키 `rosy.dashboard.*`, `rosy.pilot.*`, `rosy-console-*`. 바꾸면 모든 운용자가 로그아웃되고 설정을 잃는다.
- DB 값과 파일: `device_kind` 기본값 `'overhead-camera'`(`enrollment_store.py:122`), `fleet.sqlite3`, 볼륨 `sighting_data`.
- compose 서비스 이름 `fleet`·`vision`, 이미지 `rosy-site-fleet`·`rosy-site-vision`, 인증서 SAN `fleet`·`vision`. 서비스 이름을 바꾸면 사이트마다 인증서를 다시 발급해야 한다. Vision은 이미 규칙과 맞다(`rosy-` + `site-vision`).
- 로봇 이미지의 `rosy-boot-display.service`와 그 밖의 장치 유닛, mDNS 인스턴스 이름 `ROSY %h`·`ROSY Fleet %h`. 앱이 아닌 것의 이름이다.

**별칭 기간(alias)을 두는 것:**
- Site Vision 실행 파일. `site_vision`이 정본이다. `overhead=site_vision.cli:main`을 **한 사이트 후보 릴리스 동안** 함께 둔다. 운용 문서와 손에 익은 `overhead receive`가 그 동안 돈다. compose와 Dockerfile은 같은 커밋에서 `python3 -m site_vision.cli`로 바꾼다. 다음 후보 릴리스 뒤 단계 5에서 지운다.
- 천장 카메라 폰 앱. applicationId가 바뀌면 **다른 앱으로 설치된다**(4항). 옛 앱은 새 앱의 재페어링을 확인할 때까지만 폰에 남는다.

**지금 바꾸고 별칭을 두지 않는 것:** Python import 경로(`overhead` → `site_vision`, `dashboard` 자산 조회 → `robot_dashboard`), logger 이름, 하네스 모듈 이름, 레지스트리 id, 아이콘 파일 이름, Gradle 이름, DataStore 이름. 이것들을 부르는 곳은 모두 저장소 안에 있고 같은 커밋에서 고친다. `git grep`로 확인한다. 저장소 밖에서 부르는 곳은 없다.

**mDNS 인스턴스 이름 `ROSY Overhead %h`.** 표시용이다. 파서는 서비스 종류와 TXT만 본다(`discovery_txt.py`, `OverheadServiceRecord.kt`). 그래서 단계 1에서 `ROSY Site Vision %h`로 바꾼다. D-370 8항의 해당 질문을 닫는다.

#### 4. Android applicationId를 바꾼 결과

- `io.github.livsbittt.rosy.ceilingcamera`는 새 앱이다. 옛 앱의 DataStore(페어링 호스트·포트·토큰·source)는 옮겨지지 않는다. 앱끼리 사설 저장소를 읽을 수 없기 때문이다. 그래서 DataStore 이름도 `ceiling_camera_settings`로 새로 둔다.
- 두 앱이 함께 설치되면 둘 다 `rosyov://`를 받는다. 그러면 QR을 열 때 선택 창이 뜬다. 또 둘이 같은 `source`로 보내면 Vision의 source당 최신 한 장 규칙과 부딪힌다.
- **재페어링 절차(문서화 의무).** 계획 단계 1의 장치 절차가 정본이다.
  1. 옛 앱에서 송출을 멈추고 옛 앱을 지운다.
  2. 새 APK를 설치한다.
  3. 사이트 QR(`rosyov://…`)이나 D-341 콘솔 승인으로 다시 페어링한다.
  4. 관제 카메라 패널에서 프레임과 sighting을 확인한다.
  5. 옛 폰을 다른 곳에 다시 쓸 거라면 그 source의 폰 토큰을 교체한다.
- 서명 키는 이 결정과 무관하다. 지금 CI는 서명하지 않는다(`android.yml`).

#### 5. 순서 — 진행 중 작업과 부딪히지 않게

1. **단계 0(이 브랜치):** 이 ADR과 계획. 문서만.
2. **단계 1: 천장 카메라 앱 + Site Vision.** `src/site/overhead`를 나눈다. D-362와 겹치지 않는다. 먼저 열린 `feat/camera-preview-rectification`(overhead 9파일)과 `feat/d359-theme-ready`(1파일)의 주인에게 알린다. `git mv`로 옮기므로 병합할 때 이름 바뀜 감지가 따라간다.
3. **단계 2: Pilot 레지스트리 id.** 작다. 아무 때나 할 수 있다.
4. **단계 3: 로봇 대시보드.** **D-362 대시보드 작업이 main에 착지하고 main 체크아웃이 깨끗할 때만** 한다(감지 방법은 계획 §4). 로봇 이미지 릴리스 사이에 한다(D-191). CORE 자산 조회와 이미지 colcon 목록을 같은 커밋에서 고친다.
5. **단계 4: 관제 화면 분리.** 같은 D-362 게이트를 Fleet 서버 쪽에 건다. 열린 Fleet UI 브랜치의 주인에게 알린다.
6. **단계 5: 별칭 제거.** 단계 1을 담은 사이트 후보 릴리스가 한 번 나간 뒤 `overhead` console script를 지운다.

각 단계는 `git mv`로 옮기고, 경로를 부르는 살아 있는 파일(CI, Dockerfile, `.dockerignore`, compose, 배포 스크립트, `harness.yaml`, 아키텍처 시험, `surfaces.yaml`, README·AGENTS·스킬)을 **같은 커밋에서** 고친다. 기록 문서(날짜 붙은 계획, ADR 본문, `logs.md`, `docs/validation`)의 옛 경로는 고치지 않는다(D-226, D-339 결과 절).

### Alternatives

- **표시 이름만 바꾸고 식별자는 둔다(D-370 원안).** 사용자가 2026-09-30에 거부했다. 폴더 `overhead` 하나가 두 역할을 담는 혼동도 남는다.
- **`fleet` 패키지 전체를 `site_console`로 바꾼다.** 거부한다. 화면이 아닌 hub·대형·Mission 원장에 화면 이름이 붙는다. 이는 D-315 4항의 구분(Fleet 서비스 ≠ 사이트 console)과 부딪힌다. 파일 수도 수십 배다(Fleet 안 import 102파일, gz_sim `fleet.bench`, `secret_scan.py` 고정 경로). 이득은 화면 쪽 분리로 이미 얻는다. 사용자가 2026-09-30에 안 B(화면 분리)를 골랐다.
- **와이어 이름도 함께 바꾼다**(`_rosy-ceiling-camera._tcp`, `rosy-ceiling-camera/1`, `/api/site-console/*`). 거부한다. 로봇 이미지·사이트 호스트·설치된 폰이 동시에 바뀌어야 한다. 한 번에 바꿀 수 없어 이중 광고와 버전 협상이 필요하다. 이름 정리가 프로토콜 변경이 된다.
- **폴더만 바꾸고 패키지는 둔다(D-339 방식 연장).** 거부한다. 사용자 요청과 다르고, 대응표 예외가 앱마다 하나씩 늘어난다.
- **Android applicationId는 두고 Kotlin 패키지만 바꾼다.** 재설치를 피할 수 있다. 하지만 사용자는 식별자까지 바꾸라고 했다. 설치된 폰은 한 대뿐이다(현장 설치 전). 그래서 지금 재페어링하는 비용이 가장 작다. 사용자가 2026-09-30에 재설치·재페어링 1회를 받아들였다.

### Consequences

- 앱을 새로 만들 때는 역할 id 하나를 정하고 네 표기를 그 id에서 만든다. `surfaces.yaml` 행, 폴더, 패키지, 아이콘이 같은 커밋에 들어간다.
- 폰 앱을 쓰는 설치자는 한 번 다시 페어링한다(4항).
- 대시보드 패키지 이름이 바뀌므로 로봇 이미지 한 번이 새 share 경로를 싣는다. 개발 PC의 `install/dashboard`는 낡은 채 남는다. 지운 뒤 다시 빌드한다.
- 진행 중 브랜치는 폴더 이동 뒤 병합할 때 이름 바뀜 충돌을 풀어야 할 수 있다. 단계마다 알림과 게이트를 둔다.
- 하네스 모듈 `overhead`는 `site_vision`이 되고, `ceiling_camera` 모듈 기록이 새로 생긴다. `STATUS.md` 행이 바뀐다.

### Validation

- **SOURCE/LOCAL:** 단계마다 옛 이름에 대한 `git grep` 잔여 목록을 커밋 메시지에 남긴다. 기록 문서만 남아야 한다. 영향받는 host pytest 묶음, `test/architecture`, `rosy_harness.py lint` 0 errors, Android `gradlew testDebugUnitTest`를 돌린다. 새 **이름 규칙 시험**(`test/architecture/test_app_identity.py`)이 `surfaces.yaml`의 `app_name`이 있는 행마다 다음을 대조한다: id(kebab) ↔ 폴더 끝 이름(snake) ↔ `package.xml` `<name>` ↔ 아이콘 파일 이름 ↔ Android `applicationId`(compact).
- **DEVICE:** 새 APK 설치, 재페어링, 관제에서 프레임과 sighting 확인. 대시보드는 새 로봇 이미지에서 `/dashboard`, Pilot은 `/pilot`이 열리는지 본다. 호스트 시험 통과는 DEVICE가 아니다.
- 원래 조건은 "단계 1이 main에서 녹색이고 사용자가 열린 질문 2·3에 답하면 Accepted"였다. 사용자가 2026-09-30에 질문 1–3에 답하고 Accepted로 올렸다(Status의 사용자 결정). 단계 1은 위 SOURCE/LOCAL 검증이 녹색이어야 병합한다.

### References

실행 계획: [2026-09-30-app-identity-rename-plan.md](../plans/2026-09-30-app-identity-rename-plan.md) (부록 A 조사 표, 부록 B 열린 브랜치). `src/hmi/web_common/surfaces.yaml`, `src/hmi/web_common/manifest.json`, `src/site/overhead/android/app/build.gradle.kts`, `src/site/overhead/android/settings.gradle.kts`, `src/site/overhead/setup.py`, `src/site/fleet/fleet/server/static_routes.py`, `src/runtime/api_web/core_api_web/api/app.py`, `deploy/site/compose.yaml`, `deploy/site/fleet-mdns.py`, `tools/harness/harness.yaml`, `test/architecture/test_target_layout.py`, `test/architecture/test_module_structure.py`.
