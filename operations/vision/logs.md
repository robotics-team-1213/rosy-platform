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

## 2026-09-30 · 3c263ff0 · feat(overhead): 페어링 링크 인증서 고정 — `&pin=sha256/<b64url>` (D-341 9 첫 조각)

- 변경: `rosyov://`에 선택 키 `pin`(서버가 보내는 체인 안 인증서 하나의 DER SHA-256, base64url 무패딩; SPKI 아님)을 더했다. `tls=1` 없이 오면 `pin` 거절. 앱은 pin을 페어링과 함께 저장하고 그 링크의 OkHttp 클라이언트에만 `PinnedTrustManager`를 붙인다: 고정 인증서가 체인에 있어야 하고, CA 고정이면 leaf가 그 CA 하나를 앵커로 PKIX 검증을 통과해야 하며, 호스트명 검사(IP SAN 포함)는 OkHttp가 그대로 한다. pin 없음 + tls=1은 시스템 신뢰 그대로, 평문 ws는 그대로. 불일치는 재시도하지 않고 멈추며(D-341 10) 전용 한국어 안내를 띄운다. 사이트 쪽은 `overhead pair-link --pin-cert site.crt`(PEM 마지막 인증서 고정)와 `overhead receive --tls-cert`가 pin 든 링크를 찍는다.
- 증거: `python -m pytest src/site/overhead/test -q` 126 passed. `gradlew testDebugUnitTest assembleDebug` 녹색 142 tests(새 `PinnedTrustTest` 8개: MockWebServer TLS + 임시 CA로 CA pin 통과, leaf pin 통과, 다른 CA 거절 TLS_PIN, 위조 leaf + 진짜 CA 거절, SAN 불일치 거절, pin 없음은 시스템 신뢰로 거절, wss 링크 STREAMING 및 불일치 시 stopped). 공유 벡터 `pairing_uris`(pin 링크 1, 거절 3, `pin_pattern`)·`cert_pins`.
- gate 변화: 없음. S21 실기 TLS 송출은 DEVICE 회차(부모 세션).
- 결정: D-341의 "DER 해시, SPKI 기각"을 따른다. 콘솔 승인·1회 수령·CA PEM 전달·mDNS 재발견은 이 조각 밖이다. 링크에 CA 해시만 실리므로 CA 고정에는 프록시가 leaf+CA 체인을 보내야 한다. leaf만 보내면 leaf 고정이 되고 leaf 재발급 때 새 링크가 필요하다.
- 교훈: JDK는 서명이 안 맞는 체인을 서버 키로 싣지 못하므로 위조 체인 시험은 TrustManager를 직접 부른다.

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

## 2026-09-30 · uncommitted · refactor(vision): D-377 site_vision becomes rosy_vision in src/site/vision
- 변경: `src/site/site_vision` → `src/site/vision`, Python·ROS 패키지 `site_vision` → `rosy_vision`(`git mv`, 이동 커밋 분리). console script 정본 `rosy-vision`, 옛 `site_vision`·`overhead`는 한 사이트 후보 릴리스 동안 별칭(단계 5에서 삭제). logger `rosy_vision`, argparse `prog` `rosy-vision`. Dockerfile·`.dockerignore`·compose `python3 -m rosy_vision.cli`, mDNS 인스턴스 표시 `ROSY Vision %h`. 하네스 모듈 `site_vision` → `rosy_vision`.
- 증거: `python -m pytest src/site/vision/test -q` 112 passed (2026-09-30 Windows).
- gate 변화: 없음. SOURCE/LOCAL GO 유지. vision 이미지 재빌드·mDNS 인스턴스 확인은 DEVICE 절차.
- 결정: D-377. 와이어 이름(`rosy-overhead/1`, `/overhead/v1/frames`, `_rosy-overhead._tcp`, `/api/vision/*`, compose 서비스 `vision`, 이미지 `rosy-site-vision`)은 그대로.

## 2026-09-30 · uncommitted · feat(vision): D-375 tilt hypotheses for the paint fit

- 변경: `map_register.py` 거친 탐색을 카메라 기울기 가설 9개(pitch·roll 0, ±20°, ±35°)마다 편 선 영상에서 돌린다. 템플릿 30 px/m, 배율 12% 간격, 거울은 기울기 0에서만. 합성 시험에 pitch·roll 최대 30° 추가.
- 증거: `python -m pytest src/site/vision/test -q` 126 passed (2026-09-30 Windows). LOCAL 실제 프레임 6장(현재 설치 약 2.0 m·23° 2장, 약 30° 1장 포함, 공개 저장소 밖) 모두 수락, 손 기준 대비 중앙 오차 3.6–6.6 px, 한 번 1.2–2 s. 옆 트랙만·로터리만 자른 영상과 좌우 반전 영상은 거부.
- gate 변화: 없음. DEVICE/FIELD PARKED 유지.

## 2026-09-30 · 1f769d4a · feat(vision): pair-link이 사이트 CA 고정을 먼저 쓴다 (`--pin-ca`)

- 변경: `rosy-vision pair-link`에 `--pin-ca site-ca.crt`를 더했다. CA 고정이 기본 권장이다. `--pin-cert`(프록시가 서비스하는 PEM)와 함께 주면 그 파일에 CA가 들어 있는지 확인하고, 없으면 `site-fullchain.crt`를 만드는 법을 알리고 거절한다(exit 2). `--pin-cert`만 주면 마지막 인증서를 고정하고, leaf 하나뿐이면 재발급 때마다 새 링크가 필요하다는 경고를 stderr에 찍는다. `protocol.pem_cert_pins` 추가. README는 CA 고정 + leaf+CA 서비스(`cat site.crt site-ca.crt > site-fullchain.crt`, Caddy는 파일 전체를 보낸다)로 고쳤다.
- 증거: `python -m pytest src/site/vision/test -q` 132 passed. 앱 쪽 `PinnedTrustTest.caPinAcceptsALeafTheCaSigned`가 leaf+CA 서비스 + CA pin 경로를 이미 시험한다.
- gate 변화: 없음. 실제 사이트의 `site.crt`는 leaf 하나라 CA 고정 전에 `site_cert`를 fullchain으로 바꿔야 한다(DEVICE 회차).
- 결정: 서비스 파일에 없는 CA는 고정하지 않는다 — 폰은 서버가 보낸 체인에서만 pin을 찾는다(D-341 9).
- 교훈: 없음.

