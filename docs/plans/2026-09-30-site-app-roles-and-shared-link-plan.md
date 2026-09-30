# 앱 역할·이름·아이콘·화면 소유와 공유 연결 조각 실행 계획

**결정:** [D-370](../adr/D-370-site-app-roles-names-and-shared-link.md) Proposed.

**현재 상태:** 문서만 있다(2026-09-30). 각 단계는 따로 커밋할 수 있다. 단계마다 **실패하는 시험을 먼저** 쓰고, 적신을 확인한 뒤 구현한다(TDD). 새 검사는 변이 증명으로 믿는다(test/AGENTS 규약). 한 번 일부러 어기고 적신을 본 뒤 되돌린다.

**공통 규칙:**
- Windows 호스트는 `python`으로 돌린다(PyYAML 때문, `python3` 아님).
- pytest 임시 폴더는 `--basetemp X:\DevTemp\<session>\pt`에 둔다.
- 장치에 연결하지 않는다. 모든 단계는 SOURCE/LOCAL 증거다.
- 단계를 마칠 때마다 해당 모듈 `logs.md`에 항목을 쓰고, `python tools/harness/rosy_harness.py generate` → `lint`를 돈다.

## 확인한 출발점

| 경계 | 확인한 사실 | 이 계획의 단계 |
|---|---|---|
| TXT 파서 | Python 네 벌(`fleet-mdns.py`, `fleet_agent/discovery.py` 복사본, `mdns-bridge.py`, `fleet/server/discovery.py`), Kotlin 한 벌. `mdns-bridge.py`는 공통 키를 보지 않는다 | S1 |
| 벡터 선례 | `src/site/overhead/protocol/vectors.json`을 Kotlin(`rosy.overhead.vectors`)과 Python이 함께 읽는다 | S1이 같은 방식을 쓴다 |
| 역할 시험 | `test_no_video_relay.py`, `test_module_separation.py:186`(단일 `cmd_vel`)은 있다. 카메라 앱·Vision·Pilot의 역할 경계 시험은 없다 | S2 |
| 이름·아이콘 | 폰 런처 아이콘이 없다(`AndroidManifest.xml`에 `android:icon` 없음). 웹 파비콘이 없다. Pilot `short_name`이 `Pilot`이다(브랜치) | S3 |
| 화면 소유 | 대시보드 `console.teleop`과 Pilot이 겹친다. Pilot "관제 화면" 버튼(브랜치) | S4 |
| 기기 연결 | D-341·D-352 브랜치가 `device_pairing_audit`와 "기기 연결" 패널을 먼저 착지하는 쪽이 만들기로 했다 | S5 |
| 실패 분류 | `NetworkFailure`가 `feat/overhead-app-ceiling-ux`에 있다 | S6 |
| 전송 | Fleet → CORE WS가 `?token=`을 쓴다(`swarm/robots.py:122-131`) | S7 |

## S1 — 발견 TXT 공유 벡터와 파서 (가장 싸고 효과가 크다)

**파일**
- 새로 만든다: `test/fixtures/protocol/discovery-txt.v1.json`
- 새로 만든다: `src/contracts/foundation/core_common/protocol/discovery_txt.py`. 표준 라이브러리만 쓴다. `parse_txt_pairs`, `classify(service_type, host, address, port, txt) -> Accepted|Rejected(reason)`, `legacy` 표시를 둔다.
- 새로 만든다: `src/contracts/foundation/test/test_discovery_txt_vectors.py`
- 새로 만든다: `test/test_discovery_txt_profile_parity.py`. 벡터 ↔ `docs/reference/site-lan-discovery-profile.md` 표를 대조한다.
- 고친다: `src/runtime/services/core_features/fleet_agent/discovery.py`. 복사된 `TXT`와 `parse_avahi` 판정을 `core_common` import로 바꾼다.
- 고친다: `src/site/fleet/fleet/server/discovery.py`. 행 검사를 같은 분류로 바꾼다. Fleet은 `core_common`만 import할 수 있다(`test_fleet_prod_only_core_common`).
- 고친다: `deploy/site/mdns-bridge.py`와 `deploy/site/fleet-mdns.py`. 단독 스크립트이므로 사본을 유지하되 공통 키를 검사한다. 공통 키가 없는 옛 광고는 `legacy`로 통과시킨다.
- 고친다(시험 추가): `test/test_site_mdns_bridge.py`, `test/test_site_fleet_mdns.py`. 같은 벡터 파일을 돈다.
- 고친다: `src/site/overhead/android/app/build.gradle.kts`. 시스템 속성 `rosy.discovery.vectors`를 추가한다(`../../../../test/fixtures/protocol/discovery-txt.v1.json`).
- 새로 만든다: `app/src/test/java/io/github/livsbittt/rosy/overhead/settings/DiscoveryVectorsTest.kt`
- 고친다: `OverheadServiceRecord.kt`. 거절 사유를 벡터 어휘로 낸다.

