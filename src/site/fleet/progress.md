---
module: fleet
logical_modules: [M07, M11]
owner: FLEET
last_verified: { commit: "bed604ef", date: 2026-09-30 }
gates:
  SOURCE:
    state: GO
    evidence: "패키지 순수성·hub CORE import 경계 계약 시험 통과 (2026-09-17, 6 passed). server/ 추가 후에도 rclpy 금지 유지"
    cmd: "python3 -m pytest src/fleet/test/test_boundaries.py -q"
  LOCAL:
    state: GO
    evidence: "Fleet suite 676 passed/5 skipped including ER2 proposal/admission, durable Mission Action dispatcher with persisted stable grant and restart GetAction reconciliation, independent goal evidence provenance, and SQLite WAL/index contracts. API web 70 passed/13 skipped, OMX adapter 85 passed/3 skipped, foundation 102 passed. Synthetic indexed Mission queries improved by three orders of magnitude locally; this is not target-device evidence. D-348 producer registry, token-scoped evidence ingress, SQLite idempotency, terminal-action verification, and grace-timeout HOLD are implemented and covered by host tests. Dispatcher remains explicit opt-in and automatic policy dispatch remains disabled; no live observation producer, configured OMX service/driver, ROS-SIM, or physical stop/goal proof. SOURCE/LOCAL only. D-392 provider-neutral model tool contract and per-call SQLite journal are covered by 1,126 Fleet tests (6 skipped) on 2026-10-01. Interactions and Live API-shaped conformance fixtures use fake provider envelopes only; they do not prove a production Live adapter, ROS-SIM, ARTIFACT, DEVICE, or FIELD acceptance."
    cmd: "python3 -m pytest src/site/fleet/test -q"
  ROS-SIM:
    state: HOLD
    blocker: "D-87: 현재 트리의 colcon install/setup.bash가 없다. 2026-09-17 WSL Task 14 로그는 설계 입력이며 GO가 아니다 (D-89)"
    cmd: "python3 src/gz_sim/scripts/swarm_bench.py --robots <robots.yaml> --leader rosy_01 --scenario follow|hold"
  ARTIFACT:
    state: PARKED
  DEVICE:
    state: PARKED
  FIELD:
    state: PARKED
adrs: [D-5, D-10, D-12, D-18, D-20, D-21, D-30, D-31, D-59, D-60, D-90, D-93, D-106, D-114, D-116, D-157, D-159, D-269, D-288, D-289, D-290, D-291, D-293, D-300, D-306, D-316, D-318, D-331, D-333, D-334, D-336, D-268, D-392]
plans:
  - docs/plans/2026-09-29-er2-mission-action-contract-closure.md
  - docs/plans/2026-09-29-fleet-mission-control-arbitration-implementation.md
  - docs/plans/2026-09-29-policy-evidence-contract.md
  - docs/plans/2026-09-14-site-middleware-role-fabric-design.md
  - docs/plans/2026-09-14-site-middleware-role-fabric.md
  - docs/plans/2026-09-08-swarm-formation-slice-design.md
  - docs/plans/2026-09-08-swarm-formation-slice.md
  - docs/plans/2026-09-08-swarm-formation-slice-results.md
  - docs/plans/2026-09-15-module-harness-design.md
  - docs/plans/2026-09-21-fleet-signals-integration-design.md
  - docs/plans/2026-09-22-fleet-signals-integration.md
  - docs/plans/2026-09-27-uiux-surface-closure.md
  - docs/plans/2026-09-28-site-camera-preview-rectification.md
  - docs/plans/2026-09-29-er2-semantic-actions-mission-implementation.md
  - docs/plans/2026-10-01-model-tool-contract-implementation.md
---
## 현재 상태 (2026-09-27)

- D-306의 Fleet 목표 지정 개선으로 지도에 키보드 좌표 선택, 대상·좌표 확인, 취소 후 포커스 복귀를 추가했다. 브라우저 회귀 18건과 확인 계약 3건을 LOCAL에서 검증했다. 지도 1920/390/320 상태별 G2 판정과 실물 이동은 아직 별도다.
- Formation geometry(FOR-001), slot assignment(FOR-002), relay(D-31), formation session(FOR-004), 그리고 SiteHub의 HELLO/HEARTBEAT/EVENT 수집과 REST scatter(D-59)는 CORE API 경계를 유지한다. Browser/SiteHub는 DDS/ROS에 직접 연결하지 않는다.
- G-S3 신호등 연동은 상태 수집과 명령 표시를 제공하지만 안전 인터록은 아니다. CORE의 로컬 stop/safety 책임을 대체하지 않는다.
- 별도 `fleet_pairing_token`으로 연결된 CORE Agent의 HELLO/HEARTBEAT/EVENT 경로를 candidate에서 확인했다. 이벤트는 authenticated API로 조회되며 SQLite에서 Fleet restart 이후에도 유지된다.
- Operator web/API와 task queue를 검증했다. navigation 요청은 `REQUESTED → QUEUED`에서 멈췄다. 합성 `nav.completed`는 별도 synthetic event이므로 task의 실제 완료나 로봇 동작으로 해석하지 않는다.
- Overhead WSS → CPU ArUco → Fleet sighting 경로와 SQLite restart 보존을 확인했다. 합성 sighting의 `quality`는 `null`이므로 D-268 policy evidence가 아니다. 자동 이동/집기는 HOLD다.
- 자세한 candidate image/hash와 실행 범위는 `docs/validation/2026-09-26-site-stack-container-smoke.md`에 기록했다. LOCAL 증거는 Windows Docker Desktop `linux/amd64` 및 synthetic fixture 한정이다. Ubuntu/RTX 5080/GPU, 현장 TLS/LAN, 실물 phone/CORE/robot은 아직 미검증이다.

## 다음 gate

1. Ubuntu 24.04 현장 호스트에 immutable candidate를 설치하고 Docker/Compose, 재부팅 복구, loaded image ID, TLS/FQDN/firewall 및 RTX 5080 driver를 확인한다.
2. 실제 CORE와 천장 phone을 연결해 pairing/authentication, reconnect, event/task correlation, timestamp/freshness 및 sighting 품질을 관찰·기록한다.
3. D-268 evidence 형식과 freshness/false-trigger 수치를 합의·측정하기 전까지 자동 policy task 생성을 비활성으로 둔다. 통과 이후에도 운영자 승인과 CORE 안전 조건을 확인하는 별도 제한 시험이 필요하다.
4. 로봇암 집기와 Pinky/로봇 onboard camera는 각각 별도 계약과 장치 gate로 검증한다.

## 현재 유효한 금지사항

- `formation/`과 `swarm/arming.py`는 `httpx`/`websockets`/`rclpy`/`asyncio`를 import하지 않는다(순수성, `test_boundaries.py`가 강제).
- `hub/`는 `core.protocol.schemas` 외 `core`의 무엇도 import하지 않는다(D-18, D-59).
- Hub는 `COMMAND` envelope, `cmd_vel`/`image`/`twist` 페이로드, `PEER` 참조 소스 scatter를 `ROLE_VIOLATION`으로 거절한다(D-59, D-31).
- 관제 UI 가 로봇 `cmd_vel`·DDS 에 붙지 않는다(설계 §6). 내리는 것은 원자 액션뿐이다.
- `map` 프레임을 로봇별로 접두하지 않는다. CORE 가 `map` 고정으로 pose 를 읽고 목표를 받는다(`ros_bridge._map_frame`).
- `core`를 이 패키지에서 수정하지 않는다. 로봇 계약에 없는 것은 API Ref 사이클의 finding이지 로컬 patch가 아니다.