## 2026-09-30 · 80096516 · feat(vision): optional hello.lens logged and exposed
- 변경: `protocol.parse_hello_lens()`가 hello의 선택 필드 `lens {kind: wide|standard, focal_mm, hfov_deg}`를 읽는다. 없거나 잘못된 lens는 무시하고 hello를 거절하지 않는다(`validate_hello`는 그대로). ingest가 연결 시 lens를 로그로 남기고, 미리보기 프레임 헤더 `X-Source-Lens: kind=…;focal_mm=…;hfov_deg=…`와 field-proposal 본문 `lens`로 알린다(보정 선택용).
- 근거: 배포된 수신기(main의 `site_vision/protocol.py` 포함)는 모르는 hello 필드를 무시한다. 그래서 와이어 추가만으로 충분하고 `rosy-overhead/1`은 바꾸지 않는다.
- 증거: `python -m pytest src/site/vision/test -q` 127 passed (2026-09-30 Windows). 공유 벡터 `test/fixtures/protocol/overhead-ingest.v1.json`에 `hello_with_lens`, `hello_lens.{valid,ignored}` 추가(Kotlin `ProtocolTest`도 읽음).
- gate 변화: 없음. 초광각 프레임의 field_detect 결과는 DEVICE 단계에서 기록(폰 대기).

## 2026-09-30 · 646fe8e6 · feat(vision): 계산 중인 map-proposal 읽기는 마지막 완료 결과를 받는다

- 변경: `ingest.py` — 한 번에 1.2–2 s라 1 s 간격보다 길어 도중 읽기가 429 busy였다. source마다 마지막 성공 결과(`_map_done`)를 그 결과의 `frame_seq`·나이와 `X-Proposal-State: previous`로 돌려준다(새 결과는 `current`). 성공 결과가 아직 없을 때와 주체별 속도 제한만 429. 2026-10-01 병합: 아래 단일 비행·작업 프로세스 설계 위에 얹었다(바쁠 때만 이전 결과).
- 증거: `test_map_proposal_route.py` 새 시험 1개; 콘솔 헤드리스 시험에서 실제 프레임 4장(rx5·rx6·standard·wide) 모두 수락.
- gate 변화: 없음.


## 2026-10-01 · uncommitted · fix(vision): D-375 review fixes and worker process

- 변경: 독립 리뷰(APPROVE WITH FIXES)와 실기 시험 결함 반영. 방향 차는 다른 방향(적어도 180°) 후보를 늘 정밀화해서 구하고, 경쟁자가 없으면 1.0이 아니라 미정(거부). recall×precision ≥ 0.75 추가, 거울상은 잘 맞고 방향이 분명할 때만. 픽셀 중심 변환은 실제 축별 배율, 세로 프레임은 긴 변 기준. 정합은 별도 작업 프로세스 하나(`map_worker.py`)에서 돌고 source마다 한 번에 하나, 실패는 다음 계산까지 422, `rejected_fit`에는 homography를 넣지 않는다. hello 대기는 루프가 응답하던 시간만 세고, 시간 초과는 1013(재시도)으로 닫는다(4400은 틀린 hello만).
- 증거: `python -m pytest src/site/vision/test -q` 143 passed (2026-10-01 Windows). 각 거부 기준을 끄면 해당 합성 시험이 실패함을 확인. 3 s CPU 정합 중에도 새 폰 hello·프레임 읽기가 0.5 s 안에 끝나는 시험(스레드로 바꾸면 실패). LOCAL 실제 프레임 6장·렌즈 2장·실기 프레임 1장(JPEG 품질 20–40 포함) 수락, 리뷰 부분 시야 45장 중 잘못된 수락 0.
- gate 변화: 없음. DEVICE/FIELD PARKED 유지. 실기 컨테이너에서 작업 프로세스 시간 재측정은 남았다.

## 2026-10-01 · 14253f8e · fix(vision): bound hello.lens numbers, safe connect log
- 변경: `parse_hello_lens`는 `0 < v < upper`(focal_mm 1000, hfov_deg 180)로 검사한다. 400자리 정수는 `float()` OverflowError로 연결 처리기를 죽였고, `Infinity`/`1e400`은 `> 0`을 통과해 나중에 `json.dumps`가 JSON이 아닌 `Infinity`를 내보냈다. 이제 둘 다 무시한다(공유 벡터 `huge_int_focal`, Python 전용 Infinity/NaN/1e400 시험). 연결 로그의 `app_version`·`device`는 폰이 보낸 글이라 64자로 자르고 `%r`로 남긴다.
- 증거: `python -m pytest src/site/vision/test -q` 132 passed (2026-10-01 Windows).
- gate 변화: 없음.

## 2026-10-01 · 4ae81b6e · fix(vision): 사이트 CA pin만 발급(D-341 9), 패턴 fullmatch

- 변경: `rosy-vision pair-link`는 `--pin-ca`와 `--pin-cert`를 모두 요구하고, 서비스 파일이 leaf 위에 그 CA를 싣지 않거나 CA 자리에 leaf를 주면 exit 2로 거절한다(fullchain 만드는 법 안내). leaf 단독 pin은 더 이상 찍지 않는다. `receive --tls-cert`는 leaf+CA 파일일 때만 CA를 고정하고, 아니면 pin 없이 이유를 찍는다. PEM의 UTF-8 BOM을 받아들이고 해석할 수 없는 파일은 깔끔한 오류로 끝낸다. `SOURCE_PATTERN`·`PIN_PATTERN`은 `fullmatch`라 끝의 `%0A`가 더는 통과하지 않는다(Kotlin과 일치).
- 증거: `python -m pytest src/site/vision/test -q` 156 passed.
- gate 변화: 없음.
- 결정: 앱은 호환을 위해 leaf pin을 계속 받지만 사이트 도구는 CA pin만 만든다.
- 교훈: 없음.

