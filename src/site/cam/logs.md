# ceiling_camera logs

추가만 한다. 형식: [module harness 설계](../../../docs/plans/2026-09-15-module-harness-design.md) §4.2.

이 모듈의 2026-09-30 이전 이력은 [`src/site/vision/logs.md`](../vision/logs.md)의 2026-09-30 이전 항목(`overhead-app`)이다.

## 2026-09-30 · uncommitted · refactor(ceiling-camera): D-374 stage 1 — split the phone app out of overhead

- 변경: `src/site/overhead/android` → `src/site/ceiling_camera`(`git mv`). `applicationId`·`namespace`·Kotlin 패키지 `io.github.livsbittt.rosy.overhead` → `io.github.livsbittt.rosy.ceilingcamera`, Gradle `rootProject.name` `rosy-ceiling-camera`, DataStore `ceiling_camera_settings`. 프로토콜 벡터는 `test/fixtures/protocol/overhead-ingest.v1.json`으로 옮겼고 JVM 시험 경로를 고쳤다. 런처 아이콘 원본은 `web_common/icons/ceiling-camera.svg`. 레지스트리 id `ceiling-camera`. 와이어 이름은 그대로(D-374 3항).
- 증거: `gradlew testDebugUnitTest assembleDebug` BUILD SUCCESSFUL, JVM 시험 130 passed, APK `app/build/outputs/apk/debug/app-debug.apk`의 applicationId `io.github.livsbittt.rosy.ceilingcamera` (2026-09-30 Windows, JDK 21).
- gate 변화: 새 모듈. SOURCE/LOCAL GO, DEVICE/FIELD PARKED(새 APK 설치·재페어링 전).

## 2026-09-30 · uncommitted · refactor(cam): D-377 ceiling_camera becomes Rosy Cam in src/site/cam
- 변경: `src/site/ceiling_camera` → `src/site/cam`(`git mv`, 이동 커밋 분리). `applicationId`·`namespace`·Kotlin 패키지 `io.github.livsbittt.rosy.cam`, `rootProject.name` `rosy-cam`, `app_name` `Rosy Cam`, DataStore `cam_settings`, 인텐트 action `io.github.livsbittt.rosy.cam.action.*`, 런처 아이콘 원본 `web_common/icons/cam.svg`(주석·`LauncherIconParityTest`). 하네스 모듈 `ceiling_camera` → `cam`.
- 증거: `gradlew testDebugUnitTest --rerun assembleDebug` BUILD SUCCESSFUL, JVM 시험 130 passed, 0 failed (2026-09-30 Windows, JDK 21). APK `src/site/cam/app/build/outputs/apk/debug/app-debug.apk`.
- gate 변화: 없음. SOURCE/LOCAL GO, DEVICE/FIELD PARKED(새 APK 설치·재페어링 전). `…rosy.ceilingcamera`는 현장에 설치된 적이 없어 재페어링은 여전히 한 번(`…rosy.overhead` → `…rosy.cam`).
- 결정: D-377. `Overhead*` 클래스와 와이어 이름은 그대로.

## 2026-09-30 · 5358ce49 · feat(cam): ultra-wide lens (화각 넓게/기본)
- 변경: `LensSelector`(순수, JVM 시험 12개)가 후면 카메라 중 가로 화각이 가장 넓은 것(초점거리 `LENS_INFO_AVAILABLE_FOCAL_LENGTHS` 최솟값과 `SENSOR_INFO_PHYSICAL_SIZE` 긴 변으로 계산, 물리 카메라 우선)을 WIDE로, CameraX 첫 후면 카메라를 STANDARD로 고른다. 3° 이상 넓지 않으면 WIDE는 STANDARD로 물러나고 화면이 그렇게 말한다. `LensProbe`가 `Camera2CameraInfo`로 특성을 읽고, `CameraController`는 카메라 필터로 그 id를 바인딩한다. 설정 `lens`(DataStore `cam_settings`, `wide`|`standard`, 미설정이면 wide)를 연결 설정 화면의 "화각"에서 고른다. 촬영 중 바꾸면 다시 바인딩(적응 JPEG 품질 초기화, 타임스탬프 소스·센서 크기 다시 읽기)하고 링크를 즉시 다시 연결해 새 hello를 보낸다. 송출 화면·알림에 "렌즈: 초광각 2.2 mm · 화각 104°". hello에 선택 필드 `lens {kind, focal_mm, hfov_deg}`(벡터 `hello_with_lens`, `hello_lens`).
- 근거: S21(Android 15)의 기본 카메라 zoomRatioRange는 [1.0, 8.0]이라 `setZoomRatio(0.5)`는 불가능하고, 초광각은 별도 camera id 2(2.2 mm, 가로 104.1°; 기본 5.4 mm, 67.8°)로 노출된다(`dumpsys media.camera`).
- 증거: `gradlew testDebugUnitTest --rerun assembleDebug` BUILD SUCCESSFUL, JVM 시험 146 passed, 0 failed; `lintDebug` 0 errors, 42 warnings(모두 기존 항목) (2026-09-30 Windows, JDK 21).
- gate 변화: 없음. DEVICE PARKED: S21이 다른 세션(rosy-84, 옛 `…ceilingcamera` 앱, `:18448`)에 물려 있어 설치·실기 비교를 미뤘다.
- 교훈: 0.5×는 줌 비율이 아니라 다른 카메라 id일 수 있다. 카메라 id를 고를 때는 `DEFAULT_BACK_CAMERA`가 아니라 특성으로 고른다.

