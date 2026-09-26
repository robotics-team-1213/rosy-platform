---
module: overhead
logical_modules: []
owner: SITE
last_verified: { commit: "778bbd31", date: 2026-09-27 }
gates:
  SOURCE:
    state: GO
    evidence: "protocol/ingest + isolated CPU ArUco detector/projector/publisher/latest-only worker; ROS-free and no cmd_vel (2026-09-26 Windows)"
    cmd: "python -m pytest src/site/overhead/test -q"
  LOCAL:
    state: GO
    evidence: "70 passed (Windows). Revision 778bbd31 packaged linux/amd64 Compose smoke: TLS WSS synthetic JPEG -> CPU ArUco projection -> authenticated Fleet HTTPS/SQLite readback; sighting persisted across Fleet container restart. Synthetic quality is null; this is not a physical phone, Ubuntu/GPU, freshness, calibration, DEVICE or FIELD result (2026-09-27 Windows Docker Desktop)"
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
## 현재 상태 (2026-09-27)

- D-261 ingest와 D-257 display-only CPU vision path는 source별 최신 JPEG를 보관하고, fresh frame의 ArUco pose만 별도 Fleet sighting token으로 전송한다. 자동 policy/motion 경로는 없다.
- Android 앱은 CameraX → JPEG → WebSocket, 최신 1장 처리와 `rosyov://` pairing을 제공한다. 기존 에뮬레이터 및 단위검증은 실물 천장 phone의 연속 수신 증거가 아니다.
- Revision 778bbd31의 packaged Fleet/Vision/proxy candidate에 합성 phone JPEG를 TLS WSS로 보내고 ArUco projection과 Fleet SQLite readback을 확인했다. Fleet restart 뒤에도 sighting이 유지됐다. 합성 `quality`는 `null`이다.
- SOURCE/LOCAL은 Windows host와 CPU fixture 범위에서 GO다. Ubuntu/TLS/FQDN/LAN, 현장 map calibration, 실제 phone 연속 수신 및 GPU inference는 미검증이다. DEVICE/FIELD는 PARKED다.

## 다음 gate

1. 실제 천장 Android phone과 Ubuntu 현장 Fleet host에서 30분 연속 수신을 기록한다(age_ms, frame 간격/sequence gap, disconnect/reconnect, CPU/RAM 포함).
2. `age_ms`에 kernel 송신 대기가 포함되지 않는 점을 고려해 end-to-end 지연을 별도 측정한다. 필요하면 SO_SNDBUF 제한 또는 수신 확인 동작을 평가한다.
3. 현장 camera 위치와 map calibration을 검토하고 지연·가림·marker 누락·stale 입력에서 sighting 생성이 차단되는지 확인한다.
4. RTX 5080 GPU inference가 필요하면 별도 구현/성능 비교를 진행한다. 현재 검증한 Vision image는 CPU ArUco다. 로봇암/Pinky onboard camera는 별도 계약과 장치 수용 gate를 둔다.