## 2026-10-01 · uncommitted · test(vision): 4400 재시도 목록을 전환 예외로 고정
- 변경: 공유 벡터 `close_4400_reasons.retry`를 `["", "no hello"]`로 좁혀 "hello timeout"·"timed out waiting for hello"·"receiver busy"를 뺐다. 수신기 코드는 그대로(hello 시간 초과는 1013). 재시도 목록이 fatal 사유와 겹치지 않고 정확히 전환 예외임을 확인하는 시험을 더했다.
- 증거: `python -m pytest src/site/vision/test -q` 188 passed (2026-10-01 Windows).
- gate 변화: 없음.

## 2026-10-01 · 2d6d268b · fix(vision): 재연결 전 계산을 이전 결과로 남기지 않는다

- 변경: `ingest.py` — 옛 연결의 계산이 재연결로 캐시가 비워진 뒤 끝나면 `_map_done`에 들어가 "previous"가 옛 homography를 줬다. 아직 그 source의 현재 계산일 때만 남긴다.
- 증거: `test_map_proposal_route.py` 막히는 가짜 작업으로 재현하는 시험.
- gate 변화: 없음.

## 2026-10-01 · uncommitted · fix(vision): 페어링 링크는 이름(tls_host)을 기본으로, IP는 경고하는 예비로

- 변경: `cli.py` — `receive`는 링크 호스트를 `--advertise-host` > `--tls-host` > `<hostname>.local`로 정하고(D-391 `.local` 규칙으로 검증), 8.8.8.8 경로 탐지 IP는 `IP fallback:` 진단 줄로만 낸다. `pair-link --host <ip>`는 "수동 주소"·서브넷 변경·IP SAN을 설명하는 WARNING을 stderr에 내고 종료 코드 0을 유지한다. `deploy/site/README.md`·사이트 runbook §3에 "이름 기본, IP는 예비"를 적었다.
- 증거: `python -m pytest src/site/vision/test -q` (아래 결과), 새 시험 `test_overhead_link_host_name_first.py`.
- gate 변화: 없음.

## 2026-10-01 · uncommitted · fix(vision): receive 링크 호스트 안내와 오류 문구 보강

- 변경: 특정 `--host` 주소로 바인드해도 링크는 이름이며 "link host is <name>.local (D-391); use --advertise-host <ip> to pair by IP (fallback, needs an IP SAN)"라고 한 줄 알린다. `--tls-host`는 `<name>.local`만 받고(FQDN은 `--advertise-host`) 오류가 그쪽을 가리킨다. 호스트명 오류는 원래 `gethostname()` 값과 밑줄·점 불가를 말하고, 경로 탐지 실패는 `IP fallback: unknown (no route)`로 쓴다.
- 증거: `python -m pytest src/site/vision/test -q` 206 passed (2026-10-01 Windows).
- gate 변화: 없음.

## 2026-10-01 · uncommitted · feat(vision): D-341 3단계 — 페어링 자격 동기화와 회수 닫기

- 변경: 새 `rosy_vision/pairing_sync.py` — `PairedCredentials`(Fleet 목록의 `token_sha256`만 보관, source별 상수 시간 대조, 첫 동기화 전·마지막 정상 목록 10분 초과는 상태 불명)와 `PairingSync`(전용 데몬 스레드에서 2 s마다 `GET /api/fleet/pairing/v1/credentials?role=overhead-camera`, `pairing_sync_token` bearer, 실패해도 마지막 정상 목록 유지, URL·헤더·본문은 기록하지 않음). `ingest.py` — `paired=`가 있으면 정적 토큰 0개로도 기동; 업그레이드 단계는 정적 토큰 또는 동기화 digest, 상태 불명이면 `503` + `Retry-After: 2`, 모르면 `401`; hello 단계는 paired source면 그 source의 digest만 대조해 불명 `4503`, 회수·모름 `4401`; `enforce_paired_credentials()`가 목록에서 빠진 연결을 `4401`(불명은 `4503`)로 닫고, 그 사이 들어온 프레임은 `_handle_frame`에서 버린다. websockets 서버 로거를 INFO로 고정해 DEBUG에서도 Authorization 헤더가 기록되지 않는다. `protocol.CLOSE_CREDENTIAL_UNKNOWN = 4503`(벡터 `credential_unknown`). `vision_config.py` — `credential: static|paired`(static은 `phone_token_env` 필수, paired는 금지, 어기면 기동 거절). CLI `vision --pairing-sync-url/--pairing-sync-token-env/--pairing-sync-ca`: paired source가 있으면 필수, 없으면 설정 자체를 거절, 동기화 비밀이 폰·sighting·preview 비밀과 같으면 거절, preview 비밀 검사는 폰 토큰이 없는 paired source를 다룬다.
- 결정: 동기화는 이벤트 루프 밖 스레드에서 돌고, 루프에는 `call_soon_threadsafe`로 닫기 검사만 올린다(2026-10-01 굶주림 교훈). 닫기가 늦어도 회수된 자격의 프레임은 다음 동기화 직후부터 버려진다. 상태 불명은 이미 붙은 paired 연결도 `4503`으로 닫는다(회수가 전파되지 못하는 동안 계속 받지 않는다). 업그레이드에서 paired source가 있고 상태 불명이면 모르는 bearer도 `503`이다(그 순간에는 페어링 자격과 구분할 수 없다).
- 증거: 새 시험 `test_pairing_sync.py` 14(호출 스레드가 GIL을 쥔 채 도는 동안에도 동기화가 5회 이상), `test_ingest_paired_credentials.py` 9(실제 2 s 동기화 스레드로 회수 후 5 s 안에 `4401`), `test_vision_config.py` 3, `test_vision_cli.py` 7, `test_protocol.py` 1 단언 — 구현 전 실패 확인 뒤 녹색. `src/site/vision/test/` 223 passed(2026-10-01 Windows).
- gate 변화: 없음(LOCAL).

