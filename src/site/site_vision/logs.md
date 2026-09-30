# overhead logs

추가만 한다. 형식: [module harness 설계](../../docs/plans/2026-09-15-module-harness-design.md) §4.2.

## 2026-09-26 · uncommitted · feat(overhead): rosy-overhead/1 protocol module (D-261 A1)

- 변경: `overhead/protocol.py` — 20바이트 헤더 pack/parse(`magic`/`short`/`reserved`/`rotation`/`size` 사유), `validate_hello`, `make_config`, `rosyov://` pairing URI 생성·파싱. `protocol/vectors.json`의 모든 벡터를 시험이 돈다.
- 증거: `python -m pytest src/site/overhead/test/test_protocol.py -q` 27 passed
- gate 변화: SOURCE/LOCAL GO 시작. DEVICE/FIELD PARKED.

## 2026-09-26 · uncommitted · feat(overhead): receive-only WebSocket ingest server (D-261 A2)

- 변경: `overhead/ingest.py` — 토큰 없으면 401, 경로 틀리면 404, `hello` 불량이면 4400, 같은 source 재접속이면 옛 연결 4409, 최신 1장만 보관(큐 없음), `max_bytes` 초과·헤더 불량은 연결 유지한 채 드롭 카운트, `captured_at`은 이 프로세스 자체 벽시계 − `age_ms`.
- 증거: `python -m pytest src/site/overhead/test -q` 36 passed (실 localhost 서버, websockets 클라이언트)
- gate 변화: 없음. LOCAL GO 유지.

## 2026-09-26 · uncommitted · feat(overhead): rosy_overhead receive CLI + ament_python package (D-261 A2)

- 변경: `overhead/cli.py` — `rosy_overhead receive`가 pairing URI(+선택 ASCII QR)를 찍고, 토큰 미설정이면 생성하고, 초당 소스별 통계를 찍는다. `--stats-jsonl`/`--save-latest` 지원. `package.xml`/`setup.py`/`setup.cfg`/`resource/overhead`는 games와 같은 레이아웃.
- 증거: `python -m pytest src/site/overhead/test -q` 41 passed
- gate 변화: 없음. LOCAL GO 유지. DEVICE/FIELD PARKED.

## 2026-09-26 · 27b8f34e · fix(overhead): never stall a reconnecting phone behind a half-open old socket

- 변경: 독립 리뷰(REQUEST CHANGES)가 재현한 결함 — 같은 source 교체 때 옛 연결 close를 기다리면, 옛 폰이 Wi-Fi를 잃은 반열림 상태일 때 새 연결이 10 s 멈추고 그동안 프레임이 websockets 안에 쌓였다. 옛 close는 백그라운드(2 s 뒤 transport abort), 수신 큐 1장, `max_size`는 `max_bytes`를 따른다, hello 5 s 무응답은 4400, 토큰 비교 상수 시간, `websockets>=14` 선언(Ubuntu 24.04 apt 10.x는 import에서 명확히 실패).
- 증거: 반열림 시험이 옛 코드에서 10.2 s로 빨강, 수정 후 초록. `python -m pytest src/site/overhead/test -q` 45 passed ×4
- gate 변화: 없음. LOCAL GO 유지.

## 2026-09-26 · c6647a1e · 에뮬레이터 종단 확인 (안드로이드 앱 → 이 어댑터)

- 변경: 코드 없음. 안드로이드 리뷰 수정(타임스탬프 기준 판정, 토큰 로그 가림, 회전 시 페어링 대화상자 유지) 뒤 재확인.
- 증거: API 35 에뮬레이터(가상 장면 카메라) → `rosy_overhead receive` 127.0.0.1:8095. 3 fps, `seq_gaps` 0, 헤더 불량 0, `age_ms` p50 11–177 ms, 약 0.4–0.6 Mbps. 수신기 종료 → 앱 "다시 연결 중" → 수신기 재기동 → 앱이 스스로 재접속해 32프레임. 딥링크 확인 대화상자가 가로/세로 회전 뒤에도 남고 취소하면 기존 페어링 유지. 정지 시 카메라 DISCONNECT 확인.
- gate 변화: 없음. 에뮬레이터는 LOCAL이다(D-261 8항). DEVICE PARKED.

