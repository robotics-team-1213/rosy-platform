## D-1064 main push 실행은 큐 실행이 같은 범위로 통과한 커밋이면 guard 묶음만 다시 돈다

**Status:** Accepted (2026-11-21, 사용자 결정: "좋아 진행해"). 2026-11-17 결정 "서명기는 정확한 main 커밋의 push CI만 인정한다"는 그대로다. push 실행은 계속 돌고 녹색이어야 한다. 바뀌는 것은 그 실행이 도는 범위다. 켜는 것은 저장소 변수 `ROSY_PUSH_SAME`이고 기본은 꺼짐이다.

잇는 결정: [D-1059](D-1059-merge-queue-retests-what-changed-since-the-pr-run.md)(큐 실행) · [D-762](D-762-main-gateway-pull-request-merge-queue.md)(Merge Queue) · [D-1055](D-1055-pr-merge-queue-only-merge-path-land-retired.md).

### Context

- 2026-11-21 03:00~06:45Z에 CI 65회가 작업 754개, 러너 2,719분을 썼다. 조직의 동시 작업 한도는 20개다. 실행 50건 중 20건이 작업 하나를 2분 넘게, 길게는 15분 기다렸고 실행 시간 중앙값이 418초에서 590초로 늘었다.
- 러너 시간의 24%가 main push 실행이다. PR 하나가 단독으로 병합되면 push 실행은 큐 실행과 같은 커밋에서 같은 범위(`HEAD^1..HEAD`)를 고른다. 같은 시험을 같은 트리에서 한 번 더 도는 것이다.
- 큐가 PR 여러 개를 한 번에 병합하면 다르다. push 실행은 그 PR들의 변경 전체를 최종 트리에서 고르고, 큐 실행은 마지막 PR의 변경만 골랐다. 이 경우 push 실행은 중복이 아니다.
- 최근 main push 59건 중 49건이 단독 병합이었다.

### Decision

| 항목 | 결정 |
|---|---|
| 조건 | push의 이전 tip(`github.event.before`)이 `HEAD^1`과 같고, `ci.yml`의 merge_group 실행이 바로 그 커밋에서 성공으로 끝났을 때. |
| 동작 | `tools/harness/affected_queue.py --pushed <before>`가 그 커밋을 돌려주고, 선택은 D-1059와 같은 경로로 guard 묶음만 남는다. build-smoke 판단은 그대로다. |
| 전부 도는 경우 | 묶음 병합(`HEAD^1`이 이전 tip이 아님), 큐를 거치지 않은 직접 push, 큐 실행 기록 없음·실패, push base를 모름(기존대로 FULL), 선택이 FULL, API 조회 실패. |
| 그대로인 것 | push 실행 자체와 그 필수성, 서명기 규칙, Safety-Review·크기 검사, 예약·수동 전체 실행. |

### Consequences

- D-1059와 겹치면, 트리가 같은 변경은 PR 실행에서 시험이 한 번 돌고 큐와 push에서는 guard 묶음만 돈다. 시험 범위는 같고 실행 횟수가 준다. 불안정 시험이 뒤에서 한 번 더 걸러질 기회가 없어진다.
- 러너 사용량이 줄어 대기가 줄고, 병합 뒤 서명 가능 시점이 당겨진다.
- 되돌리기: 저장소 변수 `ROSY_PUSH_SAME`을 지우면 즉시 이전 동작이다.
- 남은 확인: 변수를 켠 뒤 push 실행 로그의 `[queue]` 줄로 적용 비율을, 작업 단위 대기 시간으로 효과를 본다.