## 2026-10-01 · uncommitted · test(vision): D-341 합성 종단 시험 — 요청부터 회수 4401까지

- 변경: 새 `test/test_pairing_e2e.py`. 시험의 tmp 폴더에 일회용 CA·leaf(SAN `rosy-e2e.local`·`localhost`·127.0.0.1, AKI/SKI 포함)를 만들고, Fleet(실제 `create_app` + uvicorn TLS, 자기 스레드)과 Vision(`_vision_ingest`로 같은 `site-cameras.yaml`에서 만든 수신기 + 실제 2 s `PairingSync` 스레드)을 127.0.0.1에 띄운다. 합성 폰이 첫 연결 leaf를 검증 없이 기록(SAN에 `tls_host` 확인)하고 그 leaf로만 요청→공개→(운용자 코드 입력 승인)→1회 수령→받은 CA로 leaf 체인 확인·지문 대조→확인→받은 CA 하나만 믿는 WSS로 hello·프레임을 보낸다. 이어서 Fleet 정지 → 오래된 목록으로 살아 있는 연결 `4503`, 재접속 `503` → 같은 DB로 Fleet 재기동 → 재접속 성공 → 콘솔 회수 → `4401`(5 s 안), 재접속 `401`.
- 결정: 일반 시험 묶음에 둔다(Windows 벤치 PC에서 약 10 s, 3회 반복 9.5–9.9 s). Vision의 상태 불명 한도만 600 s → 3 s로 줄였다. 전체 소요 시간 단언은 부하 때 흔들릴 수 있어 두지 않고, 회수 5 s 단언만 둔다. 개인 키는 tmp에만 생기고 커밋되지 않는다.
- 증거: `python -m pytest -q -p no:cacheprovider src/site/vision/test/test_pairing_e2e.py` 1 passed(13.4 s 포함 수집). 처음 실행은 Python 3.14의 엄격한 X.509 검사(AKI 없음)로 실패해 시험용 인증서에 키 식별자를 더했다.
- gate 변화: 없음(LOCAL). Compose 스택 종단(D-341 LOCAL 표의 Compose 항목)과 DEVICE는 별도.

## 2026-10-01 · uncommitted · chore(vision): D-341 저장소 가드 정리 — 역할 경계·크기 판정·비밀 스캔

- 변경: `test/architecture/test_app_roles.py`의 Vision 경계가 sighting 쓰기 말고도 D-341 12항의 `/api/fleet/pairing/v1/credentials` 읽기를 허용한다(다른 Fleet 경로는 여전히 금지). `test_module_structure.py`에 `ingest.py` 671줄 판정(accept: 한 연결 표를 공유하는 한 소유자, digest 저장·동기화 스레드는 `pairing_sync.py`)과 `fleet` 패키지 재판정(21476)을 적었다. 비밀 스캔이 이름만 보고 잡은 호출 자리를 고쳤다(`cli.py` `known_tokens`, 종단 시험 `poll_auth=`, Fleet 시험 `shared_secret`) — 스캐너는 그대로(D-256).
- 증거: `test/architecture/` 75 passed + 남은 1 failed는 main에 이미 있던 `schemas.py` 1092줄 판정. `test/test_release_boundary_guards.py` 72 passed + 남은 1 failed는 main의 `docs/logs.md:4077`·`docs/plans/2026-10-01-gemini-robotics-samples-research.md:5`(이 브랜치 파일 아님). vision 224 passed, foundation 389 passed.
- gate 변화: 없음.


## 2026-10-01 · uncommitted · fix(pairing): Vision 자격 동기화는 https와 사이트 CA 고정이 필수

- 변경: 보안 리뷰 2번. 평문 `http://`나 CA 없는 동기화 URL은 기동 때 거절한다. 둘 중 하나라도 허용하면 LAN의 위장 서버가 동기화 토큰을 읽고 자기 digest 목록을 내 운용자 승인 없이 카메라 자격을 살릴 수 있었다(D-341 9·12항).
- 증거: `test_pairing_sync.py` 신규 매개변수 시험 2건, Vision 시험 전체 통과.
- gate 변화: 없음.

## 2026-10-04 · uncommitted · fix(site): D-457 마커 우선·무마커 폴백

- 변경: 현행 모듈에 source-token 표시 추적과 승인 보정을 통합. 마커 명시 대응 우선, 없으면 익명 검출·신뢰 가능한 map pose 대조. UI/UX 리팩터링 없음.
- 증거: 공유 벡터·Vision·Fleet·브라우저 전환 조건을 호스트에서 검증. 실제 사이트는 두 등록 로봇과 S21 영상 연결 조회만 확인. 후보 배포·빈 트랙 학습·실물 위치 오차는 미완료.
- gate 변화: 없음. SOURCE/LOCAL 변경이며 DEVICE/FIELD 완료 주장 없음. 기존 등록·credentials 보존.


## 2026-10-05 · uncommitted · fix(test): signal observer exact-source collection

- 변경: signal observer 테스트는 private exact-file 로더로 자신의 실제 소스를 읽는다. 다른 테스트가 generic observer를 먼저 읽어도 관측 타입을 섞지 않는다. 프로덕션 standalone CLI 및 카메라/명령 경로 변경 없음.
- 증거: 실제 Gazebo observer가 generic observer를 차지한 fresh-process에서 기존 모듈과 검색 경로 보존, ObserverConfig/make_source 타입 동일성 확인. T2/T5/T3/Vision 양방향 각 105 PASS.
- gate 변화: 없음. SOURCE/LOCAL 테스트 수선만. 실제 카메라·ROS·기기 수용 주장 없음.


