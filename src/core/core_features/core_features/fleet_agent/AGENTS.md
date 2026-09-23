# fleet_agent

## Purpose

Outbound Fleet WebSocket(D-5)의 **로봇 측 구현체**. `FleetAgent.start()`는 설정의
`fleet.hub_url` + `fleet.pairing_token`이 둘 다 있을 때만 소켓을 연다 — 기본
설정(`rosy_default.yaml`)에는 없으므로 잠자고, 중앙 Fleet 서버가 없는 지금은
그 상태가 계약상 옳다. 허브가 생기면 설정만으로 깨어난다(D-170 인접).

## Key Files

| File | Description |
|---|---|
| `__init__.py` | Package marker |
| `agent.py` | hello/welcome 핸드셰이크(PRT-002, 신원은 `RobotIdentity` 실값)·1 Hz heartbeat+스냅샷(PRT-003)·이벤트 seq 버퍼(1000 cap)·`last_event_seq` 이후 재전송·지수 backoff `next_backoff()` 상한 30 s(API Ref §7.6) |

## Subdirectories

None.

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
- 실제 대형(fleet-less)은 `src/site/fleet`이 CORE의 **외부 클라이언트**로
  연다 — 이 아웃바운드 소켓이 아니다.

### Testing Requirements

`src/core/core/test/test_fleet_agent.py`

### Common Patterns

토큰이 없으면 `start()`는 즉시 반환. 값이 들어가는 계산(backoff cap 등)은
순수 헬퍼로 두고 시험이 직접 잰다.

## Dependencies

### Internal

- CORE node가 construct하지만 블록하지 않는다 (`services.py` DI)

### External

- websockets (활성화 시에만 import)

<!-- MANUAL: -->