**순서**
1. 벡터를 쓴다. 서비스 종류 셋에 대해 받는 사례와 거절 사례를 담는다: `duplicate_key`, `value_mismatch`, `missing_key`, `tls_host_mismatch`, `bad_address`(링크 로컬·공인·IPv6), `ap_mode`, 알 수 없는 키 무시, 옛 로봇 광고 `legacy`. 각 사례의 기대 사유를 적는다.
2. 프로필 대조 시험을 적신으로 본다(파일이 없는 상태). 벡터를 추가해 녹색으로 만든다.
3. `test_discovery_txt_vectors.py`를 적신으로 본다(모듈이 없는 상태). `discovery_txt.py`를 구현한다.
4. 브리지·광고 스크립트 시험에 벡터 루프를 더한다. `mdns-bridge.py`는 `value_mismatch` 사례에서 적신이 나야 한다(D-382 발견 8). 그 뒤 고친다.
5. FleetAgent·Fleet 서버를 `core_common`으로 옮긴다. 기존 시험(`test_fleet_agent_mdns.py`, `src/site/fleet/test/test_discovery.py`)은 녹색이어야 한다.
6. Kotlin `DiscoveryVectorsTest`를 적신으로 본 뒤 파서 사유를 맞춘다.

**수용 기준**
- `python -m pytest src/contracts/foundation/test/test_discovery_txt_vectors.py test/test_discovery_txt_profile_parity.py test/test_site_mdns_bridge.py test/test_site_fleet_mdns.py -q`가 녹색이다.
- `python -m pytest src/runtime/gateway/test/test_fleet_agent_mdns.py src/site/fleet/test/test_discovery.py -q`가 녹색이다.
- `src/site/overhead/android`에서 `gradlew testDebugUnitTest`가 녹색이다.
- 변이 증명 두 가지를 한다. 벡터의 기대 사유 하나를 바꿔 Python·Kotlin이 **모두** 적신이 되는지 본다. `mdns-bridge.py`의 공통 키 검사를 지워 적신을 본다.
- `grep -n 'TXT = {' src/runtime/services/core_features/fleet_agent/discovery.py`가 비어 있다(복사본 제거).
- 영향: `deploy/site`, `fleet`, `core_common`, `overhead` 모듈 `logs.md`.

## S2 — 역할 경계 시험 (역할 표를 코드로 고정)

**파일**
- 새로 만든다: `test/architecture/test_app_roles.py`
- 고친다: `src/hmi/web_common/surfaces.yaml`. 표면마다 `role:` 한 줄(D-370 1항 요약)과 `owns:` 목록을 둔다. D-339 레지스트리 시험이 빈 칸을 거절한다.
- 고친다: `src/hmi/web_common/test/` 레지스트리 시험(기존 파일에 `role`·`owns` 필수 검사를 추가한다).