## 2026-09-30 · 877a6fb4 · test(cam): S21 ultra-wide device check
- 변경: 코드 변경 없음. 벤치 Vision(이 브랜치, 8095)에 S21을 `s21`로 페어링하고 같은 자리에서 STANDARD·WIDE를 비교했다.
- 증거: CameraX 후면 카메라는 id 0(5.4 mm, 67.8°)과 id 2(2.2 mm, 104.1°) 둘이고, WIDE는 id 2, STANDARD는 id 0에 1280x720으로 바인딩됐다. 두 경우 모두 3.0 fps, 건너뜀 0. 촬영 중 넓게로 바꾸자 약 30 ms 안에 다시 바인딩됐고, 새 hello로 Vision `X-Source-Lens`가 `kind=wide;focal_mm=2.2;hfov_deg=104.1`로 바뀌었다. WIDE 프레임에는 트랙 전체가 여유 있게 들어오고, STANDARD는 울타리 가장자리가 잘린다. field_detect는 두 프레임 모두 오류 없이 "field runs past the frame"으로 제안하지 않았다. 증거는 `private/validation/2026-09-30-cam-ultrawide/`(git 밖).
- gate 변화: 없음(DEVICE는 벤치 한 대, 한 장면. 현장 FIELD 전).
- 교훈: 초광각은 옆 트랙까지 담아 흰 외곽선 제안이 프레임 끝까지 번질 수 있다. 제안을 받으려면 D-318 모서리 수동 지정이 필요하다.

## 2026-09-30 · a4d9fa7c · feat(cam): STANDARD default, wide on suggestion only
- 변경: 기본 화각은 STANDARD(`LensChoice.DEFAULT`), 저장된 `lens`가 없는 설치(새 설치, 이 설정 이전 설치)도 기본 렌즈. 설정의 넓게는 "넓게 (초광각 0.5×) — 필드가 화면에 다 안 들어올 때"이고, 넓게는 1 m당 화소가 절반쯤이라는 안내를 붙였다. 설치 안내는 수신기가 마커를 보고하는데 모서리가 다 보이지 않고, 지금 렌즈가 기본이며, 더 넓은 카메라가 있을 때만 "연결 설정 › 화각에서 넓게"를 권한다(`LensAdvice`). 렌즈를 저절로 바꾸지는 않는다. 폰은 수신기의 모서리 보고만 받으므로 "필드 잘림"은 모서리 누락으로 본다. Vision/Fleet의 차선 정합 결과는 폰에 오지 않는다.
- 근거: 사용자 결정 2026-09-30. rosy-84가 S21 두 프레임을 차선 정합한 결과, 벤치의 기울어진 설치에서 STANDARD는 점수 0.865, 커버리지 0.992, 약 420 px/m였고 WIDE는 0.896, 1.0, 약 196 px/m였다.
- 증거: `gradlew testDebugUnitTest --rerun assembleDebug lintDebug` BUILD SUCCESSFUL, JVM 시험 151 passed, 0 failed, lint 0 errors·42 warnings(기존); `python -m pytest src/site/vision/test -q` 127 passed (2026-09-30 Windows, JDK 21).
- gate 변화: 없음.
- 결정: 기본 STANDARD, WIDE는 운용자 선택(자동 전환 없음).

