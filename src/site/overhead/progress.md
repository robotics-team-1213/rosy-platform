---
module: overhead
logical_modules: []
owner: SITE
last_verified: { commit: "uncommitted", date: 2026-09-26 }
gates:
  SOURCE:
    state: GO
    evidence: "protocol/ingest + isolated CPU ArUco detector/projector/publisher/latest-only worker; ROS-free and no cmd_vel (2026-09-26 Windows)"
    cmd: "python -m pytest src/site/overhead/test -q"
  LOCAL:
    state: GO
    evidence: "python 69 passed; Android Gradle testDebugUnitTest succeeded; Ubuntu 24.04 Fleet/vision/proxy Docker images built and all Compose services healthy; TLS WSS synthetic JPEG → ArUco projection → HTTPS Fleet SQLite readback passed (2026-09-26 Windows Docker Desktop Linux containers)"
    cmd: "python -m pytest src/site/overhead/test -q && (cd src/site/overhead/android && gradlew testDebugUnitTest --rerun-tasks --no-daemon) && docker compose -f deploy/site/compose.yaml build && docker compose -f deploy/site/compose.yaml up -d"
  ROS-SIM:
    state: N/A
  ARTIFACT:
    state: N/A
  DEVICE:
    state: PARKED
  FIELD:
    state: PARKED
adrs: [D-257, D-261, D-269]
plans:
  - docs/plans/2026-09-26-overhead-camera-android-app-design.md
  - docs/plans/2026-09-26-middleware-device-server-contract-integration.md
---
## 지금 상태

- D-261 ingest와 D-257 display-only CPU vision path. `protocol`/`ingest`는 source별 최신 JPEG를 보관하고 `detect`/`project`/`worker`가 fresh frame의 ArUco pose만 별도 Fleet sighting token으로 전송한다. automatic policy/motion path는 없다.
- 안드로이드 앱(`android/`, D-261): CameraX → JPEG → WebSocket, 최신 1장, 포그라운드 camera 서비스, `rosyov://` 딥링크(확인 대화상자). 에뮬레이터에서 이 어댑터까지 실제 프레임 수신 확인.
- Docker Compose로 Fleet, vision, Caddy를 띄우고 TLS로 보호된 WSS 프레임 수신→ArUco pose→Fleet API→SQLite 저장을 합성 JPEG로 검증했다. 이 증거는 현장 Ubuntu나 실제 천장 카메라 map calibration·연속 오차·token 운영 수용을 뜻하지 않는다.
- DEVICE/FIELD는 실물 폰 + 현장 LAN 실측 전까지 PARKED.

## 다음 gate

1. A3: 실물 폰 30분 연속 기록 (age_ms, 드롭률, 대역, 열 상태) → DEVICE
2. A3 전에 결정: 커널 송신 버퍼 때문에 `age_ms`가 전송 대기를 빼고 잰다(앱 쪽 최신 1장은 보장). 실측 지연이 크면 SO_SNDBUF 상한 또는 수신 확인으로 막는다.
3. A4: 노출 고정, `status` 거치 도움 표시. 그 뒤 마커 인식(D-257 3항).
