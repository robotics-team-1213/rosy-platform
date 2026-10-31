# Fleet 로봇별 동시 작업 발행 실행 계획 (D-928)

**상태:** 초안. D-928이 Accepted가 된 뒤에만 구현한다. 다중 로봇 Gazebo 수용(D-928 Validation 3)과 함께 진행한다.

**목표:** 응답이 느린 로봇 하나가 다른 로봇의 작업 발행을 늦추지 않게 한다. 교통 판정의 안전 성질(`FleetConsole._goal`·D-93: 겹치는 경로는 하나만 나간다)과 claim 우선순위(D-271 6항)는 지금과 같다.

**전제(이미 착지):** 발행 루프 드레인(`background_workers.py`), 교통 판정 잠금 `_traffic_lock`과 발행 중 로봇의 비켜세우기 제외(`console.py`), 발행 로그의 `claim_s`·`send_s`.

## 바뀌는 파일

| 파일 | 변경 |
|------|------|
| `operations/fleet/fleet/server/background_workers.py` | 로봇별 발행 태스크 시작·추적·종료 시 취소와 대기 |
| `operations/fleet/fleet/server/ledger/task_service.py` | 사이클당 로봇마다 하나 claim, 발행 태스크 본체 분리, `CancelledError` 정리 |
| `operations/fleet/fleet/server/console/console.py` | 임시 점유 기록 순서·판정 규칙, `_run_traffic` 예외와 잠금 비대기 정리, 명단 제거 시 상태 정리 |
| `operations/fleet/fleet/server/console/goal_admission.py` | 임시 점유 순서·전환 규칙 helper - `console.py`는 size ratchet 상한이라 새 코드는 여기에 |
| `operations/fleet/test/test_server_traffic.py`, `test_server_yield.py`, `test_loop_supervision.py`, `test_queue_wait_metrics.py` | 아래 시험 |

`console.py`는 1294줄로 D-766 상한이다. 늘어나는 코드는 `goal_admission.py`로 옮기거나 같은 커밋에서 다른 부분을 줄인다. `size_ratchet.txt`는 고치지 않는다.

시험의 가짜 로봇은 `await asyncio.sleep(0)`이나 `asyncio.Event`로 실제로 멈춰야 한다([교훈](../solutions/workflow-issues/fakes-that-never-suspend-hide-check-then-act-races.md)).

## 순서 (각 단계 실패 시험 먼저)

1. **임시 점유와 판정 순서.** 시험: (a) 발행 중인 rosy_01이 판정 전이면, 마주 오는 rosy_02 미션은 rosy_01의 직선 경로에 막혀 대기한다. (b) 같은 사이클에서 배경 작업의 임시 점유가 먼저 판정 잠금에 닿아도, 먼저 기록된 운영자 작업의 임시 점유에 양보한다. 구현: 임시 점유에 기록 순번을 두고(`_provisional: dict[robot, seq]`), 판정은 실제 점유와 자기보다 작은 순번의 임시 점유만 본다. 명단 제거 때 지우는 로봇별 상태 묶음(`console.py` 명단 정리)에 `_provisional`을 더한다.
2. **판정 뒤 전환.** 시험: 수락 + 경로 계획 없음이면 직선 점유가 남는다. `accepted is False`·확인된 취소 뒤에는 점유가 없다. timeout·5xx 뒤에는 일반 점유가 남고, 로봇이 NAVIGATING이 아님이 보이면 `_run_traffic`이 지운다. 구현: `_claims[robot] = intended`(빈 `route` 금지), 결과별 분기.
3. **스냅샷 정리.** 시험: 임시 점유는 `_run_traffic`이 지우지 않는다. 판정 잠금이 잡혀 있는 동안 `snapshot()`은 기다리지 않고 끝나며 점유 정리는 다음 스냅샷으로 미룬다. 구현: `_traffic_lock.locked()`이면 정리를 건너뛴다. 대기 미션 재발행은 그대로 `goal()`.
4. **취소 정리.** 시험: 발행 태스크를 (a) 잠금 대기 중 (b) 전송 뒤 판정 중 취소하면 로봇에 취소가 가고, 작업은 `UNKNOWN`(`DISPATCH_CANCELLED`), 점유는 2단계 규칙대로다. 구현: 태스크 본체의 `except asyncio.CancelledError`에서 `asyncio.shield`로 `console.cancel`과 상태 전이를 마친 뒤 다시 올린다.
5. **로봇별 발행.** 시험: 첫 로봇 `send_goal`이 Event에 묶여 멈춘 동안 다른 로봇들은 같은 사이클에 발행된다. 진행 중인 로봇은 다음 사이클 claim에서 빠진다(`fleet_action_claims`). 앱 종료 시 진행 중 태스크가 취소되고 4단계 정리를 마칠 때까지 기다린다. 구현: `background_workers`가 `dict[robot_id, Task]`를 들고 끝난 태스크를 거둔다. 예외는 기존 감독 로그 경로로 보낸다.
6. **관측성.** 시험: 발행 로그에 `traffic_wait_s`가 있다. 구현: 잠금 획득 전후 `time.monotonic()`.
7. **정지 경로 회귀.** 시험: 판정 잠금을 다른 미션이 잡고 있어도 cancel-all·e-stop은 즉시 끝난다.

## 검증

- 원격: `operations/fleet/test` 전체(`tools/remote/remote_pytest.py`), 새 실패 0.
- 합성: `Rosy/docs/research/d271-gate-a-2026-10-30/` 계측기를 새 revision에 다시 돌려 slow-receipt 시나리오의 다른 로봇 마지막 발행이 1초 지연에 묶이지 않는지, 이벤트 루프 최대 지연과 `/healthz` 예약 지연이 드레인 결과(32대 18 ms / 41-56 ms)보다 나쁘지 않은지 본다.
- SIM: 다중 로봇 Gazebo에서 교차·정면·비켜세우기 시나리오를 직렬 발행 revision과 비교한다.
- 착지: console 경로는 safety-tagged이므로 독립 검토자의 `Safety-Review:` trailer가 필요하다.

## 범위 밖

브로커 도입(D-271), 화면·API 필드 추가, 달리는 로봇의 우선순위 선점, 판정 구간에서 로봇 HTTP 호출 빼기(D-928 Consequences의 후속), DEVICE/FIELD 수용.
