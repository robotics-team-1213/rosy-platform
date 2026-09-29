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

## 2026-09-30 · feat/overhead-app-ceiling-ux · 천장 설치용 앱: 다음 행동을 말하는 상태, 화면 꺼짐 송출, 기기 상태

- 변경: 연결 실패를 원인(닿지 않음·거부·이름 못 찾음·TLS·토큰·같은 이름 중복·Wi-Fi 없음)으로 나눠 다음 행동을 한 문장으로 보여 주고, 원문은 `자세히` 뒤에 둔다(`NetworkFailure`, `ProblemGuide`). 배터리·충전·온도를 화면과 상시 알림에 보이고 열 상태 MODERATE 이상이나 충전 없이 20% 미만이면 경고한다(`DeviceHealth`, 휴대폰 안에서만; 선로 변경 없음). 수신기 `status`로 코너 마커 점 4개와 보이는 로봇을 보인다(`CornerGuide`). `버림`을 `건너뜀`으로 바꾸고 뜻을 한 줄로 적었으며, 자동 조정으로 낮아진 JPEG 품질을 보인다. 송출 중에도 연결 설정을 읽기 전용으로 연다. 화면 글자가 검정으로 떨어지던 테마 결함(Column에 Surface가 없음)을 고쳤다.
- 증거: Android `testDebugUnitTest` 117 passed, `assembleDebug` 성공(JDK 21, Windows). Galaxy S21(Android 15) 실기에서 임시 수신기(`receive --port 8096`)로 확인: 화면 잠금 65초 동안 수신 70표본 최소 2 fps, `age_ms` 최대 178 ms, seq gap 0. 잠금 화면 깨우기·강제 deep idle에서도 3 fps 유지. 카메라는 이미 서비스 수명에 묶여 있어 (b) 현상은 이 빌드에서 재현되지 않았다. 닿지 않음·401·자세히·기기 경고(배터리/열 상태는 `dumpsys battery`·`cmd thermalservice`로 모의)·읽기 전용 설정 화면을 캡처했다(`private/validation/2026-09-30-overhead-app-ceiling-ux/`).
- 남은 일: 어댑터 `status`의 `corners_seen`·`robots_seen`이 항상 빈 목록(`ingest.py` 자리값)이라 설치 안내가 늘 0/4를 보인다. Vision이 실제 값을 채워야 한다. 프로토콜에 휴대폰→수신기 상태 메시지가 없어 기기 상태는 현장 PC에 가지 않는다. Windows 방화벽이 닫힌 포트의 SYN을 버려 수신기가 꺼진 경우도 `닿지 않음`으로 보인다.
- gate 변화: 없음. 실기 앱 확인은 임시 수신기 기준이며 Vision/Fleet 종단과 현장 수용은 아니다.