## 2026-10-01 · 9c69e38f · fix(cam): review fixes for the ultra-wide lens
- 변경: 촬영 중 렌즈 전환이 실패하면 이전 카메라를 다시 바인딩하고 송출을 이어 간다(`LensSwitch`, 순수·JVM 시험). 화면에 "렌즈를 바꾸지 못해 이전 렌즈로 계속 송출합니다". 상태와 hello의 lens는 전환이 성공한 뒤에만 바뀐다. 초점거리를 여럿 알리는 논리 멀티카메라는 렌즈 정보가 불확실하므로 hello.lens를 보내지 않고 "렌즈 정보 불확실"로 표시한다. 세션 수집기는 하나의 Job 아래에서 돌고 `releaseSession()`이 취소한다. 기기 점검 항목의 커밋 표기를 877a6fb4로 바로잡았다.
- 증거: `gradlew testDebugUnitTest --rerun assembleDebug lintDebug --no-daemon` BUILD SUCCESSFUL, JVM 시험 156 passed, 0 failed, lint 0 errors·42 warnings(기존) (2026-10-01 Windows, JDK 21).
- gate 변화: 없음.

## 2026-10-01 · 35140f13 · fix(cam): 보안 리뷰 반영(인증서 고정) + 바쁜 수신기에서 멈추지 않음

- 변경: 핀 불일치 표식은 `PinMismatchException`이나 SSL/인증서 예외에 있을 때만 믿고, HTTP 응답이 온 실패는 핀 정지로 보지 않는다(평문 ws 503 reason으로 영구 정지를 강제할 수 없다). 고정 인증서의 유효 기간을 직접 검사하고(PKIX는 앵커 날짜를 보지 않는다), leaf보다 위의 고정 인증서는 CA여야 한다. 설정 화면은 TLS를 꺼서 pin이 지워졌음을 알리고, 딥링크 확인 창은 새 링크가 TLS나 pin을 잃으면 경고한다. 닫힘 4400은 비호환 사유일 때만 영구 정지하고, 빈 사유·"no hello"·시간 초과·1013은 `LinkError.Busy`로 백오프 재접속하며 "수신기가 바빠서…"를 띄운다(2026-10-01 실기에서 Vision 루프가 막혀 4400 "no hello"로 카메라가 멈춘 문제). 앱은 예전 링크의 leaf pin을 호환용으로만 계속 받는다.
- 증거: `gradlew testDebugUnitTest assembleDebug` BUILD SUCCESSFUL, JVM 시험 177 passed, 0 failed(`PinnedTrustTest` 13: 호스트명 불일치 CA·leaf pin 모두 `SSLPeerUnverifiedException`/TLS, 같은 CA의 다른 leaf → TLS_PIN, 공격자 leaf 뒤의 고정 leaf 거절, 만료 leaf·만료 CA 거절, 평문 ws 503 표식은 정지 아님). 공유 벡터 `close_codes.try_again_later`·`close_4400_reasons`, `%0A` 거절 벡터.
- gate 변화: 없음. DEVICE 점검 항목은 progress 3항.
- 결정: 4400 사유 분류는 "일시적 사유 목록이 아니면 비호환"이다. 수신기의 4400 사유를 바꾸면 벡터 목록도 같이 고친다.
- 교훈: PowerShell 5.1은 네이티브 인자로 넘긴 here-string 안의 큰따옴표를 깨뜨린다. 커밋 메시지는 `git commit -F <파일>`로 넘긴다.
- 열린 후속: NSC에 user 인증서가 없어 D-341 16항 되돌림 경로가 이 앱에서 동작하지 않는다(progress 4항).

## 2026-10-01 · uncommitted · fix(cam): 4400 재시도 범위를 합의한 전환 예외로 좁힘
- 변경: 4400은 사유가 정확히 빈 문자열이거나 "no hello"(공백 제거, 대소문자 무시, 1013 이전 수신기)일 때만 재접속한다. 그 밖의 사유는 "busy"나 "timeout"이 들어 있어도 비호환으로 보고 멈춘다(`ingest.py`의 `str(exc)` 검증 메시지가 재시도 대상이 되면 안 된다). 공유 벡터 `close_4400_reasons.retry`는 `["", "no hello"]`. `OverheadLink`의 KDoc은 4400이 비호환일 때만, 4401·4409는 멈춘다고 바로잡았다. 예외 자리에 제거 시점 표식(1013 수신기 전환 후 한 릴리스, D-341 11항).
- 증거: `gradlew testDebugUnitTest --rerun-tasks` BUILD SUCCESSFUL (2026-10-01 Windows, JDK 21). `ProtocolTest`는 공유 벡터의 retry·fatal 목록과 "receiver busy"·"timeout" 같은 fatal 사유를 함께 확인한다.
- gate 변화: 없음.

