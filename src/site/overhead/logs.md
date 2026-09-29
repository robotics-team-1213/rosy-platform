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

## 2026-09-30 · uncommitted · test(overhead-app): D-358 S1 DiscoveryVectorsTest

- 변경: Gradle 단위 시험에 시스템 속성 `rosy.discovery.vectors`(`test/fixtures/protocol/discovery-txt.v1.json`)를 더했다. `OverheadServiceRecord`/`RobotCoreServiceRecord`에 벡터 어휘로 사유를 내는 `rejection()`을 두고 `parse()`가 그것을 쓴다. 받는 집합은 바뀌지 않았다.
- 증거: `gradlew testDebugUnitTest` 95 tests, 0 failures. 변이 증명: 벡터 기대 사유 하나를 바꾸면 Kotlin도 적신.
- gate 변화: 없음.
- 결정: D-358 5.1. 로봇 레코드는 주소·호스트·AP·legacy를 아직 보지 않는다. 앱 동작 변경이라 이번 범위 밖이고, 시험에 `knownRobotDivergence` 8건으로 못 박았다(고치면 시험이 목록 삭제를 요구한다).
- 교훈: 없음.
