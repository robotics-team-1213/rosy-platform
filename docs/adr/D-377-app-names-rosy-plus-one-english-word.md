## D-377 앱 이름 규칙: Rosy + 영어 한 단어 — 표시 이름·id·폴더·패키지·Android id가 그 한 단어에서 나온다

**Status:** Accepted (2026-09-30, 사용자 결정). 이름 규칙과 앱별 대응표만 정한다. 이 ADR 자체는 코드를 바꾸지 않는다. 실행은 [D-374 계획](../plans/2026-09-30-app-identity-rename-plan.md)의 단계가 한다. 단계 1(천장 카메라 앱·Site Vision)은 이미 D-374 이름으로 main에 있으므로 브랜치 `refactor/app-naming-cam-vision`이 이 규칙의 이름으로 다시 옮긴다. 단계 3·4·5의 게이트는 그대로다.

**사용자 결정 (2026-09-30):** "Rosy 천장 카메라" 같은 표시 이름을 거부했다. 이름 **규칙**을 먼저 정하고 모든 앱 이름을 그 규칙에서 다시 만들라고 했다. 규칙은 "Rosy + 영어 한 단어"다(1항).

**부분 대체:**
- [D-370](D-370-site-app-roles-names-and-shared-link.md) 2항 이름표를 대체한다. 한국어 이름(`Rosy 천장 카메라`, `Rosy 관제`, `Rosy 로봇 대시보드`)과 영어 이름(`Rosy Ceiling Camera`, `Rosy Site Console`, `Rosy Robot Dashboard`)은 2항 표의 표시 이름으로 바뀐다. 한국어는 설명·부제에만 남는다. D-370의 역할 표(1항), 아이콘 가족 규칙(3항), 화면 소유(4항), 통신 통합(5항)은 그대로다.
- [D-374](D-374-app-identity-follows-one-role-name.md) 1항(규칙)과 2항(대응표)을 대체한다. 역할 id의 원천이 "D-370 영어 이름 − `Rosy`"에서 "표시 이름의 영어 한 단어"로 바뀐다. 그래서 `ceiling-camera`·`site-vision`·`site-console`·`robot-dashboard`가 `cam`·`vision`·`console`·`robot`이 된다. D-374 1항의 "`rosy_` 접두를 붙이지 않는다(D-147)"도 대체한다: 앱 패키지는 `rosy_<word>`다(1항).
- D-374 3항(바꾸지 않는 와이어 식별자), 4항(applicationId 변경 결과와 재페어링 절차), 5항(단계 순서와 게이트)은 그대로다. 3항 별칭 목록만 2항 아래처럼 늘어난다.

잇는 결정: [D-147](D-147-src-6.md) · [D-226](D-226-document-placement-and-publication-criteria.md) · [D-231](D-231-layered-source-roots-keep-package-names.md) · [D-339](D-339-surface-and-folder-role-names.md) · [D-345](D-345-design-philosophy-reaches-every-surface.md) · [D-370](D-370-site-app-roles-names-and-shared-link.md) · [D-372](D-372-topic-branch-names-and-shared-checkout-wip.md) · [D-374](D-374-app-identity-follows-one-role-name.md).

### Context

D-374는 이름을 D-370 2항의 영어 이름에서 기계적으로 뽑았다. 그래서 여러 낱말 이름이 모든 자리로 퍼졌다: `ceiling_camera`, `io.github.livsbittt.rosy.ceilingcamera`, `rosy-ceiling-camera`, `site_vision`. 표시 이름도 한국어와 영어가 섞였다("Rosy 천장 카메라"). 단계 1(`refactor/d374-s1-ceiling-camera-site-vision`)은 main에 착지했다. 단계 3·4(대시보드·관제 화면)는 아직 게이트 뒤라 옮겨지지 않았다.

패키지 이름 `vision`·`robot`·`console`은 너무 일반적이다. ROS 배포판·PyPI·다른 저장소 패키지와 겹칠 수 있다. 그래서 패키지에만 브랜드 접두를 붙인다.

### Decision

#### 1. 규칙

앱마다 역할을 나타내는 **영어 명사 한 단어** `<Word>`를 정한다. 나머지 이름은 모두 그 단어에서 나온다.