## 2026-10-01 · f908c2d5 · feat(cam): D-391 사이트 연결 기록 + 접속마다 mDNS로 tls_host 찾기

- 변경: (기록은 2aa00ca3, 재발견·진단은 f908c2d5) 저장 모양을 D-391 1항 사이트 연결 기록(`SiteLink`: `site_name`·`tls_host`·`port`·`ca_pin`·`role`·토큰·`source`·`secure`·`expires_at`, 되돌림 `manual_host`, 진단용 `pairing_subnet`)으로 바꿨다. 옛 저장값(`host`/`pin`)은 읽을 때 옮긴다: IP면 `manual_host`, 이름이면 `tls_host`. 해석된 IP는 저장하지 않는다. 링크 URL은 `tls_host`를 유지하고 OkHttp `Dns`(`SiteDns`)가 접속마다 `SiteResolver`로 주소를 찾는다: `_rosy-overhead._tcp` 탐색(`NsdSiteBrowser`, D-370 TXT 규칙으로 `tls_host` 일치) → 없으면 `manual_host`("수동 주소") → 없으면 `not_discovered`. 찾은 주소는 30 s 캐시하고 접속 실패 때 버린다. 같은 `tls_host`가 두 주소에서 보이면 `conflict`로 자동 선택하지 않는다(D-370 5.3). pin이 있는 IP 전용 기록은 그 IP의 광고에서 `tls_host`를 배워 다음 세션부터 이름으로 붙는다. NSD 제약: API 34 미만은 resolve를 하나씩, 34 이상은 `registerServiceInfoCallback`. 진단: 5 s 안에 못 찾으면 "사이트가 이 Wi-Fi에서 보이지 않습니다 — 같은 이름의 다른 Wi-Fi일 수 있습니다"와 지금 Wi-Fi 서브넷·게이트웨이, 페어링 때 서브넷을 보여 준다. "Wi-Fi 연결 안 됨"은 주소를 가진 LAN 네트워크(LinkProperties) 기준이다(설정 화면 검색도 `activeNetwork` 대신 같은 기준). 실패 분류 이름은 `link/FailureClass.kt` 한 곳에 두었다.
- 증거: `gradlew testDebugUnitTest assembleDebug` BUILD SUCCESSFUL, JVM 시험 212 passed, 0 failed(새 시험: `SiteLinkTest` 9 기록·이관, `SiteResolverTest` 14 가짜 NSD·순서·캐시·충돌·학습, `SiteDnsTlsTest` 4 MockWebServer 127.0.0.1 + `tls_host` 인증서: SNI=`tls_host`, 다른 이름 인증서 거절, 수동 주소도 `tls_host` 검사, 못 찾으면 소켓 전 `not_discovered`, `FailureClassTest` 3, `ProblemGuideTest` 진단 문구 선택·실제 연결 기준) (2026-10-01 Windows, JDK 21).
- gate 변화: 없음. DEVICE 점검은 progress 5항.
- 결정: `manual_host`로 붙어도 URL은 `tls_host`라서, 이름을 아는 기록은 IP SAN 없이도 수동 주소로 붙는다. IP SAN이 필요한 것은 `tls_host`를 모르는 IP 전용 기록뿐이다.
- 열린 후속: 공유 벡터 `test/fixtures/protocol/failure-classes.v1.json`·`site-link.v1.json`이 main에 아직 없다(rosy-00). 들어오면 `FailureClassTest`·`SiteLinkTest`가 그 벡터를 읽게 바꾼다. 4400/4403/429/503 행은 앱의 해석이다. leaf 단독 pin 금지는 저장 때 판정할 수 없어 `PinnedTrustManager`가 옛 leaf pin을 계속 받는다.

## 2026-10-01 · 6588c4a8 · fix(cam): D-391 태블릿 실기·독립 리뷰 반영

