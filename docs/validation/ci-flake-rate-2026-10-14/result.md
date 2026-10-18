# CI 불안정 비율 측정 (D-762 단계 1, 2026-10-14)

`gh workflow run ci.yml --ref main`을 한 번에 하나씩 여섯 번 돌렸다(전체 티어, 실행마다 잡 17개). 첫 dispatch 뒤 `origin/main`이 00d7c3679에서 b1e84dd79로 움직였다. 그래서 실행 1은 00d7c3679에서, 실행 2–6은 b1e84dd79에서 돌았다. 두 sha 모두 push 실행이 녹색이었다(38554116295, 38564679502). 이 측정은 이 브랜치의 변경(`modules` 러너, 재시도)을 싣지 않은 `main`의 `ci.yml`로 돌았다.

| # | 실행 | sha | 결과 | 벽시계 | 잡 분 | 실패한 잡 | 실패한 시험 |
|---|---|---|---|---|---|---|---|
| 1 | 38563920833 | 00d7c3679 | 녹색 | 11.3분 | 66.4 | — | — |
| 2 | 38565544698 | b1e84dd79 | 녹색 | 10.9분 | 65.3 | — | — |
| 3 | 38567080526 | b1e84dd79 | 녹색 | 12.7분 | 66.4 | — | — |
| 4 | 38568954601 | b1e84dd79 | 적색 | 13.0분 | 67.0 | `test (fleet-4of4)` | `operations/fleet/test/test_ai_facts.py::test_a_stalled_fact_write_does_not_delay_the_emergency_stop` (`AssertionError: 0.83`, 한도 0.5 s) |
| 5 | 38571112242 | b1e84dd79 | 적색 | 13.1분 | 65.0 | `test (fleet-4of4)` | `operations/fleet/test/test_incident_cost_receipt.py::test_actual_worker_cost_evidence_or_failure_reaches_atomic_store_and_readonly_export[True]` ("worker did not become idle") |
| 6 | 38573105206 | b1e84dd79 | 적색 | 11.1분 | 64.4 | `test (core-domain)` | `middleware/core/gateway/test/test_line_junction_api.py::test_refused_while_manual_control_is_active` (409 `LINE_FOLLOW_NOT_ACTIVE`, 기대 `MODE_CONFLICT`) |

## 비율

- 같은 sha(b1e84dd79)에서 실행 5번 중 적색 3번: 실행 단위 불안정 비율 60%. 여섯 번 전체로는 50%다.
- 실패한 시험은 세 개이고 서로 다르다. 같은 sha의 다른 네 번(push 실행 포함)에서는 모두 통과했다. 실행마다 시험은 2만 개가 넘는다. 시험 단위로는 드물지만, 실행 하나를 적색으로 만들기에는 충분하다.
- 비용: 실행마다 잡 분 64–67, 여섯 번에 395 잡 분. 공개 저장소라 러너 분은 과금되지 않는다. 벽시계는 10.9–13.1분이다.

## 처리

- `test_incident_cost_receipt.py::...[True]`는 `test/flaky_quarantine.txt`에 넣었다. 실패가 이미 넣은 `test_model_recovery_submit.py::...[unknown]`과 같은 부류다(fleet 작업자 유휴 대기). 이 브랜치의 규칙이 있었다면 실행 5는 그 시험을 한 번 다시 돌렸을 것이다. 다시 돌린 결과가 통과였다면 실행 5는 녹색이었다.
- 나머지 둘은 격리하지 않았다. 둘 다 안전 경로다. 하나는 비상정지 지연 한도이고, 하나는 수동 조작 중 모드 충돌 거절이다. 격리하면 실제 회귀(비상정지가 느린 쓰기를 기다림, 거절 순서의 경쟁)를 가릴 수 있다. 각 소유자가 원인을 보고 고칠지 정한다. 그 전까지 이 둘은 단계 3에서 큐를 멈출 수 있다.
- 원본: `X:/DevTemp/land-recent/stage1/flake/run-<n>.json`, `run-<n>-failed.log`.