## 2026-10-06 · uncommitted · feat(vision): D-484 필드 경계 자동 캘리브레이션

- 변경: 소스 설정 `calibration_source: field_boundary`가 코너 ArUco 마커 대신 D-360 흰 경계 사각형으로 측정 캘리브레이션을 유지한다. 신규 `field_calib.py`(no_field→orientation_pending→calibrated⇄stale 상태 머신, 급변 재획득, 상실 시 orientation 초기화)가 주기(기본 1 Hz) 감지를 받아 호모그래피를 만들고, orientation은 D-375 페인트 정합(map_worker 프로세스, 단일 flight)의 map_to_image로 맵 코너↔감지 코너 최근접 대응(거리 게이트+순환 일대일)으로만 확정한다. worker가 로봇 ArUco 마커를 매 프레임 투영하고 미리보기가 worker 수용 사각형으로 자동 보정(rectification mode "auto", `X-Frame-Rectified: auto`, `X-Field-Calib`, 감지 없으면 원본+`X-Frame-State: field-unavailable`)한다. 폰 앱·전선 불변.
- 증거: `test_field_calib.py`(신규 13본: 상태 전이·게이트·회전 판정), worker/project/config/preview 시험 확장, contracts/foundation·operations/fleet 스위트 통과. 호스트 통과는 장치·현장이 아니다: 실제 폰 프레임에서 orientation 확정·재획득·장시간 안정성은 DEVICE/FIELD 게이트 별도.
- gate 변화: 없음. SOURCE/LOCAL 테스트 통계만 갱신. D-318 수동 보정·D-360/D-375 제안 엔드포인트는 그대로 동작.

## 2026-10-07 · 556dd1954 · feat(vision): 카메라 차선 지도 초안 생성

- 변경: D-497: 현장 카메라 원본과 확인된 metric 보정·차로 폭으로 rosy.site_map/1 초안을 생성하는 rosy-lane-map. 직접 HTTPS preview lease 읽기·신선도·원본 검사, 흰 페인트 중심선·교차점·원형 경로, 근거 JSON, 덮어쓰기 거절. 초안만 생성, 활성화·주행 없음.
- 증거: 81 affected geometry/store/browser checks passed (latest loop regression rechecked), 0 NEW. Direct source-command test on the actual site host read a fresh raw S21 frame over pinned HTTPS and generated a 12-place/10-lane draft. That draft imported in local Chromium at 1440/390 px without activating or moving a robot. Source command was ephemeral; permanent deployment and field geometry acceptance are unproven. Independent review found an attached-loop loss; fixed and independently rechecked.
- gate 변화: 없음. SOURCE/LOCAL 근거 추가; 장치 상시 배포·현장 지도 정확도 수용은 별도다.

## 2026-10-07 · uncommitted · fix(vision): camera-map integration contract pins

- 변경: D-497 command registration and existing-draft confirmation are explicitly pinned in their existing contract tests. Existing aliases and confirmation ownership remain asserted.
- 증거: 18 CLI/dialog checks passed after fixing the two NEW findings from pre-push; the remaining candidate checks continue.
- gate 변화: SOURCE only; deployment and installed readback pending.

## 2026-10-07 · uncommitted · fix(vision): 도로 경계와 흰색 무늬를 구분하고 ROI 가장자리 연결 유지

- 변경: 넓은 흰색 테두리를 포함하고 출력 ROI 밖의 경계도 관측한다. 실제 도로 기준점으로 연결 영역을 선택한다. 흰 페인트의 전역 연결 여부로 막다른 도로를 제거하지 않는다. 최종 명령·활성화 경로는 유지한다.
- 증거: 실제 저장 영상 수정본은 연결된 5 places/7 lanes로 왼쪽 연결을 유지하며 기존 비도로 p4–p11, p15–p16, p21–p22 선분이 제거됐다. 합성 넓은 경계·ROI·U 무늬와 기존 가림·원형·교차점 회귀를 검사한다. 배포·현장 수용은 별도다.
- gate 변화: SOURCE/LOCAL 수정 근거만 추가. FIELD 수용은 미확인이다.

## 2026-10-07 · uncommitted · fix(vision): 직선 차로를 원본 해상도 경계 중심에 맞춘다
- 변경: 저해상도 검출·세선화·간선 간소화의 중심 오차를 원본 해상도 관측 경계로 보정한다. 기존 페인트 주변만 관측하고 보정량 중앙값으로 반사 잡음을 줄인다. 측정 폭 범위와 이동 상한을 확인하고, 지점·연결·가림 구간은 유지한다. 최종 간소화 허용 오차를 줄인다
- 증거: 합성 고해상도 사선 직선 회귀 포함 관련 pytest 53 passed, known_failures 0 NEW; 최종 생성기 회귀 3 passed. 독립 검토 PASS. 저장된 현장 영상은 5 지점·7 차로 유지; 왼쪽 위 관측 중심 최대 오차 8.3→4.8 mm, 왼쪽 아래 4.0→1.8 mm. 실제 거리 정확도는 보정 수용 별도. Fleet 초안 revision 비교 교체·GET 일치·활성 지도 불변 확인
- gate 변화: SOURCE/LOCAL 근거만 추가. 새 생성기 설치·물리 주행·보정 FIELD 수용은 미확인
- 관제 확인: 실제 Fleet를 SSH 경유 Chromium으로 열어 초안의 153개 경로 점과 SVG 좌표를 비교했다. 최대 차이 0.000032 px, 1440·390 px에서 가로 넘침 없음. 활성 주행 지도는 유지했다. 직사각형 영상 중첩 화면은 별도 로컬 화면 검증이며 새 UI 배포 증거는 아니다
- 결정: D-497 2항 구현 보강
- 교훈: 유효한 도로 영역의 세선화 결과가 실제 양쪽 페인트의 중심과 일치하는 것은 아니다