- 변경: (3c089998) 이름 링크로 다시 페어링하면 `manual_host`를 지운다. `manual_host`는 저장하는 링크 자체의 IP에서만 온다. mDNS가 못 찾고 수동 주소도 실패하면 `not_discovered`(서브넷 포함)를 먼저 보이고 수동 주소 실패를 둘째 줄에 붙인다. (a45a47cb) 서브넷이 페어링 때와 같으면 첫 줄을 "사이트가 자동 찾기(mDNS)에 보이지 않습니다"로 바꾼다. 리뷰 반영: M1(15f69abb) IP 리터럴을 엄격히 파싱하고 포트가 붙은 호스트를 거절한다. 잘못된 수동 주소는 없는 것으로 보고, 조회 오류는 크래시가 아니라 `UnknownHostException`이 된다. M2(cef23c0d) IP 전용 기록은 광고가 정확히 하나이고, `manual_host`로의 고정 핸드셰이크에서 받은 leaf가 그 이름을 담을 때만 `tls_host`를 배운다. OkHttp의 `Handshake.peerCertificates`는 `PinnedTrustManager`와 함께면 비어 있으므로, 신뢰 관리자가 검증한 leaf를 기록한다. M3(2bafd282) 발견한 주소에서 난 첫 TLS_PIN은 치명적이지 않다: 다시 탐색하고, 되풀이되면 멈춘다. m2–m5(064cc3b9): 잠금 없는 캐시 무효화, pin이 있는 기록만 mDNS를 쓴다, `.local`이 아닌 이름은 DNS 실패 때 수동 주소로 간다, 충돌은 주소 집합이 서로소일 때만. m6(031a4742) 문구 "주소 범위가 페어링 때와 같습니다", `pairing_subnet`은 새 페어링 때만 기록한다. m7(71fdf5e7) 새 LAN 네트워크를 LinkProperties로 채운다. m8(94bc848a) FAILURE_ALREADY_ACTIVE resolve를 200 ms 뒤 한 번 재시도하고, 송출 중에는 설정 화면이 검색하지 않는다. m9(7161c152) Preferences↔SiteLink 매핑을 순수 코드 `SiteLinkPrefs`로 뺐다. 잔손질(6588c4a8): 탐색하지 않은 수동 경로는 "자동 찾기 쓰지 않음"으로 표시한다.
- 증거: `gradlew testDebugUnitTest assembleDebug --rerun-tasks` BUILD SUCCESSFUL, JVM 시험 235 passed, 0 failed(`SiteLinkPrefsTest` 6, 새 `OverheadLinkTest.connectFailureForcesAFreshBrowse`, `SiteDnsTlsTest`의 M2 leaf·M3 pin 재탐색, `SiteResolverTest`의 m2 잠금·m3·m4·m5). `python -m pytest test/architecture/test_app_identity.py test/test_harness_contracts.py -q` 녹색. 태블릿(Android 11) 실기, 코디네이터 수행: 3c089998에서 이름 링크 재페어링이 옛 IP를 지우고 mDNS로 10.16.36.17에 붙어 송출했다. 광고되지 않는 이름은 서브넷과 함께 `not_discovered`를 보였다 (2026-10-01).
- gate 변화: 없음. DEVICE는 태블릿 부분 확인만 했고 progress 5항이 남았다.
- 교훈: `PinnedTrustManager.getAcceptedIssuers()`가 비어 있으면 OkHttp 체인 정리기가 실패해 `Handshake.peerCertificates`가 조용히 빈 목록이 된다. 검증된 leaf가 필요하면 신뢰 관리자에서 받는다. Android NSD 캐시는 goodbye 없이 꺼진 광고도 몇 분 동안 계속 풀어 준다. 앱 캐시 무효화는 새 탐색을 강제하지만, NSD가 같은 옛 주소를 돌려줄 수 있다.
- 열린 후속: 공유 벡터 `failure-classes.v1.json`·`site-link.v1.json`(rosy-00, `feat/d391-shared-link-vectors`)이 main에 오면 `FailureClassTest`·`SiteLinkTest`·`SiteLinkPrefsTest`가 그 벡터를 읽게 바꾼다.

## 2026-10-01 · 137564eb · test(cam): D-391 공유 벡터(failure-classes·site-link)를 Kotlin 시험이 읽는다