| 자리 | 형식 | 예 (Cam) |
|---|---|---|
| 표시 이름 (런처·PWA `name`·`short_name`, `app_name`, 페이지 `<title>`) | `Rosy <Word>` (title case) | `Rosy Cam` |
| 레지스트리 id (`surfaces.yaml` `id`) | `<word>` (소문자) | `cam` |
| 폴더 | `src/<영역>/<word>` | `src/site/cam` |
| Python·ROS·colcon 패키지 | `rosy_<word>` | (Cam은 ROS 패키지가 아니다) |
| console script | `rosy-<word>` | — |
| Android `applicationId`·`namespace`·Kotlin 패키지 | `io.github.livsbittt.rosy.<word>` | `io.github.livsbittt.rosy.cam` |
| Gradle `rootProject.name` | `rosy-<word>` | `rosy-cam` |
| 아이콘 파일 | `src/hmi/web_common/icons/<word>.svg` | `cam.svg` |
| 하네스 모듈 | 패키지가 있으면 패키지 이름, 없으면 `<word>` | `cam` |

- **표시 이름에 한국어를 쓰지 않는다.** 한국어는 설명·부제·안내 문구에만 쓴다. D-345 4항("`Rosy <이름>`, `short_name`도 `Rosy`로 시작")은 이 규칙으로 만족된다.
- **한 단어**다. 두 낱말이 필요해 보이면 역할이 둘인지 먼저 본다(D-370 1항). 단어는 영어 명사이고 `[a-z]+`만 쓴다. 그래서 kebab·snake·compact 표기 구분(D-374 1항)이 필요 없다.
- **폴더 끝 이름과 패키지 이름은 `rosy_` 접두 하나만 다르다.** 앱 폴더는 `test_module_structure.py` `ROLE_DIR` 표 대신 이 규칙으로 대조한다(`test/architecture/test_app_identity.py`).
- 영역 폴더(`src/site`, `src/hmi`)는 D-243·D-315 그대로다.
- **와이어 계약을 부르는 이름은 앱 이름이 아니라 와이어를 따른다**(D-374 1항 마지막 줄, 3항). 이 규칙은 와이어 이름을 바꾸지 않는다.

#### 2. 대응표

| 앱 | 표시 이름 | id | 폴더 | 패키지 | Android ID | 아이콘 | 단계 |
|---|---|---|---|---|---|---|---|
| 천장 카메라 앱 | Rosy Cam | `cam` | `src/site/cam` (D-374: `src/site/ceiling_camera`) | — (`COLCON_IGNORE`) | `io.github.livsbittt.rosy.cam` (D-374: `…ceilingcamera`) | `cam.svg` | 1 (다시 옮김) |
| Site Vision | Rosy Vision | `vision` | `src/site/vision` (D-374: `src/site/site_vision`) | `rosy_vision` (D-374: `site_vision`) | — | 없음(화면 없는 서비스, D-370 2항) | 1 (다시 옮김) |
| 사이트 관제(Fleet 화면) | Rosy Console | `console` | `src/site/console` (D-374 계획: `src/site/site_console`) | `rosy_console` (계획: `site_console`) | — | `console.svg` | 4 (게이트 그대로) |
| 로봇 대시보드 | Rosy Robot | `robot` | `src/hmi/robot` (계획: `src/hmi/robot_dashboard`) | `rosy_robot` (계획: `robot_dashboard`) | — | `robot.svg` | 3 (게이트 그대로) |
| 조종 | Rosy Pilot | `pilot` | `src/hmi/pilot` (그대로) | `pilot` (그대로, 아래) | — | `pilot.svg` | 2 (이미 규칙) |

- **Rosy Pilot의 패키지 `pilot`은 지금 바꾸지 않는다.** 사용자 결정의 표가 "unchanged"로 정했다. `rosy_pilot`로 옮기는 일은 단계 3과 함께 판단한다.
- **Rosy Console과 Rosy Robot의 아이콘 파일과 레지스트리 id·표시 제목은 지금 바꾼다**(단계 1 브랜치). 폴더·패키지 이동만 단계 3·4 게이트를 기다린다. 아이콘 파일은 `/common/icons/<id>.svg`로만 불리고 링크하는 HTML이 같은 커밋에서 바뀐다(D-374 3항 예외와 같다).
- 페이지 제목: 관제 화면 `<title>`은 `Rosy Console`, 로봇 대시보드는 `Rosy Robot`이다. D-339 4항의 `Rosy <범위> — <화면 이름>` 탭 제목 중 표면 이름 자리는 이 표시 이름으로 읽는다. 한국어 화면 이름은 부제로 남는다.
- **범위 밖(그대로):** Fleet 서비스 `src/site/fleet`·패키지 `fleet`, CORE, LCD, `emotion`, `web_common`, 경기 보드 `games`, 제어 진단, 시뮬 라이브 뷰. 이유는 D-374 2항과 같다.

