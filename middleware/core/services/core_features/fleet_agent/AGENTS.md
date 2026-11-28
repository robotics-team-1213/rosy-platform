
# fleet_agent

**Parent context:** `../AGENTS.md`

## Purpose

Outbound Fleet WebSocket(D-5)의 **로봇 측 구현체**. `FleetAgent.start()`는 설정의
승인된 `fleet.pairing_token`과 명시적 `fleet.hub_url` 또는
`fleet.discovery.{expected_hostname,ca_file}`가 있을 때만 소켓을 연다.
기본 설정(`rosy_default.yaml`)에는 토큰이 없으므로 새 장치는 등록 대기한다.
SD의 일회성 `pairing_credential`을 지속 연결 토큰으로 사용하지 않는다.

## For AI Agents

### Working In This Directory

- 이 저장소에는 중앙 Fleet 서버가 없다. 허브 주소·토큰을 기본 설정에 넣지
  않는다 — 잠자는 것이 의도된 상태다(D-5). 서버 착수 시 PRT-004 확장
  (correlation_id·AckPayload)도 같은 변경에 담는다(D-170).
- hello 신원(`device_uid`/`device_name`/`model`/`hardware_serial`)은
  `RobotIdentity` 실값에서 온다. 모르면 빈 문자열이지 지어낸 값이 아니다 —
  허브의 `DUPLICATE_IDENTITY`/`IDENTITY_DRIFT` 방어가 이 값으로 산다.
- Teleop·navigation·safety는 이 에이전트를 import하거나 기다리지 않는다.
- Commissioning은 `fleet_hold: true`, 로봇 오버레이 `swarm.follow`/`swarm.lead`는 false 유지.
- 실제 대형(fleet-less)은 `operations/fleet`이 CORE의 **외부 클라이언트**로
  연다 — 이 아웃바운드 소켓이 아니다.

### Testing Requirements

`middleware/core/gateway/test/test_fleet_agent.py`, `test_fleet_agent_mdns.py`

### Common Patterns

토큰이 없으면 `start()`는 즉시 반환. 값이 들어가는 계산(backoff cap 등)은
순수 헬퍼로 두고 시험이 직접 잰다.

## Dependencies

### Internal

- CORE node가 construct하지만 블록하지 않는다 (`services.py` DI)

### External

- websockets (활성화 시에만 import)