## 2026-09-26 · uncommitted · feat(overhead): CPU vision worker to Fleet sighting contract (D-257/D-269)

- 변경: `detect.py`가 JPEG에서 ArUco를 검출하고, `project.py`가 4개 map marker로 homography를 맞춰 지정 robot marker pose를 계산한다. `worker.py`는 configured source의 fresh latest frame만 처리하고 `publish.py`는 별도 source Bearer token으로 JPEG 없는 `SiteSightingPayload`를 Fleet에 보낸다. 측정식이 승인되지 않은 quality는 null이다.
- 증거: `python -X utf8 -m pytest src/site/overhead/test -q -p no:cacheprovider` 60 passed. 포함된 실제 localhost 시험에서 합성 phone WebSocket frame → source/seq/map/calibration lineage → Uvicorn Fleet operator readback을 확인했다. corner 누락·stale frame은 sighting을 만들지 않았다. `src/site/fleet/test/test_sightings_api.py` 7 passed, `src/runtime/gateway/test/test_site_sightings.py` 15 passed.
- gate 변화: SOURCE/LOCAL 코드·합성 localhost만 확인. config/CLI wiring, 지속 저장·재시작, Ubuntu/TLS/LAN, 실제 폰·로봇은 미수용이며 DEVICE/FIELD PARKED, D-268 자동 실행 HOLD.

## 2026-09-26 · uncommitted · feat(site): TLS Docker path and durable sighting readback

- 변경: Fleet console CLI now loads source permissions and SQLite-backed latest/history storage; overhead `vision` runs the receive→detect→project→publish worker. Android pairing supports explicit `tls=1` and `wss://`. Site Compose builds Ubuntu 24.04 Fleet and vision images plus a hardened Caddy TLS proxy; backend TLS and CA verification are enabled inside the stack.
- 증거: overhead 70 passed, Fleet sighting/config/store/CLI/API 40 passed, gateway sighting 15 passed, Android `testDebugUnitTest` successful. Three local images built; Compose services healthy. With a synthetic ArUco JPEG sent over trusted WSS, Fleet API readback returned source `ceiling_north`, seq 77, pose `(2.0, 1.0)`, quality `null`; Fleet restart preserved the SQLite readback.
- 조사/수정: upstream Caddy binary carries `cap_net_bind_service=ep`, which prevented exec under `cap_drop: ALL`; the site proxy image removes that unused file capability because it binds only 8443. Caddy config/data tmpfs are owned by uid/gid 10001.
- gate 변화: LOCAL Docker integration GO. Real host install, site certificate/CA provisioning, real ceiling camera calibration, CORE/Pinky/arm hardware and field acceptance remain open. Sightings remain display-only; D-268 motion/pick HOLD.

## 2026-09-27 · 778bbd31 · verify packaged camera-to-Fleet sighting path (LOCAL)

- 변경: Android 소스 변경 없이 immutable Site candidate를 재빌드하고 synthetic ceiling-phone JPEG를 packaged WSS → Vision CPU ArUco → Fleet HTTPS/SQLite로 전송했다.
- 근거: overhead `70 passed`; source `ceiling_north`, sequence 78, pose `[2.0, 1.0]`; Fleet 재시작 후 sighting readback 통과. `quality: null`이며 physical phone/freshness/calibration 수용은 아니다.
- gate 변화: SOURCE/LOCAL 유지. Android phone, Ubuntu/RTX GPU, DEVICE/FIELD는 PARKED; D-268 automatic movement/picking은 HOLD.
## 2026-09-28 · uncommitted · serve authorized latest-frame preview

- Change: Vision validates Fleet HMAC leases, serves only the latest fresh JPEG directly to the browser, caps each principal/source at 5 requests/second, and returns explicit missing/stale/rate-limit responses. Compose mounts a dedicated read-only secret and Caddy routes preview traffic directly to Vision.
- Evidence: overhead suite 76 passed with the HTTP preview route and rate cap. Compose config parses and Caddy adapts with the Vision preview route. Packaged stack/TLS/browser smoke was not run.
- Gate: local tests/config only; device, calibrated view, site host, and field gates remain parked.