**검사**
1. 천장 카메라 앱 `app/src/main/java`에 `/api/v1/`, `/api/fleet/`(D-341 `pairing/v1` 제외), `cmd_vel`, `estop` 문자열이 없다.
2. Vision `src/site/overhead/overhead`에 CORE URL(`/api/v1/`), `cmd_vel`, Fleet 명령 라우트 호출이 없다. Fleet에는 `/api/fleet/sightings`만 쓴다.
3. Fleet은 기존 `test_no_video_relay.py`를 유지한다. 라우트 정규식을 통과하는 `vision/lease`·`vision/sources`는 **lease만 발급한다**는 사실을 허용 목록으로 명시한다(응답에 바이트가 없음을 검사).
4. Pilot 시험(`src/hmi/pilot`의 `/api/fleet` 부재)은 Pilot이 main에 착지하는 커밋에서 활성화한다. 그 전에는 경로가 없을 때 `pytest.skip`이 아니라 **대상 목록에서 빠진 것으로** 둔다(가짜 녹색 금지).
5. `surfaces.yaml`의 `owns` 항목이 두 표면에 겹치면 실패한다. 예외는 `estop` 하나다(D-370 4항).

**수용 기준**
- 각 검사에서 금지 문자열을 임시로 넣어 적신을 확인한다(변이 증명).
- `python -m pytest test/architecture/test_app_roles.py src/hmi/web_common/test -q`가 녹색이다.
- 적신이 되는 첫 결과는 **현재 겹침**이어야 한다. 대시보드 `teleop` ↔ Pilot(착지 전이면 없음)이다. 이행기 겹침은 `transitional: D-370 4항 1`로 표시해 허용한다.

## S3 — 이름과 아이콘

**파일**
- 새로 만든다: `src/hmi/web_common/icons/overhead-camera-app.svg`, `pilot.svg`, `fleet-console.svg`, `robot-dashboard.svg`. 108×108이고 안전 영역은 가운데 66이다. 오른쪽 위에 `--brand-rose` 점을 둔다. 바탕은 `--ground`다.
- 새로 만든다: `src/hmi/web_common/test/test_surface_icons.py`. 다음을 검사한다:
  - SVG 색이 `tokens.css` 값과 같다.
  - 네 SVG의 흑백 실루엣이 서로 다르다. 도형 목록 비교로 한다.
  - `status-*` 색을 쓰지 않는다.
  - `surfaces.yaml`의 `icon:` 경로가 있다.
- 고친다: `surfaces.yaml`. `app_name`, `app_name_en`, `short_name`, `icon`을 추가한다(D-370 2항 표).
- Android(`src/site/overhead/android/app/src/main/res/`):
  - `mipmap-anydpi-v26/ic_launcher.xml`, `ic_launcher_round.xml`
  - `drawable/ic_launcher_foreground.xml`, `drawable/ic_launcher_monochrome.xml`
  - `values/ic_launcher_background.xml`
  - `AndroidManifest.xml`의 `android:icon`·`android:roundIcon`
  - `values/strings.xml`: `app_name` 유지. 영어 이름은 `values-en/strings.xml`을 둘지 D-370 8항을 따른다.
- 새로 만든다: `src/site/overhead/android/app/src/test/.../ui/LauncherIconParityTest.kt`. 벡터 드로어블 경로와 색이 SVG 원본과 같다(`rosy.icons.dir` 시스템 속성).
- 웹:
  - `src/site/fleet/fleet/server/web/index.html`, `src/hmi/dashboard/index.html`, `src/hmi/dashboard/surface.html`에 `<link rel="icon" type="image/svg+xml" href="/common/icons/<id>.svg">`를 넣는다.
  - `src/hmi/web_common/manifest.json` `shared_assets`에 네 SVG를 추가한다. 이것이 경로 순회 방어 허용 목록이므로 폴더를 통째로 열지 않는다.