## 2026-10-08 · uncommitted · feat(vision): D-513 7 화면 회전 키 허용
- 변경: `site-cameras.yaml` source의 `display_rotation_deg`를 허용 키에 넣는다. Vision은 값을 쓰지 않는다(Fleet 관제 표시 전용).
- 증거: Vision 설정·예시 시험 통과.
- gate 변화: SOURCE/LOCAL만.

## 2026-10-08 · uncommitted · refactor(vision): D-513 7 화면 회전 키 제거
- 변경: `display_rotation_deg` 허용을 되돌린다. 관제가 보정에서 회전을 계산하므로 설치 키가 필요 없다.
- 증거: Vision 설정·예시 시험 통과.
- gate 변화: SOURCE/LOCAL만.

## 2026-10-08 · uncommitted · feat(vision): D-472 LED 점멸 검출과 Fleet 판정
- 변경: 순수 검출기 `track/led_identity.py`(blob 둘레 고리의 HSV 색 비율, 프레임 간 blob 연결, 켬/끔/켬 시간). 한 사슬만 맞고 창 전체 프레임·신선도·revision 하나일 때만 `matched`, 아니면 `ambiguous`(none·multiple·frames_missing·stale·calibration_changed)와 근거 숫자. 추적 워커가 Fleet `identity_challenge` 창 동안 고리를 재고 창이 끝나면 판정 하나를 `POST /api/fleet/detections/identity`로 보낸다(숫자만, 영상 없음)
- 증거: 합성 프레임 시험(일치, 두 blob, 가림, 프레임 누락, 다른 색, 설정 임계) 6건과 워커 1건. 임계값은 잠정, ceiling_north 실측 전
- gate 변화: 없음. FIELD 실측(LED 가시성·색 분리·시각 오차) 미실시
- 결정: D-472 addendum 6항 측정 먼저

## 2026-10-09 · uncommitted · fix(vision): D-539 운영자 재학습 배경을 재시작 뒤에도 쓴다
- 변경: `BackgroundStore`(source마다 npz 하나, JPEG q95, 트랙 밖 검게)와 `BackgroundBlobDetector.relearn()`. 운영자 재학습(Fleet `relearn_seq` 증가)의 마지막 30프레임만 revision·작업 크기와 함께 저장하고, 프로세스의 첫 학습에서 같은 revision·크기면 재생해 바로 검출한다. CLI `--track-state DIR`, compose named volume `vision_state:/var/lib/rosy-vision`
- 원인: 2026-10-09 현장 `site-af80a5b37eec`가 09:52 자동 갱신으로 재시작하며 매트 위 두 로봇을 배경으로 배웠다(`relearn_seq` 0, 로봇 NO_POSE, 빈 곳 미확인 2개). 매일 06:08 재부팅도 같다
- 증거: 합성 프레임 시험 6건(재시작 재생·저장본 없음·시작 학습 미저장·다른 revision·트랙 밖 0·손상 파일)과 워커 1건
- gate 변화: 없음. 현장 배포 뒤 빈 매트 재학습 → Vision 재시작 → 주차 로봇 검출 확인 전

## 2026-10-09 · uncommitted · fix(vision): D-547 배경에 굳은 로봇 추측과 유령 치유
- 변경: `BackgroundBlobDetector`가 모델이 준비될 때 학습된 배경에서 로봇 크기의 어둡고 단단한 덩어리(max(B,G,R) < 트랙 중앙값×0.6, footprint 창, solidity ≥0.8, 장단비 ≤2)를 후보로 잡는다. 그 자리가 배경과 같으면 점수 ≤0.35로 보고하고, 전경이면서 90% 이상 더 이상 어둡지 않으면 유령으로 보아 그 blob을 보고하지 않고 학습 프레임의 그 자리만 실시간 바닥으로 바꿔 MOG2를 다시 세운다. 프로토콜·`processor_revision` 변경 없음
- 원인: 2026-10-09 현장 재시작 때 매트 위 두 로봇이 배경으로 굳어 Fleet이 rosy_26/rosy_60을 찾지 못함. D-539는 빈 매트 재학습 뒤에만 도움이 됨
- 증거: 합성 프레임 시험 5건(굳은 로봇 추측·표지판/기둥/띠 제외·유령 치유·이동한 로봇·깨끗한 학습)과 D-539 시험 1건 기대값 변경. 실프레임 오프라인 평가(`X:\DevTemp\bg-fallback\eval.py`): A 후보 2/2 실제 로봇·24/24 검출·오차 1.1/6.1 cm, B 유령 프레임 0, C 기준선과 같음
- gate 변화: 없음. 현장 Vision에서 실제 떠남 확인 전

## 2026-10-09 · uncommitted · fix(vision): D-547 리뷰 반영 — 유령 확정·전체 blob 치유·명목 footprint
- 변경: 유령은 학습된 바닥 색(트랙 중앙값 또는 고리의 흔한 색 32개, BGR 거리 40)이 연속 3프레임일 때만 확정하고, 확정 전에는 그 자리를 보고하지 않는다. 치유는 유령 영역과 거기 닿는 전경 blob 전체의 바닥 색 픽셀을 덮는다. 추측의 footprint는 명목 0.165 m
- 원인: 독립 리뷰가 한 프레임 가림(손·종이)이 유령으로 치유되어 로봇이 사라지는 것, 로봇의 밝은 부분이 고리로 남는 것, 추측 footprint가 어두운 부분만(0.14 m) 재는 것을 찾음
- 증거: 합성 프레임 시험 추가(한 프레임 가림, 3프레임 확정, 덱 포함 전체 치유와 재주차, 후보 없을 때 프레임 해제, relearn/SCENE_CHANGED 후보 해제, D-539 재생 뒤 치유와 저장 파일 불변). 실프레임 평가 A·B·C 통과
- gate 변화: 없음