## 2026-09-28 · uncommitted · apply measured rectification to Fleet preview only

- Change: added bounded normalized lens intrinsics/distortion and clockwise quadrilateral settings to the short-lived HMAC preview lease. Vision applies OpenCV undistortion and perspective warp only to the response copy; raw latest JPEG and ArUco/sighting input are untouched. Identity settings return the original JPEG.
- Evidence: overhead suite 86 passed, including synthetic square warp, invalid/crossed setting rejection, signed lease validation, direct HTTP preview, and raw frame immutability. Fleet lease route tests also pass. Local Docker Compose WSS synthetic-frame preview returned HTTP 200 with `X-Frame-Rectified=true`; 1920/390/320px captures show the rectified checkerboard with zero page errors or horizontal overflow. Captures are under `X:\\DevTemp\\rosy-uiux-local-site\\camera-rectification-docker`.
- Gate: SOURCE/LOCAL only; real measured lens/floor calibration, physical camera/phone, Ubuntu/site, DEVICE and FIELD acceptance remain PARKED.

## 2026-09-28 · uncommitted · validation(overhead): recheck physical camera availability

- Change: ran read-only availability checks for the previously supplied robot address and connected Android devices; no robot commands were sent.
- Evidence: ping to `192.168.1.202` timed out and `adb devices -l` returned an empty device list. The local Docker Fleet/Vision/proxy stack remains healthy, but the synthetic WebSocket sender has stopped and no live camera frame is available.
- Gate: synthetic SOURCE/LOCAL evidence remains valid. Measured camera calibration, phone streaming, Ubuntu/site TLS, DEVICE and FIELD remain PARKED.

## 2026-09-29 · uncommitted · web-surface-hardening: CI에 overhead 호스트 시험과 android 단위 시험

- 변경: `ci.yml`이 `src/site/overhead/test`를 따로 돌린다(games와 `test_preview.py` 이름이 겹친다). 새 `.github/workflows/android.yml`이 `src/site/overhead/**` 변경 때만 Temurin 17로 `testDebugUnitTest`를 돈다.
- 증거: `python -m pytest src/site/overhead/test -q` 86 passed. 로컬 `gradlew testDebugUnitTest --no-daemon`(JDK 21) BUILD SUCCESSFUL. CI 실행 증거는 아직 없다(푸시 안 함).
- gate 변화: 없음.

## 2026-09-29 · uncommitted · fix(overhead): pick the ArUco detector API by hasattr

- Change: detect.py built cv2.aruco.ArucoDetector at import time, which exists only on OpenCV 4.7+ — the CI image (and the device precedent) ship 4.6, so every overhead test failed at collection with AttributeError. The module now picks the 4.7+ detector when present and falls back to the 4.6-era cv2.aruco.detectMarkers module function, the same pattern dock_tag.py already ships for the same reason.
- Evidence: python -m pytest src/site/overhead/test -q 86 passed on a host OpenCV that has ArucoDetector (new branch exercised); the fallback mirrors the proven dock_tag shape. CI run 36572518093 shows the failure this removes.
- Gate: SOURCE/LOCAL only; no device or FIELD claim.- 추가(같은 회차): 시험 픽스처의 마커 합성도 같은 갭이었다(4.7+ generateImageMarker vs 4.6 drawMarker). detect.py에 generate_marker_image() 헬퍼를 두고 두 시험이 그걸 쓴다 — OpenCV 버전 선택은 이 모듈에만 격리된다는 원칙 유지. 86 passed, flake8 clean.
- 추가(같은 회차): CI 세그폴트는 4.6 바인딩에서 직접 생성한 DetectorParameters 객체가 module detectMarkers와 어긋난 것이다. dock_tag과 같이 DetectorParameters_create를 우선하고 레거시 경로는 흑백 프레임을 먹인다(16e884a9 회차의 CI 36574967367 근거).

## 2026-09-30 · uncommitted · fix(overhead-app): 적응형 JPEG 화질과 정지 중 대상 표시

