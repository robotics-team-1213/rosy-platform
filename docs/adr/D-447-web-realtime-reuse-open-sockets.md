## D-447 웹 표면의 실시간 상태는 이미 열린 소켓을 재사용한다

**Status:** Proposed (2026-10-04, 사용자 지시 "ADR 작성해서 하나 처리해보자". 사다리 계획 §4 배정표의 "웹 표면 실시간 구독 통일" 항목이 이 ADR이다. 계획은 "P4-2 착수 시 배정"이라 적었으나 이번 착수로 D-447을 배정한다. 이 ADR은 전환 계약과 순서를 정하는 문서 결정이다. (a)단계 구현을 동반하나 DEVICE/FIELD 승격과는 무관하다.)

## 배경

- Fleet v1 gather는 REST 폴링이다(D-81). `console.snapshot()`이 주기마다 모든 로봇에 `GET /api/v1/robot/state`를 날린다. 그러나 로봇 `FleetAgent`(CORE `core_features/fleet_agent`, 기본 비활성)는 이미 hub `/ws/robots`에 1 Hz(PRT-003) heartbeat로 `StateSnapshot`을 밀어 붙고, hub `RobotRegistry`가 로봇마다 저장한다(`registry.py` `RobotRecord.snapshot`). `server/AGENTS.md`가 예약한 봉합점 그대로: "붙으면 `snapshot()`의 출처만 바꾼다".
- 로봇 로컬 셸도 같은 모양이다 — `shell/store.js`는 폴링만 읽고, 같은 origin의 `/ws/state`(10 Hz, D-362 P1)가 이미 돈다.
- 두 전환 모두 새 계약이 필요 없다. 필요한 것은 출처 우선순위와 신선도 규칙이다.

## 결정

1. **원칙 — 재사용, 불변, 우선순위.** 실시간 상태는 이미 열린 소켓(hub `/ws/robots`, CORE `/ws/state`)에서 온다. 새 전송 계약·엔드포인트를 만들지 않는다. 응답 스키마는 불변이다(콘솔 UI·브라우저 코드 변경 없음). 소켓이 연결되고 신선하면 그것이 출처가 되고, 아니면 지금의 폴링이 폴백이다.
2. **순서는 D-445 §3 그대로다.** (a) Fleet gather 출처 전환이 먼저: hub에 online이고 신선한 로봇은 `console.snapshot()`이 registry의 `StateSnapshot`을 쓰고 REST GET을 건너뛴다. (b) 그 뒤 로봇 셸 `store.js`가 같은 원칙으로 `/ws/state` 구독으로 옮겨간다(같은 ADR, 별도 구현 회차, D-362 파일 예산 준수).
3. **신선도 규칙.** hub 스냅샷은 마지막 heartbeat 도착이 `hub_state_max_age_s`(기본 3.0 s — 1 Hz 3박동 여유, SAF-003 `fleet_loss_timeout_s` 5.0 s보다 작게) 안일 때만 출처로 쓴다. 넘으면 그 로봇은 그 주기에 REST GET으로 돌아가고, REST마저 실패하면 지금과 같은 offline 행이 된다. heartbeat 도착 시각은 hub가 기록한다(registry `RobotRecord`). 로봇이 만든 증거·나이 필드(D-309)는 스냅샷 안에 이미 있고 그대로 흘린다 — Fleet이 다시 계산하지 않는다.
4. **감사·관측.** 행마다 출처를 선택 필드 `gather_source: "hub" | "rest"`로 남긴다(additive, PRT-006 관행). `SharedGather`의 1 s 스냅샷 재사용(D-438), 맵·사건·명령·대형 경로는 그대로다.
5. **범위 밖.** 브라우저→Fleet `/api/fleet/state` 폴링을 바꾸지 않는다(그것은 hub가 브라우저를 섬기는 별도 결정이다). 로봇→hub heartbeat 주기·본문, hub 인증, scatter 경로도 바꾸지 않는다.

## 결과

- 로봇당 주기별 REST GET 1건이 hub 연결 로봇에서 사라진다. N대 규모(D-131)에서 gather 비용이 소켓 유지비로 바뀐다.
- hub가 죽으면 콘솔은 자동으로 오늘의 REST 폴백으로 돌아간다 — 전환이 새로운 단일 실패점을 만들지 않는다.
- `gather_source`로 두 출처가 실제로 섞여 도는지 운영에서 읽을 수 있다.

## 검증

- 호스트: fleet 시험 — hub-fresh 로봇은 REST `state()`가 불리지 않음, stale 로봇은 REST 폴백, hub 미연결·REST 실패 행 불변, `gather_source` 표기, registry heartbeat 도착 시각 기록. hub 경계 시험(`test_boundaries.py`)·기존 콘솔 시험 회귀 없음.
- (b) 회차: 셸 headless 시험(`web_common`), Playwright 보존 G2.
- 이 전환은 ROS-SIM/DEVICE/FIELD 승격이 아니다.

## 잇는 결정

D-1(단일 프로세스), D-59(사이트 패브릭), D-81(v1 gather와 다음 단계), D-131(콘솔 재현율), D-309(서버 소유 증거·나이), D-362(웹 자산 예산·state socket), D-382(페어링 세션), D-419(SAF-003 링크 상실), D-438(SharedGather), D-444·D-445(사다리), 계획 `2026-10-04-web-gate-ladder-fleet-readiness-adr-plan.md` §4.