## 2026-10-09 · uncommitted · fix(vision): LED 확인 판정이 현장에서 늘 frames_missing이었다 (D-472)
- 변경: 트래커가 확인 요청과 상관없이 최근 `RING_S`(창 6 s + 설정 읽기 지연 2×2 s + 1 s)의 LED 표본을 확인 색(파랑·주황)마다 모아 두고, 판정은 그 링에서 창 안 표본만 쓴다. 링은 최신 `MAX_SAMPLES`까지. 판정 규칙(`max_gap_s` 0.7 s, 창 끝 포함)은 그대로다.
- 증거: 현장 2026-10-09 Fleet 갱신 뒤 9dfk(rosy_26) 이동 중 `identify`가 처음 수락(200)됐으나 판정은 `UNKNOWN frames_missing`. 요청은 2 s 설정 읽기로 늦게 도착하고 표본은 그때부터만 모여 창 앞이 비었다. 새 시험 `test_frames_before_the_challenge_arrives_still_fill_the_window` 포함 30 passed.
- gate 변화: SOURCE. 현장 vision 갱신 뒤 LED 확인 matched 확인.

## 2026-10-09 · uncommitted · refactor(vision): LED 링 뒤 쓰이지 않는 challenge 인자 제거
- 변경: 링이 요청과 상관없이 표본을 모으므로 `_detect`·`_identity_sample`의 `challenge` 인자를 지웠다. `MAX_SAMPLES`가 약 5.8 fps 위에서 링 범위를 정한다는 한계를 주석으로 남겼다(독립 검증 지적).
- 증거: test_overhead_track_worker.py·test_led_identity.py 30 passed.
- gate 변화: 없음(동작 같음).

## 2026-10-09 · uncommitted · fix(vision): D-547 addendum 후보 없는 유령 치유
- 변경: 후보가 덮지 않는 로봇 크기(0.06–0.39 m) 전경 blob도, 실시간은 바닥 색이고 학습된 배경은 트랙 중앙값에서 멀면 유령으로 보아 보고하지 않고 같은 자리 연속 3프레임 뒤 치유한다. 학습 프레임은 프로세스 동안 보관(30장, 640×360에서 약 20 MB). 학습된 배경 캐시를 후보 검색과 분리
- 원인: 2026-10-09 16:38 현장에서 8kcn이 떠난 자리에 유령(점수 0.89–0.95)이 남음. 15:20 학습에서 후보 검색이 그 로봇을 놓쳐 1–6항 치유가 돌지 않음
- 증거: 합성 프레임 시험 3건(후보 없는 유령 치유, 보이는 로봇 비치유 ×3, 의자·바닥 색 종이 비치유)과 학습 프레임 보관 기대값 변경. 실프레임 D4 재현: main 유령 9/9 → 0/9, 8kcn 9/9 유지. A·B·C 변화 없음
- gate 변화: 없음. 현장 확인 전

## 2026-10-09 · uncommitted · fix(vision): D-547 addendum 리뷰 반영 — 어두운 배경 조건, 확정 전 보고
- 변경: 후보 없는 유령은 학습된 배경이 절반 이상 어두울 때만(전체 프레임 지도로 먼저 거름), 확정 전에는 점수 0.35 이하로 보고, 처음 자리 기준 연속 3프레임 뒤 치유하고 지도 x/y·footprint를 로그로 남긴다. CALIBRATION_REQUIRED에서 연속 기록 지움, 치유 영역 안 후보 제거, 팽창 커널 상수화
- 원인: 독립 리뷰가 파란 사각형 위 회색 상자가 첫 프레임부터 숨고 치유되어 치운 뒤 유령이 남는 것(S1), 확정 전 숨김, blob 16개에서 30–47 ms를 찾음
- 증거: 합성 시험(테이프 위 색 덱 로봇, 파란 사각형 위 상자, 확정 전 0.35 보고, 의자 부분)과 각 조건 변이 시 실패 확인. 실프레임 D4/D5: 0.35 보고 2프레임 뒤 유령 0, 8kcn 9/9. A·B·C 변화 없음. blob 16개 약 9 ms
- gate 변화: 없음

## 2026-10-09 · 3284df22e · feat(vision): 천장 검출 minMarkerPerimeterRate 0.015 (D-562)
- 변경: `detect.py`가 `_detector_parameters`가 돌려준 객체에 `minMarkerPerimeterRate = 0.015`를 둔다(4.6 segfault 회피로 새 객체를 만들지 않음). 로봇 윗면이 40 mm 스티커만 받기 때문이다.
- 증거: 실 천장 프레임 + 승인 보정 위 88배치 시뮬레이션에서 40 mm 스티커 39/88 → 54/88, 실프레임 124장의 오검출 수는 기본값과 같은 3(번호 17, 칠한 원·케이블). 새 시험 `test_vision_detect.py`(10 px 마커는 0.015에서만 검출). 원격 로그 X:/DevTemp/marker-id-plan/run-1.txt.
- gate 변화: SOURCE. 현장 Vision 갱신 뒤 실제 스티커로 MARKER 확인은 열림.