- 새로 만든다: `tools/icons/render_png.py`. Pillow로 SVG 도형 목록을 512 px PNG로 그린다(배포 목록·문서용). 산출물은 저장소에 두지 않는다. 필요할 때만 X:에 만든다.
- Pilot(착지 회차, `feat/pilot-teleop` 쪽): `manifest.webmanifest`의 `short_name` → `Rosy Pilot`, 아이콘 PNG 세 개를 `pilot.svg`로 다시 만들고, `index.html:22`의 "관제 화면" → "로봇 대시보드"로 바꾼다.

**순서**
1. `test_surface_icons.py`와 레지스트리 필드 검사를 적신으로 본다.
2. SVG 네 개와 레지스트리를 쓴다.
3. Android 패리티 시험을 적신으로 본 뒤 리소스를 쓴다.
4. 파비콘 링크를 넣고 서빙 시험(`/common/icons/...` 200, 목록 밖 404)을 확인한다.

**수용 기준**
- 호스트 시험이 녹색이고 `gradlew testDebugUnitTest assembleDebug`가 녹색이다.
- G2: 네 아이콘을 48 dp·흑백·원형 마스크로 나란히 캡처한다. `X:\DevTemp\<session>`에 두고 사용자에게 보인 뒤 확인을 기록한다.
- DEVICE(별도 회차): 실제 폰 런처에서 아이콘과 이름을 본다.

## S4 — 화면 소유 정리

**파일**
- 고친다: `src/hmi/dashboard/panels.yaml`. `console.teleop`에 `transitional: "D-370 4항 1 — Pilot DEVICE 수용 뒤 링크 패널로"`를 둔다.
- 새로 만든다(전환 회차): `src/hmi/dashboard/panels/console/pilot-link.js`. "Rosy Pilot으로 조종" 링크만 있고 명령 호출이 없다.
- 천장 카메라 앱: 설정 화면에 "로봇 정지는 관제에서" 안내 한 줄과 관제 주소 링크를 넣는다(`res/values/strings.xml`, 설정 화면 Composable). 명령 호출은 넣지 않는다.
- 로봇 대시보드: 사이트에 등록된 로봇이면 개요 패널에 "사이트 관제" 링크를 둔다. 주소는 D-352 등록부에서 오지 않으므로 이번 범위에서는 수동 설정값만 쓴다. 없으면 표시하지 않는다.
- 고친다: `test/test_dashboard_browser.py`(또는 패널 계약 시험). `transitional` 패널이 새 기능을 더하지 않았는지 확인한다. 패널 모듈 해시나 크기 예산을 스냅샷으로 비교한다.

**수용 기준**
- S2의 `owns` 겹침 검사가 `transitional` 하나만 허용하고 다른 겹침은 적신이다.
- 정지 버튼 존재 시험: 대시보드 `console`, Fleet 관제, Pilot(착지 후)에 정지 컨트롤이 있다. 천장 카메라 앱에는 **정지 호출이 없다**(S2 검사 1).
- Pilot DEVICE 수용 전에는 teleop 패널을 링크로 바꾸지 않는다. 바꾸는 커밋은 D-323 Validation 증거를 인용한다.

## S5 — 기기 연결 용어·감사·관리 위치 (D-341·D-352 착지와 함께)

**파일**(먼저 착지하는 쪽의 파일에 더한다)
- `src/site/fleet/fleet/server/enrollment_store.py`(D-352) 또는 D-341의 페어링 저장소: `device_pairing_audit.device_kind`의 허용 값 목록을 한 상수로 둔다(`overhead-camera`, `robot`, 예약 `fleet-agent`).
- 새로 만든다: `src/site/fleet/test/test_device_link_vocabulary.py`. 다음을 검사한다:
  - 패널 제목이 "기기 연결"이다.
  - 구역 동사가 "등록"·"연결 승인"이다.
  - 감사 열 집합이 같다.
  - 응답·로그에 원문 토큰 문자열이 없다.
- 고친다: `docs/reference/site-lan-discovery-profile.md`. D-341 14항 `pair` 키를 표에 추가한다(S1 벡터와 같은 커밋).

