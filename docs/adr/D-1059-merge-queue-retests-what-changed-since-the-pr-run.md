## D-1059 Merge Queue는 PR의 녹색 실행 뒤에 바뀐 것이 닿는 시험만 다시 돈다

**Status:** Accepted (2026-11-21, 사용자 결정: "큐 재시험 되는걸 선별하는거면 되지않아", "남은것도 바로 처리해"). [D-762](D-762-main-gateway-pull-request-merge-queue.md)의 큐 재시험 범위만 바꾼다. 켜는 것은 저장소 변수 `ROSY_QUEUE_DELTA`이고 기본은 꺼짐이다.

잇는 결정: [D-436](D-436-change-scoped-test-tiers.md)(affected 선택) · [D-762](D-762-main-gateway-pull-request-merge-queue.md)(Merge Queue) · [D-1052](D-1052-self-review-and-zero-full-ci.md) · [D-1055](D-1055-pr-merge-queue-only-merge-path-land-retired.md).

### Context

- 같은 affected 선택이 pull_request, merge_group, main push에서 세 번 돈다. 2026-11-20 병합 25건에서 큐 진입→병합 중앙값은 9.2분이었다.
- GitHub Free의 동시 작업은 조직 전체 20개다. 2026-11-21 새벽 CI 85회에서 작업의 러너 대기 중앙값이 2초에서 45~177초로 늘었다. 큰 선택(작업 17~29개)이 큐에서 한 번 더 도는 것이 풀을 채운다.
- PR 실행은 PR head와 그 시점 base의 병합 커밋을 시험한다. 그 커밋은 나중에도 SHA로 받아올 수 있다(6건 확인). PR #350은 큐가 시험한 트리가 PR 실행이 통과한 트리와 같았다.
- 패널(Claude·Codex·opencode, 2026-11-21)은 "PR 선택과 main 쪽 선택의 교집합"을 그대로는 기각했다. 이름 변경과 수정이 겹치는 경우와, 좁은 티어가 알려진 읽기 시험만 고르는 경우를 놓친다.

### Decision

| 항목 | 결정 |
|---|---|
| 증거 | 녹색 pull_request 실행의 `ci-result`가 시험한 병합 커밋을 notice(`rosy-tested-commit`)로 남긴다. 쓰기 권한을 더하지 않는다. |
| 큐 실행 | `ROSY_QUEUE_DELTA=1`이면 scope가 PR head(`HEAD^2`)의 그 notice를 읽고, 커밋을 받아 둘째 부모가 PR head인지 확인한 뒤 `ROSY_QUEUE_TESTED`로 넘긴다. |
| 선별 | `tools/harness/affected_queue.py`가 시험한 커밋과 큐 커밋의 **두 트리를 직접 비교**한다. 그 차이를 affected로 선택해, PR 선택 가운데 그 선택과 겹치는 경로만 남긴다. guard 묶음은 늘 남는다. build-smoke 판단은 PR 변경 기준 그대로다. |
| 선별하는 경우 | 두 트리의 차이가 **전부** 시험 파일, Markdown, 등록 모듈 안의 Python일 때만. 선택기가 import와 모듈 등록으로 고르는 변경이다. |
| 전부 도는 경우 | 그 밖의 모든 경우. notice 없음(fork 포함), 커밋 불일치, 파일 삭제, FULL trigger 경로(`contracts/foundation` 등은 알려진 읽기 시험만 고른다), safety 경로, 설정·데이터·웹 자산, 차이의 선택이 FULL·좁은 티어·미분류, PR 선택이 FULL, `ROSY_FULL_LEGACY`. |
| 그대로인 것 | pull_request 실행, main push 실행(서명기는 정확한 main 커밋의 push CI만 인정), 필수 검사 이름, Safety-Review·크기 검사. |

### Consequences

- 큐에서 빠진 시험은 "PR 실행에서 통과했고, 그 뒤 바뀐 파일이 선택기 모델로 닿지 않는" 시험이다. 선택기는 직접 의존 한 단계만 본다. 두 단계 이상 떨어진 의존과 실행 중에 읽는 파일은 놓칠 수 있다.
- main push 실행은 병합된 PR의 변경으로 같은 선택을 병합된 트리에서 돈다. 큐가 지금 도는 것과 같은 범위다. 선별이 놓친 조합은 여기서 잡히지만 그때는 main이 이미 적색이고, 서명기는 적색 main을 서명하지 않는다.
- 작은 PR은 guard 묶음이 하한이라 줄어드는 것이 거의 없다. 선택이 큰 PR의 큐 실행이 줄고 러너 풀이 빈다.
- 되돌리기: 저장소 변수 `ROSY_QUEUE_DELTA`를 지우면 즉시 이전 동작이다. 코드 되돌리기는 `affected_ci.ci_matrix`의 호출 한 줄이다.
- 남은 확인: 변수를 켠 뒤 큐 실행 로그의 `[queue]` 줄로 선별 비율과 "전부 도는 경우" 사유를 일주일 모은다. main push 적색이 큐 선별에서 빠진 시험 때문이면 이 ADR을 다시 연다.
