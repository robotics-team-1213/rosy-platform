---
module: overhead
logical_modules: []
owner: SITE
last_verified: { commit: "uncommitted", date: 2026-09-26 }
gates:
  SOURCE:
    state: GO
    evidence: "protocol/ingest/cli modules, ROS-free, no cv2/rclpy (2026-09-26 Windows)"
    cmd: "python -m pytest src/site/overhead/test -q"
  LOCAL:
    state: GO
    evidence: "protocol vectors + ingest server over a real localhost websocket + cli argparse, 41 passed (2026-09-26 Windows)"
    cmd: "python -m pytest src/site/overhead/test -q"
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
- 안드로이드 앱(`android/`)은 이 트랙 범위 밖 — 다른 에이전트가 병렬 브랜치에서 만든다. 마커 인식·Fleet 연동 없음(D-257 3항은 열림).
- DEVICE/FIELD는 실물 폰 + 현장 LAN 실측 전까지 PARKED.

## 다음 gate

1. 안드로이드 A1 골격(같은 vectors.json)과 합류한 뒤 A2 골격(에뮬레이터 카메라 → 이 어댑터) LOCAL 증거
2. A3: 실물 폰 30분 연속 기록 (age_ms, 드롭률, 대역, 열 상태) → DEVICE