- 변경: 1280 px·품질 70 JPEG가 `max_bytes`(200 KB)를 조금 넘는 장면에서 모든 프레임이 버려져 0 fps가 되던 문제를 고쳤다. 초과 프레임은 최대 두 번 10씩 낮춰 다시 인코딩하고(하한 30), 다음 프레임은 지금까지 시도한 가장 낮은 화질에서 시작하며, 30회 연속으로 맞으면 5 올려 본다. 올려 본 화질이 넘치면 마지막으로 맞았던 화질로 곧장 돌아간다. 카메라 재바인딩·화질·폭 변경 때 적응 상태를 초기화한다. 설정 `jpeg_quality`는 상한이고 초과 프레임은 여전히 보내지 않는다. 정지 중 스트림 화면은 지난 실행 대상 대신 저장된 대상을 보인다.
- 증거: Galaxy S21(Android 15) 실기기에서 수정 전 0 fps·버림 누적, 수정 후 3.0 fps·버림 0, 콘솔 미리보기 경로 HTTP 200. 저장 대상을 바꾸면 재시작 없이 표시가 바뀐다. JVM 단위 시험 통과(아래 커밋 참조). 독립 리뷰(2026-09-30) 지적 1·2·4·5 반영.
- gate 변화: DEVICE(휴대폰 송출 단독) 증거 추가. 현장 보정·Ubuntu/TLS·FIELD는 PARKED 그대로.

## 2026-09-30 · uncommitted · 천장 설치용 앱: 다음 행동을 말하는 상태, 화면 꺼짐 송출, 기기 상태

- 변경: 연결 실패를 원인(닿지 않음·거부·이름 못 찾음·TLS·토큰·같은 이름 중복·Wi-Fi 없음)으로 나눠 다음 행동을 한 문장으로 보여 주고, 원문은 `자세히` 뒤에 둔다(`NetworkFailure`, `ProblemGuide`). 배터리·충전·온도를 화면과 상시 알림에 보이고 열 상태 MODERATE 이상이나 충전 없이 20% 미만이면 경고한다(`DeviceHealth`, 휴대폰 안에서만; 선로 변경 없음). 수신기 `status`로 코너 마커 점 4개와 보이는 로봇을 보인다(`CornerGuide`). `버림`을 `건너뜀`으로 바꾸고 뜻을 한 줄로 적었으며, 자동 조정으로 낮아진 JPEG 품질을 보인다. 송출 중에도 연결 설정을 읽기 전용으로 연다. 화면 글자가 검정으로 떨어지던 테마 결함(Column에 Surface가 없음)을 고쳤다.
- 증거: Android `testDebugUnitTest` 117 passed, `assembleDebug` 성공(JDK 21, Windows). Galaxy S21(Android 15) 실기에서 임시 수신기(`receive --port 8096`)로 확인: 화면 잠금 65초 동안 수신 70표본 최소 2 fps, `age_ms` 최대 178 ms, seq gap 0. 잠금 화면 깨우기·강제 deep idle에서도 3 fps 유지. 카메라는 이미 서비스 수명에 묶여 있어 (b) 현상은 이 빌드에서 재현되지 않았다. 닿지 않음·401·자세히·기기 경고(배터리/열 상태는 `dumpsys battery`·`cmd thermalservice`로 모의)·읽기 전용 설정 화면을 캡처했다(`private/validation/2026-09-30-overhead-app-ceiling-ux/`).
- 남은 일: 어댑터 `status`의 `corners_seen`·`robots_seen`이 항상 빈 목록(`ingest.py` 자리값)이라 설치 안내가 늘 0/4를 보인다. Vision이 실제 값을 채워야 한다. 프로토콜에 휴대폰→수신기 상태 메시지가 없어 기기 상태는 현장 PC에 가지 않는다. Windows 방화벽이 닫힌 포트의 SYN을 버려 수신기가 꺼진 경우도 `닿지 않음`으로 보인다.
- gate 변화: 없음. 실기 앱 확인은 임시 수신기 기준이며 Vision/Fleet 종단과 현장 수용은 아니다.

## 2026-09-30 · uncommitted · 리뷰 반영: 실제 마커 보고, 무인터넷 Wi-Fi, 카메라 끄고 설정 열기

