---
title: 한 번도 양보하지 않는 가짜 로봇은 확인-후-기록 사이의 동시성 경쟁을 숨긴다
date: 2026-10-30
category: workflow-issues
module: operations/fleet/fleet/server/console (FleetConsole._goal, D-93 교통 중재)
problem_type: test_failure
component: development_workflow
symptoms:
  - "마주 오는 두 미션을 동시에 보내면 둘 다 출발했다(경로 확인과 점유 기록 사이 await 여러 번)"
  - "교통 시험 수백 개가 녹색이었다 - FakeRobot의 async 메서드가 한 번도 await에서 멈추지 않았다"
  - "D-271 Gate A 합성 계측기에서 연속 발행이 이벤트 루프를 41-164 ms 붙잡았다 - 가짜 포트가 양보하지 않았다"
root_cause: race_condition
resolution_type: code_fix
severity: high
related_components:
  - testing_framework
tags: [asyncio, fakes, test-doubles, race, check-then-act, traffic, d-93, d-271, d-928]
last_updated: 2026-10-30
---

# 한 번도 양보하지 않는 가짜 로봇은 확인-후-기록 사이의 동시성 경쟁을 숨긴다

## Problem

`FleetConsole._goal`은 경로를 읽고(`_route_of`), 다른 로봇의 점유(`_claims`)와 겹치는지 보고, 겹치지 않으면 점유를 기록한다. 그 사이에 로봇 HTTP 호출 await가 여러 번 있다. 발행 루프, `/api/fleet/do`, 직접 goal, lane route, 교통 대기 해제, trip이 `console.goal`을 동시에 부를 수 있으므로, 마주 오는 두 미션이 서로의 점유를 보기 전에 둘 다 검사를 통과했다.

시험은 이 경쟁을 한 번도 보지 못했다. `FakeRobot`의 `async def` 메서드는 값만 돌려주고 await에서 멈추지 않는다. `asyncio.gather`로 두 미션을 동시에 시작해도 첫 코루틴이 확인부터 기록까지 끝난 뒤에 두 번째가 시작되므로 결과가 직렬 실행과 같다.

## Root cause

asyncio 코루틴은 실제로 멈추는 await(소켓, `sleep`, 다른 태스크를 기다리는 Future)에서만 다른 코루틴에 차례를 넘긴다. 이미 결과가 있는 코루틴을 await하면 차례를 넘기지 않는다. 진짜 로봇 포트는 HTTP 응답을 기다리며 멈추고, 가짜는 멈추지 않는다. 그래서 확인과 기록 사이의 경쟁은 가짜로 만든 시험에서 원리상 재현되지 않는다.

[가짜 협력 객체가 진짜에 없는 메서드를 가지면](fake-with-a-method-the-real-class-lacks-hid-a-shutdown-bug.md)이 표면(메서드 집합)의 차이라면, 이 교훈은 타이밍(멈추는가)의 차이다. [안전 조정기는 await마다 다시 확인한다](../design-patterns/a-safety-orchestrator-rechecks-after-every-await-and-lets-every-liveness-signal-decay.md)는 코루틴 하나가 await 뒤 바뀐 상태를 다시 보는 문제다. 여기서는 두 호출자가 같은 확인을 동시에 통과한다. 다시 확인해도 상대가 아직 기록하지 않았으면 막지 못한다.

## Fix

- 확인부터 기록까지를 콘솔의 `asyncio.Lock` 하나(`_traffic_lock`)로 감쌌다. 정지 경로(cancel, e-stop)는 잠금을 잡지 않는다.
- 회귀 시험은 `navigation_path`에서 `await asyncio.sleep(0)`으로 한 번 멈추는 `_NetworkRobot(FakeRobot)`을 쓰고, 두 미션을 `gather`로 동시에 보낸다(`operations/fleet/test/test_server_traffic.py::test_concurrent_head_on_missions_let_exactly_one_through`). 잠금 없는 main에서는 둘 다 수락되어 실패했고, 잠금 브랜치에서는 정확히 하나만 나갔다.
- 독립 검토가 잠금을 기다리는 동안 그 로봇이 비켜세우기 대상으로 뽑히는 두 번째 결함을 찾았다. `_goal_busy`인 로봇은 비켜세우지 않도록 고쳤다(`test_server_yield.py::test_a_robot_waiting_for_its_own_traffic_check_is_not_ordered_to_yield`).
- 같은 가짜 성질 때문에 발행 루프를 연속으로 돌리면 이벤트 루프를 붙잡았다. 연속 사이클 사이에 `await asyncio.sleep(0)`을 두었다(`background_workers.py`).

## Verification

- 외부 계측기 `Rosy/docs/research/d271-gate-a-2026-10-30/traffic-race/`를 원격 시험 PC에서 실행했다. main `46b23e565a`는 두 미션이 모두 수락되어 RED, 수정 `1bf26403ce`는 GREEN.
- 원격 교통 시험군 333 passed, 새 실패 0.
- 실물 다중 로봇이나 Gazebo 수용은 아니다. 동시 발행 설계는 D-928(Proposed)에서 다룬다.

## When to apply

- `async` 코드가 "확인 → await → 기록" 형태이고 호출자가 둘 이상일 수 있으면, 가짜가 그 await에서 실제로 멈추게 만든 동시 시험을 하나 둔다(`await asyncio.sleep(0)` 한 줄로 충분하다).
- 가짜로만 측정한 이벤트 루프 지연이나 처리량은 진짜 포트의 양보를 반영하지 않는다. 루프를 연속으로 돌리는 변경은 양보 지점을 명시적으로 둔다.
- 잠금을 더한 뒤에는 잠금을 기다리는 동안 그 주체를 다른 경로가 대상으로 삼지 않는지(비켜세우기, 정리 루프) 확인한다.