- 변경: (58924f5a) Gradle 속성 `rosy.failure.vectors`·`rosy.sitelink.vectors`를 추가했다. `FailureClassTest`는 `failure-classes.v1.json` 26개 사례를 모두 돌린다: WS 닫힘·HTTP는 `FailureClass`로, transport는 실제 예외를 `NetworkFailure.classify`로, discovery는 `SiteNotDiscoveredException`으로 확인한다. 분류 목록, fallback, 그리고 `Protocol.TRANSIENT_4400` = `close_4400_retry_reasons`도 검사한다. 벡터에 맞춘 분류 차이는 셋이다. 모르는 WS 코드는 null에서 `unreachable`, 사유 없는 4400은 `protocol_mismatch`에서 `busy`, 목록 밖 4xx/5xx는 null에서 `protocol_mismatch`/`busy`가 됐다. 동작은 바꾸지 않았다. 수동 경로의 pin 불일치는 여전히 정지하고, 발견 경로의 첫 불일치는 다시 탐색한다. (137564eb) `SiteLinkRecord`는 공유 기록 모양을 `site_link.py`와 같은 규칙·순서로 검사하고(`ca_pem` CA 판정은 `getBasicConstraints() >= 0`), `SiteLinkTest`가 `site-link.v1.json` 33개 사례를 모두 돌린다. `toSiteLink`는 유효한 카메라 기록을 저장 모양 `SiteLink`로 옮긴다. `ca_pem` 첫 CA의 pin, 주어진 토큰·source, 소문자 `tls_host`. IP `manual_host`는 유지하고, 이름 `manual_host`는 버린다(DNS 없이 다이얼한다). robot 기록은 옮기지 않는다. 저장 형식은 바꾸지 않았다.
- 증거: `gradlew testDebugUnitTest --rerun-tasks` BUILD SUCCESSFUL, JVM 시험 241 passed, 0 failed(`FailureClassTest` 4: 26 사례·목록·4400·fallback, `SiteLinkTest` +5: 33 사례·사유/역할·카메라 기록 7건 변환·이름 수동 주소·무효 기록). host pytest와 harness lint는 progress 참조 (2026-10-01 Windows, JDK 21).
- gate 변화: 없음.
- 결정: 분류와 동작은 따로 둔다. `NetworkFailure.TLS_PIN`은 앱 내부 종류로 남지만 분류는 `tls_untrusted`다.
- 열린 후속: (1) 앱은 4400 사유를 trim·소문자로 비교한다(Python은 정확 일치). 벡터에 해당 사례는 없다. (2) 앱 `SiteLink.validate`는 `.local`이 아닌 `tls_host`도 받는다(설정 화면에서 입력한 DNS 이름, review m4의 시스템 DNS 경로). 공유 규칙은 `bad_tls_host`다. (3) 공유 기록의 `manual_host`는 이름도 되지만, 앱 저장 모양은 IP만 받는다.

## 2026-10-01 · be9ac996 · fix(cam): D-391 tls_host는 .local 이름만, 공유 벡터 갱신(464b0c88) 반영

- 변경: (be9ac996) 코디네이터 결정에 따라 `SiteLink.validate`는 한 레이블 + `.local`이 아닌 `tls_host`를 거절한다(공유 벡터와 같은 규칙). 설정 화면 저장과 `rosyov://` 딥링크도 `SiteLink.entryReason`으로 같은 검사를 하고, "사이트 이름은 .local 이어야 합니다"를 보인다. IP는 여전히 수동 주소로 받는다. review m4의 시스템 DNS 경로를 없앴다. `.local`이 아닌 이름은 수동 주소나 `not_discovered`로 간다. 저장값은 옛 IP면 그대로 `manual_host`로 옮기고, 옛 기록이든 새 형식이든 `.local`이 아닌 이름이면 읽지 않는다. `SiteLinkPrefs.rejectedHost`가 그 이름을 알려 주고, 송출 화면은 "다시 페어링하세요"를 띄운다. 저장 형식은 그대로다. (54881d1f) main 464b0c88을 병합했다. rosy-00이 4400 사유를 trim·casefold하고, `manual_host`를 IP 리터럴로 좁혔다. `SiteLinkRecord`는 이름·`ip:port` `manual_host`를 `bad_manual_host`로 거절한다.
- 증거: `gradlew testDebugUnitTest --rerun-tasks` BUILD SUCCESSFUL, JVM 시험 244 passed, 0 failed(`failure-classes.v1.json` 28 사례, `site-link.v1.json` 35 사례, `.local` 규칙·딥링크·옛 기록 거절 시험) (2026-10-01 Windows, JDK 21).
- gate 변화: 없음.
- 결정: 앞 항목의 열린 후속 셋은 닫혔다. (1)·(3)은 벡터를 바꿔 앱에 맞췄고, (2)는 앱을 벡터에 맞췄다.