- 변경: Vision 워커가 최신 프레임에서 검출한 id 가운데 설정된 `corner_marker_ids`·`robot_markers`만 골라 `IngestServer.report_markers`로 넘기고, 휴대폰 `status`는 3초 안의 보고를 `corners_seen`·`robots_seen`으로 싣는다(그 뒤에는 빈 목록). 검출은 이미 도는 워커 결과를 재사용해 추가 CPU가 없고, id만 휴대폰에 가며 영상·좌표는 Fleet에 가지 않는다(D-257). 앱은 이 세션에서 마커 보고를 한 번이라도 받기 전에는 설치 안내 대신 "수신기가 마커 인식을 아직 보고하지 않습니다"를 보인다(`overhead receive`는 여전히 빈 목록). Wi-Fi 판정은 기본 네트워크 대신 인터넷 능력을 뺀 Wi-Fi/Ethernet 요청 콜백을 써서 인터넷 없는 현장 Wi-Fi도 연결로 본다. 송출 중 토큰·이름 문제의 버튼은 "카메라를 끄고 연결 설정 열기"로 카메라를 끈 뒤 설정을 연다. 알림은 온도 정수·배터리·충전·경고가 바뀔 때만 갱신한다. `problem_*` 문장 끝 마침표와 QR 표현("현장 PC의 페어링 QR")을 맞췄다.
- 증거: `python -m pytest src/site/overhead/test -q` 88 passed(합성 ArUco 영상으로 실제 WebSocket `status`에 `[30, 31, 33]`·`["rosy_01"]` 확인 포함). Android `testDebugUnitTest` 125 passed, `assembleDebug` 성공(JDK 21, Windows). 실기 재확인은 하지 않았다.
- gate 변화: 없음. 실기·현장 수용은 그대로 열려 있다.

## 2026-09-30 · uncommitted · feat(overhead): D-354 경기장 모서리 제안과 field-proposal 경로

- 변경: `overhead/field_detect.py` 추가 — 흰 영역 마스크 → 가장 큰 볼록 윤곽 → `approxPolyDP` 네 점 → 볼록성·면적·모서리 각·가로세로 비 검사 → 외곽선 직선 맞춤으로 서브픽셀 정밀화. 경기장이 없거나 프레임 밖으로 나가면 제안하지 않는다. `ingest.py`에 `GET /api/vision/sources/{id}/field-proposal`(frame과 같은 lease·`no-store`·`nosniff`·freshness, 제안 전용 초당 1회 칸, seq별 캐시). `_http_response`에 없던 422 사유 문구를 넣었다(기존 보정 실패 경로도 KeyError로 죽을 수 있었다).
- 증거: `python -m pytest src/site/overhead/test -q` 107 passed(합성 이미지만). 저장된 실제 프레임 6장(1280×720, `private/`)은 모두 "field runs past the frame"로 제안 없음 — 경기장 오른쪽이 프레임 밖이다. 프레임당 검출 중앙값 24–27 ms, 디코드 포함 28–38 ms(Windows, 이 PC).
- gate 변화: 없음. SOURCE/LOCAL만. DEVICE(설치 폰 실시간)·FIELD(실측 치수 대조) 미실행.

## 2026-09-30 · uncommitted · fix(overhead): D-354 제안 검출을 이벤트 루프 밖에서, 소스당 초당 1회

- 변경: `process_request`를 코루틴으로 바꿔(websockets 17.0.1) 경기장 검출을 `asyncio.to_thread`에서 돌린다. 검출은 lease 주체와 상관없이 소스당 1초에 한 번만 돌고, 그 사이 요청은 직전 결과(그 프레임의 seq·age)를 받으며 첫 검출이 도는 중이면 429다. 캐시는 seq 대신 프레임 객체로 가리고(재접속하면 seq가 다시 시작한다) 소스가 빠지거나 교체되면 지운다.
- 증거: `python -m pytest src/site/overhead/test -q` 111 passed(검출 스레드·소스 공유 예산·프레임 동일성·소스 제거 시험 추가).
- gate 변화: 없음. SOURCE/LOCAL만.

## 2026-09-30 · uncommitted · docs: 경기장 자동 검출 ADR 번호 D-354 → D-360

