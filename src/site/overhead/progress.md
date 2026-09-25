---
module: overhead
logical_modules: []
owner: SITE
last_verified: { commit: "c6647a1e", date: 2026-09-26 }
gates:
  SOURCE:
    state: GO
    evidence: "protocol/ingest/cli modules, ROS-free, no cv2/rclpy (2026-09-26 Windows)"
    cmd: "python -m pytest src/site/overhead/test -q"
  LOCAL:
    state: GO
    evidence: "python 45 passed (vectors, real localhost websocket incl. half-open replacement, cli); android 72 JVM unit tests + assembleDebug; emulator API 35 e2e: 3 fps, 0 gaps, reconnect after receiver restart, pairing dialog survives rotation (2026-09-26 Windows)"
    cmd: "python -m pytest src/site/overhead/test -q && (cd src/site/overhead/android && gradlew testDebugUnitTest assembleDebug)"
  ROS-SIM:
    state: N/A
  ARTIFACT:
    state: N/A
  DEVICE:
    state: PARKED
  FIELD:
    state: PARKED
adrs: [D-257, D-261]
plans:
  - docs/plans/2026-09-26-overhead-camera-android-app-design.md
---
## 지금 상태

- D-261 A1+A2 receive-only adapter. `overhead.protocol`(헤더/hello/config/pairing URI), `overhead.ingest`(WebSocket 수신, latest-only, per-source stats), `overhead.cli`(`rosy_overhead receive`).
- 안드로이드 앱(`android/`, D-261): CameraX → JPEG → WebSocket, 최신 1장, 포그라운드 camera 서비스, `rosyov://` 딥링크(확인 대화상자). 에뮬레이터에서 이 어댑터까지 실제 프레임 수신 확인.
- 마커 인식·Fleet 연동 없음(D-257 3항은 열림). `status`의 `corners_seen`/`robots_seen`은 인식이 붙기 전까지 빈 목록이 실제 값이다.
- DEVICE/FIELD는 실물 폰 + 현장 LAN 실측 전까지 PARKED.

## 다음 gate

1. A3: 실물 폰 30분 연속 기록 (age_ms, 드롭률, 대역, 열 상태) → DEVICE
2. A3 전에 결정: 커널 송신 버퍼 때문에 `age_ms`가 전송 대기를 빼고 잰다(앱 쪽 최신 1장은 보장). 실측 지연이 크면 SO_SNDBUF 상한 또는 수신 확인으로 막는다.
3. A4: 노출 고정, `status` 거치 도움 표시. 그 뒤 마커 인식(D-257 3항).
