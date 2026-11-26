---
surface: fleet
kind: additive
slug: trip-execution-readout
date: 2026-11-26
title: Fleet 운행 명령과 기체 이동 관측
---

`GET /api/fleet/trips`와 `GET /api/fleet/trips/{trip_id}`의 운행, 출발 응답, `GET /api/fleet/work`의 운행 행에 `execution`을 제공한다 (v1.next). 원장의 `state`는 요청 수명주기를 유지한다.

`execution.phase`는 접수(`received`), 전송 전 교통 대기(`pre_dispatch_wait`), 기타 확인 대기(`goal_wait`), 명령 전달 후 이동 확인 대기(`dispatched`), 명령 수락 후 관측된 이동·정지(`moving`·`stationary`), 일시정지(`paused`), 종료(`terminal`) 중 하나다. `command_robot_id`는 명령 대상이고 `waiting_on`은 안전거리 확인 대상이다. `reason`은 대기 또는 종료 사유를 담는다.

`execution.motion`은 현재 기체의 오도메트리 관측으로 `moving`, `stationary`, `unknown`을 구분한다. `sampled_at`은 관측에 사용한 CORE 속도 표본의 원본 시각이다. 이동 판정에는 해당 기체 연결의 최신 REST 스냅숏과 표본 시각이 필요하다. 접수·정지 요청과 기체의 실제 운동은 같은 순간에 서로 다른 상태일 수 있다.