- 변경: main에 다른 D-354(mDNS 서비스 발견)가 먼저 착지해, main 병합 때 경기장 자동 검출 제안 ADR을 D-360으로 옮겼다. 코드 주석·시험·API Ref의 D-354 표기를 D-360으로 바꿨고 ADR 본문에 까닭을 적었다. 이 항목보다 앞선 로그의 "D-354"(경기장 제안)는 D-360을 가리킨다(로그는 고치지 않는다).
- 증거: 병합 커밋의 overhead·Fleet·node 실행.
- gate 변화: 없음.

## 2026-09-30 · uncommitted · test(overhead-app): D-358 S1 DiscoveryVectorsTest

- 변경: Gradle 단위 시험에 시스템 속성 `rosy.discovery.vectors`(`test/fixtures/protocol/discovery-txt.v1.json`)를 더했다. `OverheadServiceRecord`/`RobotCoreServiceRecord`에 벡터 어휘로 사유를 내는 `rejection()`을 두고 `parse()`가 그것을 쓴다. 받는 집합은 바뀌지 않았다.
- 증거: `gradlew testDebugUnitTest` 95 tests, 0 failures. 변이 증명: 벡터 기대 사유 하나를 바꾸면 Kotlin도 적신.
- gate 변화: 없음.
- 결정: D-358 5.1. 로봇 레코드는 주소·호스트·AP·legacy를 아직 보지 않는다. 앱 동작 변경이라 이번 범위 밖이고, 시험에 `knownRobotDivergence` 8건으로 못 박았다(고치면 시험이 목록 삭제를 요구한다).
- 교훈: 없음.

## 2026-09-30 · uncommitted · feat(overhead-app): D-358 S3 적응형 런처 아이콘

