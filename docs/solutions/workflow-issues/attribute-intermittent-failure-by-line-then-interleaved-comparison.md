---
title: 간헐 실패를 변경 탓으로 돌리기 전에 실패 줄을 먼저 보고, 기준선과 브랜치를 같은 부하에서 번갈아 비교한다
date: 2026-10-01
category: workflow-issues
module: src/site/fleet/test (test_console_hub_integration.py, D-382 Hub binding fix)
problem_type: workflow_issue
component: development_workflow
severity: medium
applies_when:
  - 브랜치의 간헐 시험 실패가 변경 때문인지 원래 있던 flake인지 가려야 할 때
  - main과 브랜치의 실패율을 여러 번 돌려 비교할 때
  - 다른 세션이나 백그라운드 스위트가 같은 머신을 쓰고 있을 때
  - 시험이 고정 벽시계 대기로 서버 기동을 기다릴 때
symptoms:
  - test_core_agent_hello_heartbeat_and_event_reach_console_app가 간헐적으로 실패했다
  - 순차 10회 비교에서 브랜치 2/10 실패, main 0/10이라 변경이 원인처럼 보였다
  - 실패는 모두 서버 기동 대기(server.started)가 4 s를 넘긴 것이었다
root_cause: async_timing
resolution_type: workflow_improvement
related_components:
  - testing_framework
tags: [flaky-test, load-dependent, interleaved-comparison, wall-clock-timeout, verification-discipline, fleet, d-382]
---

# 간헐 실패를 변경 탓으로 돌리기 전에 실패 줄을 먼저 보고, 기준선과 브랜치를 같은 부하에서 번갈아 비교한다

## Context

D-382 Hub 결속 변경(브랜치 `fix/d382-fleet-hub-binding-agent-events`, c86f5c10을 거쳐 main에 반영) 뒤 `src/site/fleet/test/test_console_hub_integration.py`의 `test_core_agent_hello_heartbeat_and_event_reach_console_app`가 간헐적으로 실패했다. 이 시험은 한 asyncio 루프 안에서 실제 uvicorn 서버와 실제 `FleetAgent`를 띄우고, 벽시계 예산을 주는 `_until(predicate, timeout_s=4.0)`로 기다린다. 서버 기동·hello·이벤트·오프라인 전환은 4 s, 재접속만 6 s다.

- **첫 비교는 회귀처럼 보였다.** 같은 5개 파일 묶음을 10라운드 동안 main worktree에서 먼저, 이어서 브랜치 worktree에서 순서대로 돌렸다. 브랜치 2/10 실패, main 0/10이었다(묶음 단위 실패 수라 어느 시험인지는 이 단계에서 몰랐다). 그런데 이 비교는 공정하지 않았다. 머신을 다른 세션과 나눠 썼고, 브랜치 쪽 전체 Fleet 스위트가 일부 구간에 백그라운드로 돌았다. 브랜치 실행 한 번이 11분 넘게 걸린 것이 부하 급등의 흔적이다. 부하는 브랜치 쪽에만, 서로 다른 시각에 걸렸다.
- **실패 줄을 잡자 가설이 무너졌다.** 3개를 동시에 돌리는 부하에서 이 시험만 반복하자 9번 중 4번 실패했고, 4건 모두 `await _until(lambda: server.started)`였다. (같은 부하의 main은 9/9 통과했지만, 브랜치 쪽만 백그라운드 스위트와 겹쳐 이 비교도 공정하지 않았다.) 이 시점은 `agent.start()`보다 앞이라 FleetAgent도 Hub 코드도 아직 실행되지 않았다.
- **같은 부하에서 번갈아 비교하자 결론이 났다.** 4라운드 동안 매 라운드 main 2개와 브랜치 2개를 동시에 띄웠다. main 1/8, 브랜치 0/8이었고, main의 실패도 같은 `server.started` 대기였다. 원래 있던, 부하에 따라 나타나는 flake였고 변경은 그대로 머지했다.

## Guidance

1. **실패한 줄부터 읽는다.** 어느 await나 assert에서 죽었는지 보고, 변경한 코드가 그 시점에 실행될 수 있었는지 묻는다. 이번에는 서버 기동 대기에서 죽었으므로 변경한 Hub 코드는 한 줄도 돌지 않았다.
2. **기준선과 브랜치는 같은 부하에서 번갈아 또는 동시에 돌린다.** 여러 번 돌리고, 다른 시각의 순차 묶음끼리 비교하지 않는다. 공유 머신의 부하는 시간에 따라 바뀐다.
3. **한쪽에만 걸리는 백그라운드 작업이 도는 동안에는 비교하지 않는다.** 예: 브랜치 자신의 전체 스위트. 부하 차이가 코드 차이로 읽힌다.
4. **실패율과 실패 줄을 journal에 남긴다.** 예: "main 1/8, 브랜치 0/8, 실패는 모두 `server.started` 대기". 다음 사람이 다시 조사하지 않는다.
5. **시험 자체 개선은 따로 판단한다(이번에는 하지 않음).** 기동 대기 예산을 늘리거나, 벽시계 예산 대신 준비 신호(서버가 started일 때 set되는 event)를 기다리게 할 수 있다.

