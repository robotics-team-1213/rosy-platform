<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-17 | Updated: 2026-09-17 -->
# server

## Purpose

관제 PC의 Fleet 서버 v1 — 사이트 오케스트레이터와 관제 UI 역할(site-fabric 설계 §2, 전환
순서 3단계). 등록된 N대의 상태를 모으고, 로봇별 목표·취소와 전체 정지를 내린다. 미션은
Fleet 쪽에 남는다(D-12): 하달한 목표를 기억하는 곳은 여기지 로봇이 아니다.

## Key Files

| File | Description |
|---|---|
| `console.py` | `FleetConsole` — gather(snapshot/map)와 scatter(goal/cancel/estop), 그리고 경로 충돌 시 미션 대기열 |
| `signals.py` | 신호등(ROSY-SIGNAL-001) gather/scatter — signals.yaml, `SignalConsole`(재단언·all_red·3자 교차 검증 verify), `HttpSignalClient`, `HttpSignalObserver`. `swarm/` 로봇 계약과 섞지 않는다 |
| `traffic.py` | 경로 충돌 판정(순수 기하). 전송도 asyncio 도 없다 |
| (대형) | `swarm/session.py` 의 `FormationSession` 을 콘솔이 하나만 들고 연다 |
| `app.py` | FastAPI 표면. `/api/fleet/*` 와 `/console` 정적 자산 allowlist |
| `web/` | 관제 UI (index.html, tokens.css, styles.css, console.js) |

## For AI Agents

- **v1 의 gather 는 폴링이다.** 설계 §3 의 최종 경로는 로봇 `FleetAgent` 의 outbound WS 지만
  그 에이전트는 이 서버가 생긴 뒤에야 소켓을 연다. 붙으면 `snapshot()` 의 출처만 바꾼다.
- 로봇 pose 는 CORE 가 TF `map → <ns>base_footprint` 로 읽어 준 map 프레임 값이다
  (`ros_bridge._map_frame = "map"`). `map` 은 사이트 공유 프레임이라 N대를 한 격자에 겹쳐
  그릴 수 있다 — 로봇별로 `rosy_XX/map` 을 만들면 이 화면도 CORE 의 목표 전달도 깨진다.
- e-stop 은 부분 실패해도 200 이다. 5xx 로 접으면 어느 대가 섰는지 화면이 알 수 없다.
- UI 는 CSP `style-src 'self'` 아래에서 돈다 — `style` 속성과 `el.style.x =` 는 적용되지
  않는다. 색과 배치는 클래스로만 준다.
- 이 서버는 robots.yaml 의 운영자 토큰을 들고 있다. 기본 바인드는 루프백이고, 밖으로 열려면
  `--token` 이 필수다(`cli.run_console` 가 강제).
- **교행은 Fleet 만 볼 수 있다.** 로봇의 코스트맵은 자기 주변만 본다 — 상대가 멀리 있으면
  둘 다 같은 통로로 들어가는 계획을 세우고, 서로를 본 순간엔 이미 마주 보고 갇혀 있다.
  두 경로를 동시에 쥔 쪽이 Fleet 이라 여기서 순서를 정한다(D-12). 양보는 늘 **나중에
  내려온 미션** 쪽이다 — 달리던 로봇을 세우면 통로 한가운데 장애물이 하나 생길 뿐이다.
- 경로는 목표를 받은 **뒤에** 생긴다. 그래서 `goal()` 은 일단 내려보내고, 경로를 읽어
  충돌이면 취소해 대기열에 넣는다. 되돌리는 값은 로봇이 아직 거의 안 움직였을 때 취소 한 번이다.
- 경로를 못 읽으면 막지 않는다. 모른다는 이유로 미션을 세우면 계획이 늦은 로봇 한 대가
  현장을 통째로 세운다.
- **대형에서 리더는 목표를 받고 팔로워는 받지 않는다.** 대형은 리더를 몰아서 움직이는
  것이고(D-20), 리더를 막으면 무장만 된 채 아무 데도 못 간다. 반대로 팔로워에 목표를
  따로 내리면 로봇 안에서 추종과 항법이 같은 바퀴를 두고 다툰다.
- 대형은 사이트에 하나다. 이미 열려 있으면 거절한다 — 조용히 갈아치우면 앞 세션의
  팔로워가 무장된 채 남아 아무도 보내지 않는 참조를 기다린다.
- e-stop 은 로봇을 세우기 **전에** 대형을 푼다. 릴레이가 참조를 계속 밀어 넣는 채로 세우면
  e-stop 을 푸는 순간 팔로워가 밀린 참조를 향해 달려나간다.
- 해제는 거절하지 않는다. 대형을 못 푸는 화면은 대형을 여는 화면보다 나쁘다.
- 로봇 로컬 대시보드를 대체하지 않는다. 한 대의 현장 화면·수동 조작·비상정지는 CORE
  `/dashboard` 에 그대로 있다(D-23).

## Testing Requirements

`src/site/fleet/test/test_server_console.py`, `test_server_app.py`, `test_server_traffic.py`, `test_server_formation.py` — 가짜 로봇만 쓰고
네트워크는 없다. `test_server_app.py` 는 `fastapi.testclient` 를 쓰므로 fastapi 가 필요하다.