**수용 기준**
- 두 절차의 감사 행이 같은 열로 쓰인다. 호스트 통합 시험에서 카메라 승인 한 번과 로봇 등록 한 번으로 확인한다.
- 로봇 쪽 목록·회수 화면은 대시보드 보안 패널에만 있다. Fleet 쪽 목록에서 로봇 발급 토큰을 회수하는 경로는 D-352 6항(해제 = logout)뿐이다.

## S6 — 실패 분류 공유 벡터

**파일**
- 새로 만든다: `test/fixtures/protocol/failure-classes.v1.json`. 입력(예외 종류, HTTP 상태, 오류 코드, WS 닫힘 코드)과 분류 사이의 표다.
- 고친다: 천장 카메라 앱 `link/NetworkFailure.kt`. `feat/overhead-app-ceiling-ux`가 착지한 뒤 `AUTH_FINAL`, `AUTH_RETRY`, `FORBIDDEN`, `PROTOCOL_MISMATCH`, `BUSY`, `CONFLICT`를 더하고 닫힘 코드도 분류한다.
- 새로 만든다: `app/src/test/.../link/FailureClassVectorsTest.kt`
- 웹(D-340 6항 회차): `src/hmi/web_common/link.js`(공유 fetch·WS 재연결·분류)와 `src/hmi/web_common/test/link.test.mjs`가 같은 벡터를 `node --test`로 돈다. `manifest.json` 허용 목록에 추가한다.

**수용 기준**
- 4401 → `auth_final`(재시도 멈춤), 4503 → `auth_retry`(자격 유지·백오프)를 Kotlin·JS가 같게 낸다.
- 벡터 한 줄을 바꿔 두 언어가 모두 적신이 되는지 본다.

## S7 — 전송·공개 상태 정리 (D-382 스냅샷 회차와 함께)

**파일**
- 고친다: `src/site/fleet/fleet/swarm/robots.py`(`ws_url`)와 `transport.py:222-228`. 토큰을 URL에서 빼고 첫 메시지 `{type:"auth", token}`으로 보낸다.
- 고친다: `src/site/fleet/test/`의 transport 시험. URL에 `token=`이 없다는 것을 검사한다.
- 고친다: Fleet `/healthz`(`server/app.py:438`), Vision `/healthz`(`ingest.py:170-171`). `role`·`proto`·`contract_version` 필드를 더한다(추가만).
- 고친다: `deploy/site/fleet-mdns.py`의 health 탐침. `role`·`proto`가 TXT와 같은지 대조한다.
- 그 뒤 별도 커밋: CORE `api/ws.py`의 `?token=` 수용을 닫는다. 시험 `test_ws_query_token_rejected`를 둔다.

**수용 기준**
- Fleet 시험 전체가 녹색이고, `git grep -n "token=" src/site/fleet/fleet/swarm`에 URL 조립이 없다.
- 이미지 버전 호환: 옛 CORE 이미지(첫 메시지 인증 이전 판)가 있으면 제거 커밋을 미룬다. 판정은 D-382 `contract_version`으로 한다.

## S8 (조건부) — Android 공유 모듈

두 번째 Kotlin 앱이 기록된 요구로 생길 때만 한다(D-370 5.6).
- `apps/android-link/`에 Gradle included build를 둔다. 폴더에 `COLCON_IGNORE`를 둔다.
- 내용: NSD 발견, CA 고정 OkHttp, 설정 저장, 실패 분류.
- 두 앱의 `settings.gradle.kts`에 `includeBuild`를 넣는다.
- S1·S6 벡터 시험은 모듈 안으로 옮긴다.

## 완료 판정

- S1–S3이 main에서 녹색이고, 사용자가 역할 표와 D-370 8항 질문을 확인하면 D-370을 Accepted로 올린다.
- S4–S7은 각각 연관 브랜치 착지에 묶인다. 이 계획의 진행표에 착지 커밋을 적는다.
- 모든 단계 증거는 SOURCE/LOCAL이다. DEVICE(실제 폰 런처, 실제 사이트 LAN 발견)는 별도 회차다.
