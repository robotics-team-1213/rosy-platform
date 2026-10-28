---
module: rosy_vision
logical_modules: []
owner: SITE
last_verified: { commit: "a8199fd9", date: 2026-09-30 }
gates:
  SOURCE:
    state: GO
    evidence: "D-318 adds bounded, signed Vision-only OpenCV lens and plane transform for direct preview. Raw latest frame for ArUco/sightings remains unchanged; ROS-free and no cmd_vel. Local suite 86 passed (2026-09-28 Windows). D-374 stage 1 rename overhead -> site_vision, then D-377 src/site/site_vision -> src/site/vision, package rosy_vision, console script rosy-vision (site_vision and overhead kept as aliases): 112 passed at a8199fd9 (2026-09-30 Windows)"
    cmd: "python -m pytest src/site/vision/test -q"
  LOCAL:
    state: GO
    evidence: "86 passed (Windows), including synthetic perspective warp, lease validation, raw-frame immutability, and direct preview readback. Packaged Docker preview returned authorized transformed latest-only frames in source browser; no page errors/horizontal overflow at 1920/390/320 px. Synthetic only; no measured calibration, phone/Ubuntu site acceptance, DEVICE, or FIELD"
    cmd: "python -m pytest src/site/vision/test -q && (cd src/site/cam && gradlew testDebugUnitTest --rerun-tasks --no-daemon) && docker compose -f deploy/site/compose.yaml build && docker compose -f deploy/site/compose.yaml up -d"
  ROS-SIM:
    state: N/A
  ARTIFACT:
    state: N/A
  DEVICE:
    state: PARKED
  FIELD:
    state: PARKED
adrs: [D-257, D-261, D-269, D-318, D-374, D-375, D-377, D-472, D-497, D-636, D-655, D-772, D-774, D-775]
plans:
  - docs/plans/2026-09-30-app-identity-rename-plan.md
  - docs/plans/2026-09-26-overhead-camera-android-app-design.md
  - docs/plans/2026-09-26-middleware-device-server-contract-integration.md
  - docs/plans/2026-09-28-site-camera-preview-rectification.md
  - docs/plans/2026-10-11-compact-camera-calibration.md
  - docs/plans/2026-10-11-mapless-fleet-control.md
---
## 현재 상태 (2026-09-27)

- D-261 ingest와 D-257 display-only CPU vision path는 source별 최신 JPEG를 보관하고, fresh frame의 ArUco pose만 별도 Fleet sighting token으로 전송한다. 자동 policy/motion 경로는 없다.
- Android 앱은 CameraX → JPEG → WebSocket, 최신 1장 처리와 `rosyov://` pairing을 제공한다. 기존 에뮬레이터 및 단위검증은 실물 천장 phone의 연속 수신 증거가 아니다.
- Revision 778bbd31의 packaged Fleet/Vision/proxy candidate에 합성 phone JPEG를 TLS WSS로 보내고 ArUco projection과 Fleet SQLite readback을 확인했다. Fleet restart 뒤에도 sighting이 유지됐다. 합성 `quality`는 `null`이다.
- 2026-09-30 앱은 연결 실패마다 다음 행동을 한 문장으로 말하고, 배터리·온도 경고와 코너 마커 설치 안내를 보인다. S21 실기에서 화면 잠금 65초 동안 송출이 끊기지 않았다(임시 수신기, `age_ms` 최대 178 ms).
- SOURCE/LOCAL은 Windows host와 CPU fixture 범위에서 GO다. Ubuntu/TLS/FQDN/LAN, 현장 map calibration, 실제 phone 연속 수신 및 GPU inference는 미검증이다. DEVICE/FIELD는 PARKED다.

## 다음 gate

1. 실제 천장 Android phone과 Ubuntu 현장 Fleet host에서 30분 연속 수신을 기록한다(age_ms, frame 간격/sequence gap, disconnect/reconnect, CPU/RAM 포함).
2. `age_ms`에 kernel 송신 대기가 포함되지 않는 점을 고려해 end-to-end 지연을 별도 측정한다. 필요하면 SO_SNDBUF 제한 또는 수신 확인 동작을 평가한다.
3. 현장 camera 위치와 map calibration을 검토하고 지연·가림·marker 누락·stale 입력에서 sighting 생성이 차단되는지 확인한다.
4. Vision이 `status`의 `corners_seen`·`robots_seen`을 실제 검출 값으로 채운다. 지금은 빈 목록이라 앱 설치 안내가 늘 0/4다. 휴대폰 배터리·온도를 현장 PC에 보내려면 프로토콜에 클라이언트 상태 메시지를 먼저 정의해야 한다.
5. RTX 5080 GPU inference가 필요하면 별도 구현/성능 비교를 진행한다. 현재 검증한 Vision image는 CPU ArUco다. 로봇암/Pinky onboard camera는 별도 계약과 장치 수용 gate를 둔다.

## 2026-10-11 측정 교정 후보

D-636의 소형 AprilGrid 렌즈·바닥 측정 워크숍, 유효 픽셀 mask와 bounded AI 검토 형식을 구현했다.
사용 절차는 [compact-camera-calibration.md](docs/compact-camera-calibration.md), 검증 범위는
[result.md](../../docs/validation/compact-camera-calibration-2026-10-11/result.md)에 기록한다.
운영 교정 자동 교체·모델 자동 호출·현장 오차 수용은 포함하지 않는다. 기존 DEVICE/FIELD gate는 유지한다.

## 2026-10-17 · D-775 실측 교정 운영 연결

실측 수치 묶음의 목적별 승인·영속 저장·현재 촬영 session 확인·미리보기·철회 경로를 추가했다.
기존 tracking/sighting 승인과 World/CORE 권한은 유지한다. 원격 시험의 커밋·실행·실패 수정·skipped와
실측 근거의 한계는 [구현 검증 기록](../../docs/validation/measured-camera-lifecycle-2026-10-16/result.md)에 모은다. 기존 모듈 gate의 물리 수용 범위를
넓히지 않는다. D-598의 현재 현장 readback·로봇별 오차 계수는 아직 확보하지 못했다.

## 2026-10-16 스테이션 측정 설치 실행

D-774의 전용 명령과 strict JSON 프로필은 상대/지도 worker를 기존 수신기·source-only HTTP client에 조립한다. [설치 안내](docs/station-vision.md)를 따른다. 0b816554c의 원격 전체 overhead·구조/안전 시험은 781 PASS/0 skip/NEW 0이며 실제 WebSocket demand·JPEG 전송·취소/오류 종료를 포함한다. 일반 preview의 인증/30초 유지 규칙도 회귀했다. 이 기록은 실물 카메라 결속·capture 고정·광학 측정이나 Fleet/CORE 전체 장애 수용을 입증하지 않는다. 기존 DEVICE/FIELD 상태는 유지한다.