- 변경: `mipmap-anydpi-v26/ic_launcher(_round).xml`(배경·전경·흑백 세 층), `drawable/ic_launcher_foreground.xml`·`ic_launcher_monochrome.xml`(`web_common/icons/overhead-camera-app.svg`에서 생성), `values/ic_launcher_background.xml`(ground #101214), 매니페스트 `android:icon`·`roundIcon`. `app_name`은 이미 "Rosy 천장 카메라"라 그대로 두었다. `LauncherIconParityTest`(`rosy.icons.dir`)가 경로·굵기·색을 SVG와 대조한다. 밀도별 PNG는 만들지 않았다(minSdk 26).
- 증거: `gradlew testDebugUnitTest assembleDebug` 녹색(99 tests). 변이 증명: SVG 렌즈 고리 굵기를 바꾸면 패리티 시험 2건 적신. 512 px PNG: `private/validation/2026-09-30-d358-icons/overhead-camera-app-512.png`.
- gate 변화: 없음. 실제 폰 런처 확인은 DEVICE 회차.
- 결정: D-358 3항.
- 교훈: 없음.


## 2026-09-30 · uncommitted · docs(adr): D-358 앱 역할 ADR을 D-370으로 재번호

- 변경: 이 모듈의 D-358 앱 역할·이름·아이콘 주석과 시험 문서 문자열을 D-370으로 바꿨다. 동작 변경 없음.
- 증거: 번호만 바꾼 diff. 시험은 병합 뒤 회차에서 다시 돌린다.
- gate 변화: 없음.
- 결정: 이 항목 앞의 "D-358 S1/S2/S3"·"D-358 N항"은 D-370을 가리킨다(main의 D-358 ER2 피드백 outbox와 다름). 옛 항목은 고치지 않는다.
- 교훈: 없음.

## 2026-09-30 · uncommitted · fix(overhead-app): D-370 리뷰 — Kotlin tls_host 규칙을 Python 분류기와 맞춤

- 변경: `OverheadServiceRecord.rejection`이 한 레이블 `<name>.local`만 받고, 해석된 호스트와 `tls_host`를 소문자·끝 점 제거 뒤 비교한다. 저장하는 `tlsHost`도 같은 정규화. 공유 벡터 `overhead_multilabel_tls_host`(bad_host)·`overhead_tls_host_case`(accepted) 추가. `.github/workflows/android.yml`이 `test/fixtures/protocol/**`·`src/hmi/web_common/icons/**` 변경에도 돈다.
- 증거: `gradlew testDebugUnitTest` 녹색, Python 벡터 소비자 122 passed.
- gate 변화: 없음. 실제 폰 발견은 DEVICE 회차.
- 결정: D-370 5.1.
- 교훈: 없음.

## 2026-09-30 · uncommitted · refactor(site-vision): D-374 stage 1 — overhead becomes site_vision

- 변경: `src/site/overhead` → `src/site/site_vision`(`git mv`), ROS·Python 패키지 `overhead` → `site_vision`, console script `site_vision=site_vision.cli:main`, `argparse` prog `site_vision`, logger `site_vision`, `setup.cfg` `lib/site_vision`. `protocol/vectors.json` → `test/fixtures/protocol/overhead-ingest.v1.json`(Kotlin과 같이 읽는 공유 자리). 폰 앱은 새 모듈 `src/site/ceiling_camera`로 갈라졌다. `Dockerfile.vision`·`.dockerignore`·`compose.yaml` 명령은 `python3 -m site_vision.cli`, mDNS 인스턴스 이름은 `ROSY Site Vision %h`. 하네스 모듈 `overhead` → `site_vision`. 와이어 이름(`rosy-overhead/1`, `/overhead/v1/frames`, `_rosy-overhead._tcp`, TXT, `/api/vision/*`, `rosyov://`, compose 서비스 `vision`, 이미지 `rosy-site-vision`, `ROSY_OVERHEAD_TOKEN`)은 그대로(D-374 3항).
- 증거: `python -m pytest src/site/site_vision/test -q` 111 passed; `src/site/fleet/test` 938 passed, 6 skipped; `src/hmi/web_common/test` + discovery 벡터 144 passed; 루트 architecture·site·discovery 185 passed, 1 skipped (2026-09-30 Windows).
- gate 변화: 없음. SOURCE/LOCAL GO 유지. 사이트 호스트 vision 이미지 재빌드·mDNS 인스턴스 확인은 DEVICE 절차(계획 단계 1).

## 2026-09-30 · uncommitted · feat(site-vision): D-374 overhead console-script alias

- 변경: `setup.py`에 `overhead=site_vision.cli:main`을 함께 둔다. 운용 문서와 손에 익은 `overhead receive`·`overhead vision`이 한 사이트 후보 릴리스 동안 돈다. compose·Dockerfile은 이미 `python3 -m site_vision.cli`다. `test_overhead_cli.py`가 두 줄을 고정한다.
- 증거: `python -m pytest src/site/site_vision/test -q` 112 passed (2026-09-30 Windows).
- gate 변화: 없음. 별칭 제거는 계획 단계 5(단계 1을 담은 사이트 후보가 한 번 나간 뒤).

## 2026-09-30 · uncommitted · feat(site-vision): D-375 map-proposal from the lane paint

- 변경: `site_vision/map_register.py` 추가. 마커 없이 `map_v2_fleet` `road_lines.stl` 페인트를 영상에 맞춰 image→map homography(지도 미터)를 제안한다: 가는 흰 선 마스크 → 주 선 방향 → 고정 2.5 cm/px 템플릿 대 배율별 재표본 영상의 거친 탐색(90°×4, 거울) → 지도 템플릿 ECC → 바닥 거리 기준 recall·precision. coverage, 가려진 쪽(`cut_sides`·`cut_directions`), `rotation_deg`, `mirrored`, 방향 차(`orientation_margin`)를 준다. `ingest.py`에 lease 보호 `GET /api/vision/sources/{id}/map-proposal`(D-360 규칙, source당 초당 1회 계산), `cli.py vision --map-paint`. 제안은 sighting·`CameraMap`에 쓰지 않는다.
- 증거: `python -m pytest src/site/site_vision/test -q` 122 passed (2026-09-30 Windows). LOCAL 실제 프레임 4장(공개 저장소 밖): 1장 수락, 손 기준 대비 중앙 오차 5.7 px, coverage 0.76, 잘린 쪽 서쪽; 3장(넓은 시야 2, 30° 기울기 1)은 거부(잘못된 수락 없음).
- gate 변화: 없음. DEVICE/FIELD PARKED 유지.