#### 3. 별칭

- **Rosy Vision 실행 파일.** 정본은 `rosy-vision=rosy_vision.cli:main`이다. 옛 이름 `site_vision`(D-374 단계 1)과 `overhead`(D-374 이전)를 **한 사이트 후보 릴리스 동안** 별칭으로 둔다. 둘 다 `setup.py`에 "제거 예정(D-377, 단계 5)" 주석을 단다. 단계 5가 둘을 함께 지운다.
- compose와 Dockerfile은 같은 커밋에서 `python3 -m rosy_vision.cli`로 바꾼다.
- mDNS 인스턴스 표시 이름은 `ROSY Vision %h`다(D-374의 `ROSY Site Vision %h` 대체). 파서는 서비스 종류와 TXT만 본다.
- **Rosy Cam 폰 앱.** applicationId가 다시 바뀐다. `…rosy.ceilingcamera`는 main에만 있고 현장 폰에 설치된 적이 없다. 그래서 재페어링은 여전히 D-374 4항의 한 번이다(옛 `…rosy.overhead` → `…rosy.cam`). DataStore 이름은 `cam_settings`, 인텐트 action은 `io.github.livsbittt.rosy.cam.action.*`이다.

#### 4. 바꾸지 않는 것

D-374 3항 목록 전부가 그대로다: mDNS 종류와 TXT 값, `rosy-overhead/1`, `/overhead/v1/frames`, `ROF1`, Kotlin `Overhead*` 클래스 이름, `/api/vision/*`, `/api/fleet/*`, `rosyov://`, 웹 경로 `/console`·`/dashboard`·`/pilot`, 브라우저 저장소 키, compose 서비스·이미지·SAN, `device_kind`, `ROSY_OVERHEAD_TOKEN`, Fleet 서비스 패키지 `fleet`, LCD, `web_common`.

### Alternatives

- **D-374 이름을 그대로 둔다**(`Rosy 천장 카메라`, `ceiling_camera`, `site_vision`). 사용자가 2026-09-30에 거부했다.
- **패키지에도 접두 없이 `<word>`만 쓴다**(`vision`, `robot`, `console`). 거부한다. 일반 이름이라 ROS·Python 생태계의 다른 패키지와 겹칠 수 있다. 폴더는 저장소 안에서만 쓰이므로 짧게 둔다.
- **폴더도 `rosy_<word>`로 둔다.** 거부한다. 모든 폴더가 같은 접두로 시작해 읽기 어렵다. 사용자 표가 `src/site/vision`을 정했다.
- **표시 이름을 한국어로 둔다.** 거부한다. 사용자 결정이다. 한국어는 부제로 충분하다.

### Consequences

- 새 앱은 영어 단어 하나를 정하고 1항 표의 모든 자리를 같은 커밋에서 만든다.
- 단계 1의 폴더·패키지·applicationId를 한 번 더 옮긴다. 단계 1 이름으로 열린 브랜치(`feat/overhead-app-site-ca-pin` 등)는 병합 때 이름 바뀜을 한 번 더 따라가야 한다.
- 단계 3·4의 목표 폴더·패키지 이름이 바뀐다. 계획 2.4·2.5·3항을 고친다.
- `test_app_identity.py`가 새 규칙(id = 폴더 끝, 패키지 = `rosy_<id>`, 아이콘 = `<id>.svg`, applicationId 마지막 마디 = id, 표시 이름 = `Rosy <Word>`)을 대조한다.

### Validation

- **SOURCE/LOCAL:** `test_app_identity.py`와 영향받는 host pytest, `rosy_harness.py lint` 0 errors, Android `gradlew testDebugUnitTest assembleDebug`. 옛 이름(`ceiling_camera`, `ceilingcamera`, `site_vision`, `ceiling-camera`, `site-vision`) `git grep` 잔여는 기록 문서와 별칭 줄만 남아야 한다.
- **DEVICE:** 새 APK(`io.github.livsbittt.rosy.cam`) 설치, 런처 이름 `Rosy Cam`, 재페어링, 관제에서 프레임·sighting 확인(D-374 4항 절차). 호스트 시험 통과는 DEVICE가 아니다.

### References

[D-374 실행 계획](../plans/2026-09-30-app-identity-rename-plan.md), `src/hmi/web_common/surfaces.yaml`, `test/architecture/test_app_identity.py`, `tools/harness/harness.yaml`.