## Why This Matters

순차 묶음 비교는 "부하가 걸린 시간대"와 "코드 판"을 섞는다. 이번에는 2/10 대 0/10이라는 숫자가 그럴듯한 회귀로 읽혔다. 그대로 믿었다면 멀쩡한 보안 수정을 되돌리거나, 없는 버그를 Hub 코드에서 찾았을 것이다. 실패 줄 확인과 교차 비교는 각각 몇 분이면 끝난다. 잘못된 결론은 뒤따르는 조사 방향 전체를 틀어 놓는다.

이 머신은 여러 에이전트 세션, WSL, pytest 스위트가 CPU를 함께 쓴다. 병렬 부하가 타이밍을 바꾼다는 점은 [카드 readback이 병렬 CPU 부하에서 느려진 사례](card-readback-slows-under-parallel-cpu-load-2026-09-25.md)와 같다. 그 문서는 무거운 작업을 CPU에 민감한 단계와 겹치지 않게 일정을 잡으라고 하고, 이 문서는 부하가 타이밍을 바꾼다는 전제에서 측정을 공정하게 설계하라고 한다. 둘은 서로를 보완한다.

## When to Apply

- 변경 직후 통합 시험(실제 서버, 소켓, 스레드, asyncio 대기)이 간헐적으로 실패하고, 원인이 변경인지 불분명할 때.
- 기준선과 브랜치의 실패율로 회귀 여부를 판단하려 할 때.
- 고정 `timeout_s` 같은 벽시계 대기에 기대는 시험을 여러 세션이 쓰는 머신에서 돌릴 때.

## Examples

실패 줄 확인. 4건 모두 traceback이 같은 곳을 가리켰다.

```
src\site\fleet\test\test_console_hub_integration.py:89: in scenario
    await _until(lambda: server.started)
AssertionError: condition did not become true before timeout
```

이 줄은 `agent.start()`보다 앞이므로 FleetAgent와 Hub 코드가 실행되기 전의 실패다.

교차 비교 루프. 기준선은 `main`을 가리키는 detached worktree로 만들고, 라운드마다 양쪽을 동시에 띄운다. 출력은 X:에 둔다.

```bash
cd "F:/Dev/Control/Robot/ROS/Rosy/Rosy OS"
git worktree add --relative-paths --detach .worktrees/cmp-base main

OUT="X:/DevTemp/cmp"; mkdir -p "$OUT"
T="src/site/fleet/test/test_console_hub_integration.py::test_core_agent_hello_heartbeat_and_event_reach_console_app"

for round in 1 2 3 4; do
  for i in 1 2; do
    ( cd .worktrees/cmp-base && python -m pytest "$T" -q > "$OUT/base-$round-$i.txt" 2>&1 ) &
    ( cd .worktrees/<branch-worktree> && python -m pytest "$T" -q > "$OUT/branch-$round-$i.txt" 2>&1 ) &
  done
  wait   # 한 라운드 안에서 기준선 2개와 브랜치 2개가 같은 부하를 나눠 쓴다
done

grep -l " failed" "$OUT"/base-*.txt   | wc -l
grep -l " failed" "$OUT"/branch-*.txt | wc -l
grep -h -A1 "in scenario" "$OUT"/*.txt | grep await | sort | uniq -c   # 어느 대기에서 죽었는지
```

비교가 끝나면 `git worktree remove .worktrees/cmp-base`로 정리한다. 이 루프를 돌리는 동안 어느 한쪽 전용 백그라운드 스위트를 돌리지 않는다.

## Related

- [An empty writer exit code in the reprovision test is a known flake, not your change](reprovision-write-flakes-with-an-empty-exit-code-2026-09-26.md) — 간헐 실패를 자기 변경 탓으로 본 이웃 사례. 원인은 다르다(빈 종료 코드).
- [The card readback took 18 minutes instead of 7 because parallel agent work competed for the CPU](card-readback-slows-under-parallel-cpu-load-2026-09-25.md) — 같은 종류의 원인(공유 머신의 병렬 부하).
- [An inability to check is not a clean result](inability-to-check-recorded-as-clean-result.md) — 반대 방향의 실수: 흔들리는 탐침을 판정으로 쓴 경우.