## 2026-10-09 · uncommitted · feat(vision): D-560 S1 지도 평면 영상 `mode: map`
- 변경: lease `rectification`에 `{"mode": "map"}`(다른 필드 거절). 트래커가 Fleet에서 읽은 승인 보정 기록을 `IngestServer.report_calibration`으로 ingest에 넘기고(두 번째 Fleet 클라이언트 없음), `/frame`이 `rectify.map_plane_jpeg`로 최신 원본을 지도 평면(track_bounds_m + 0.15 m, 400 px/m, 긴 변 ≤ 1920 px, 화면 밖 어두운 고정색)에 편다. 헤더 `X-Frame-Rectified: map`·`X-Frame-Plane`·`X-Frame-Calibration`, 기록 없음·source·map·렌즈·비율 불일치는 409 `plane-unavailable`(원본 대체 없음). 펴기는 `asyncio.to_thread`로 이벤트 루프 밖에서 (프레임, revision)마다 한 번. API Reference §10.6.1, v1.166
- 증거: 원격 pytest operations/vision/test 428 passed, operations/fleet/test/test_server_app.py 41 passed, known_failures 0 new. 실프레임(`ceiling_north`, `paint-7b220d432c2a`) 평면 1244×624에 활성 지도 차선 6개를 D-560 식으로 그려 도로 가운데 놓임을 눈으로 확인(X:\DevTemp\cam-map-plane-s1\plane-lanes.png)
- gate 변화: SOURCE/LOCAL. Fleet 세 화면(S2)과 현장 확인(S4) 전

## 2026-10-09 · uncommitted · fix(vision): D-560 S1 독립 리뷰 반영, API v1.167
- 변경: main이 v1.166(D-531 굽이 단계)을 먼저 가져가 D-560 S1은 API Reference v1.167이다(위 항목의 v1.166은 v1.167로 읽는다). `X-Frame-Plane`의 `max_x`·`min_y`를 반올림한 영상 크기에서 다시 정해 사각형이 영상 크기 / `px_per_m`와 같다. `MapPlane`이 펴기에 쓴 행렬을 싣고, 헤더 식과 1e-9 m로 맞는지 시험한다. 보정 revision은 `[A-Za-z0-9._:-]{1,96}`만 받는다(헤더로 나간다). 공유 펴기 작업이 자기 실패를 회수한다. 평면은 그 source에 `--track`이 켜져 있어야 나온다는 문장을 §10.6.1과 ADR S1에 넣었다
- 증거: 원격 pytest 결과는 이 브랜치 보고에 남긴다. 실프레임 평면 1244×624 다시 확인(X:/DevTemp/cam-map-plane-s1/plane-lanes.png)
- gate 변화: 없음
## 2026-10-09 · uncommitted · feat(vision): D-564 장소 마커 투영과 전송
- 변경: `place_markers` 설정(공유 검사), `project_place_markers`(로봇 마커와 같은 호모그래피·`heading_edge`, 높이 보정 없음), 워커가 0.5 s에 한 번 이하로 `/api/fleet/place-markers`에 보내고 실패는 유형만 로그.
- 증거: `test_vision_place_markers.py`, `test_vision_config.py` 포함 vision 전체, 모델 PC exit 0, 신규 실패 0.
- gate 변화: 없음(SOURCE).

## 2026-10-10 · uncommitted · feat(vision): D-587 이름 있는 천장 로봇 마커를 sighting으로
- 변경: 추적 단계가 승인 보정(D-457)을 쓴 프레임에서 `robot_markers`의 마커를 네 모서리 투영 → 윗면 높이 0.125 m 시차 보정 → 모서리 기하 문턱 → URDF 부착(−0.017, 0)과 로봇별 `marker_yaw_offset_deg`로 로봇 자세를 만들어 `calibration_source: approved_record` sighting으로 보낸다(`track/marker_sightings.py`). `project_frame`도 같은 부착·오프셋을 쓴다. 같은 프레임에 이미 sighting이 나간 로봇은 다시 보내지 않는다. 렌즈 FOV가 없으면 보내지 않는다.
- 증거: 현장 원본 150장(2026-10-10 01:15, 로봇 정지)을 이 코드로 돌려 rosy_40 150/150, rosy_41 148/150 전송, 방향 표준편차 0.09°/0.57°(최대 0.7°/1.7°), 위치 표준편차 0.3 mm 이하. 모델 PC pytest operations/vision/test + tools/calibration 506 통과, known_failures 0 new.
- gate 변화: SOURCE. 사이트 릴리스·설정 설치·주행 확인 전

## 2026-10-10 · uncommitted · feat(vision): D-596 LED 판정 2–3 fps, 동시 요청, 배경 멈춤

- 변경: `track/led_identity.py` `led-identity/2` — `min_off_s` 0.8, `max_off_s` 2.2, `max_gap_s` 1.1, 익명 blob 하나일 때 정색 표시(`evidence.mode: steady`). 추적 워커가 `identity_challenges`의 요청마다 판정하고, 열린 창 끝까지 `BackgroundBlobDetector.hold`로 배경을 얼린다(학습 프레임·장면 변경 재학습·유령 치유 없음, 박힌 로봇의 추정은 램프가 켜져도 유지)
- 증거: 현장 프레임 2묶음(2026-10-10 06:47, 2.5 fps, 간격 최대 0.76 s)에 후면 빛을 그려 넣은 6 s 창 264개: 이전 값 6 `matched`(나머지 frames_missing), 새 값 264. 빛 없는 대조 0. 모델 PC pytest 통과
- gate 변화: SOURCE. 실제 램프 가시성 미측정

## 2026-10-10 · uncommitted · fix(vision): D-595 수락한 보정 고정
- 변경: `field_calib.FieldCalibrator`가 처음 받아들인 필드 사각형을 고정한다. 문턱 안 다시 감지는 사각형·호모그래피를 바꾸지 않고 `drift_px`로만 보고하고, 문턱 밖 이동이 3번 이어질 때만 새 사각형을 받는다. `track.calibration.choose`는 쓸 수 있는 Fleet 승인 기록을 먼저 쓰고, 그 프레임의 모서리 마커는 기록이 없을 때만 쓴다(D-457 2의 마커 우선을 대체).
- 증거: 현장 읽기 표본(2026-10-10 05:12–05:20, 변경 없음) 승인 기록 `paint-7b220d432c2a`·평면 사각형 20회 같음, 필드 제안 20회 `field runs past the frame`. 원격 pytest 결과는 브랜치 보고에 남긴다.
- gate 변화: 없음(SOURCE).
