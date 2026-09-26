---
module: fleet
logical_modules: [M07, M11]
owner: FLEET
last_verified: { commit: "bcc7b138", date: 2026-09-26 }
gates:
  SOURCE:
    state: GO
    evidence: "패키지 순수성·hub CORE import 경계 계약 시험 통과 (2026-09-17, 6 passed). server/ 추가 후에도 rclpy 금지 유지"
    cmd: "python3 -m pytest src/fleet/test/test_boundaries.py -q"
  LOCAL:
    state: GO
    evidence: "2026-09-26 Windows Fleet 510 passed/5 skipped. 기존 FleetAgent 페어링과 전용 host scanner 토큰 분리; Ubuntu Avahi/LAN 실측은 아님"
    cmd: "python3 -m pytest src/fleet/test -q"
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
adrs: [D-5, D-10, D-12, D-18, D-20, D-21, D-30, D-31, D-59, D-60, D-90, D-93, D-106, D-114, D-116, D-157, D-159, D-269]
plans:
  - docs/plans/2026-09-14-site-middleware-role-fabric-design.md
  - docs/plans/2026-09-14-site-middleware-role-fabric.md
  - docs/plans/2026-09-08-swarm-formation-slice-design.md
  - docs/plans/2026-09-08-swarm-formation-slice.md
  - docs/plans/2026-09-08-swarm-formation-slice-results.md
  - docs/plans/2026-09-15-module-harness-design.md
  - docs/plans/2026-09-21-fleet-signals-integration-design.md
  - docs/plans/2026-09-22-fleet-signals-integration.md
  - docs/plans/2026-09-26-site-mdns-discovery.md
---
## 지금 상태

- Formation geometry(FOR-001)·slot assignment(FOR-002)는 순수 함수다. 리더→팔로워 pose 릴레이는 바이트 그대로 팬아웃하고 새 프레임을 합성하지 않는다(D-31). FOR-004 세션(arm→relay→watch→hold)과 SiteHub 계약 gather(hello/heartbeat/event)·REST scatter(e-stop)(D-59)까지 구현·시험됨.
- `test_boundaries.py`가 패키지 전체 `rclpy` 금지와 `hub/`의 `core.protocol.schemas` 외 CORE import 금지를 강제한다(D-18).
- **Fleet 서버 v1 있음**: `fleet console --robots robots.yaml` 이 N대를 한 화면에 모으고 로봇별 목표·취소와 전체 정지를 내린다(site-fabric 설계 §2, 전환 순서 3단계). WSL ROS 2 Jazzy + Gazebo 2대 위에서 지도 클릭 미션 하달 → 양쪽 `ARRIVED` 확인(2026-09-17).
- **신호등 연동 있음(G-S3)**: `fleet console --signals signals.yaml` 이 ROSY-SIGNAL-001 장치를 snapshot 에 모으고(`/api/fleet/signals*`), e-stop 때 전 기기 `all_red` 를 병렬로 흩뿌린다. `mode=failsafe` 를 보면 마지막 의도를 한 번 재단언한다. 신호등은 표시 장치지 안전 인터록이 아니다 — `traffic.py` 판정은 건드리지 않았다.
- CORE Agent outbound `FleetAgent`는 `robots.yaml`의 별도 `fleet_pairing_token`이 설정된 경우 `fleet console` ASGI 앱 `/ws/robots`에 연결한다. loopback hello/heartbeat/event/offline/reconnect는 LOCAL 검증됐으며 기존 snapshot은 여전히 REST 폴링이다.
- 사이트 호스트의 `mdns-bridge.py`가 Avahi `_rosy._tcp`를 Fleet 전용 scan API로 전달할 수 있다. 관제 UI는 미등록·페어링 대기·확인됨·충돌을 읽기 전용으로 보여 준다. `robots.yaml` 토큰이나 명령 대상은 mDNS로 자동 변경하지 않는다. Ubuntu 호스트의 Avahi/타이머 및 다중 Pi 실측은 대기 중이다.
- D-257 Proposed sighting API는 `create_app(..., sightings=...)`로만 활성화되는 programmatic LOCAL 경로다. CLI source/map/calibration provisioning, overhead JPEG→vision→Fleet publisher, durable audit storage, browser display는 아직 없다. D-268 자동 policy input은 별도이며 비활성이다.
- 축구 매치 시작 버튼은 없다 (D-106). `games`를 import하지 않는다. `reset()`은 games.
- 물리 대형(FAT-06 등) 실측은 아직 없다. D-35(전체 HOLD는 릴레이를 끊는 것)는 sim bench 실측 대기 중인 후보이며 ADR log에는 의도적으로 미등재다(`adr_gaps`).
- LOCAL suite evidence는 Windows host 기준이다. Ubuntu 24.04/RTX, 실물 phone/CORE, TLS/LAN, DEVICE/FIELD는 검증하지 않았다.

## 다음 gate

1. 진행 중인 WIP를 커밋하고 LOCAL을 커밋 기준으로 재실행해 `last_verified.commit`을 채운다.
2. `swarm-formation-slice-results.md` Task 14 sim bench(`gz_multi robots:=N mode:=nav core:=true`)를 ROS box에서 실행해 `relay_tx_hz`/`slot_err_m`/HOLD latency를 실측하고 D-35 등록 여부를 결정한다.
3. `FleetAgent` outbound(WS hello/heartbeat/event)를 열어 관제 gather 를 폴링에서 밀어내기(설계 §3).
4. 실물 2대 FAT-06 변형 필드 시험(`capabilities.hardware.yaml`의 `swarm.follow/lead` 점등 포함) 후 FIELD를 승격한다.

## 현재 유효한 금지사항

- `formation/`과 `swarm/arming.py`는 `httpx`/`websockets`/`rclpy`/`asyncio`를 import하지 않는다(순수성, `test_boundaries.py`가 강제).
- `hub/`는 `core.protocol.schemas` 외 `core`의 무엇도 import하지 않는다(D-18, D-59).
- Hub는 `COMMAND` envelope, `cmd_vel`/`image`/`twist` 페이로드, `PEER` 참조 소스 scatter를 `ROLE_VIOLATION`으로 거절한다(D-59, D-31).
- 관제 UI 가 로봇 `cmd_vel`·DDS 에 붙지 않는다(설계 §6). 내리는 것은 원자 액션뿐이다.
- `map` 프레임을 로봇별로 접두하지 않는다. CORE 가 `map` 고정으로 pose 를 읽고 목표를 받는다(`ros_bridge._map_frame`).
- `core`를 이 패키지에서 수정하지 않는다. 로봇 계약에 없는 것은 API Ref 사이클의 finding이지 로컬 patch가 아니다.
