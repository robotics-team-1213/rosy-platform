---
module: tools/remote/remote_pytest.py, tools/harness/affected_tests.py
date: 2026-10-29
problem_type: workflow_issue
component: testing_framework
severity: high
applies_when:
  - "using affected JSON to choose remote verification or reporting a FULL selection"
tags: ["full-tier", "affected-json", "verification-scope", "evidence", "remote-pytest"]
---

# FULL 판정과 실제로 실행한 전체 행렬을 구분한다

## Context

G1b에서 selector의 `mode=full`을 보고 native remote runner에 JSON을 전달했다. 네 묶음의 25,723 passed/1,296 skipped는 실제 결과였지만, 이를 공식 FULL 행렬 통과로 보고했다. 후속 G1c 조사에서 이 CLI가 실행한 값은 `local_invocations`이고, 공식 전체 범위인 `full_invocations`는 별도 27개 묶음임을 확인했다. 이전 계수를 지우지 않고 범위 표기를 정정했다.

`tools/remote/remote_pytest.py`의 `affected_invocations()`는 `mode=full`이면 `local_invocations`를 고른다. 반면 `tools/harness/affected_tests.py`의 `lab_full_invocations()`는 CI 행렬·root 시험·나머지 module 시험으로 별도의 전체 호출 목록을 만든다. `mode`는 선택기의 판정이며 실행 계층을 증명하는 영수증이 아니다.

## Guidance

FULL이 필요한 작업에서는 실제 실행기가 소비할 배열을 먼저 확인한다. 다음 비교의 `selected`에는 실행기로 전달할 실제 호출 배열을 넣는다.

```python
full = selection["full_invocations"]
assert selection["mode"] == "full" and full
assert selected == full
```

필요한 host/process 격리는 경로를 빼는 대신 별도 scheduling 옵션으로 기록한다. 이 회차는 원래 27개 호출을 native CLI가 소비하는 배열에 전달했고, root `test`에만 `ROSY_BROWSER_ALONE=1 -n 0`을 추가했다. 독립 검토가 원래 배열과 비교하여 삭제된 경로가 없음을 확인했다. runner 이름이나 JSON `mode`만 기록하지 말고 source commit, 실제 argv, 각 terminal code, report의 실행·skip 수와 known-failure 비교를 남긴다.

정확한 CLI 동작을 모르거나 전체 호출을 아직 실행하지 않았다면, 통과한 것을 “선택된 로컬 회귀”로 보고하고 공식 FULL은 미수행/진행 중으로 남긴다. 이 교훈을 기록한 시점의 D-916 공식 행렬은 실행 중이므로 아직 통과를 주장하지 않는다.

## Evidence and applicability

- 로컬 작업 브랜치에서 위 두 함수의 실제 선택 경로와 별도 full 배열을 대조했다. 정확한 source commit은 아래 D-916 검증 기록에 둔다. 미착지·미게시 source이며 PR은 없다. 게시되거나 main에 포함됐다는 근거로 쓰지 않는다.
- 고정 selector의 원래 local 배열은 1개, 공식 full 배열은 27개였다. 외부 실행 adapter는 27개를 보존했고 root 격리 옵션 외의 차이가 없었다.
- 실제 새 실행은 이전 로컬 범위에 없던 학습 묶음들을 별도 로그로 실행했다. 전체 성공 여부는 [D-916 검증 기록](../../validation/joint-source-provenance-2026-10-29/result.md)에서 확인하며, 이 지식 문서로 대체하지 않는다.
- 이전 범위 정정과 보존된 로그 hash는 [D-915 기록](../../validation/physical-evidence-export-2026-10-29/result.md)에 있다. 변경은 아직 작업 브랜치에 있으며 착지·게시 수용을 뜻하지 않는다.

예방: FULL이라고 보고하기 전에 원격 argv 전체가 공식 `full_invocations`의 경로·묶음을 덮는지 비교한다. 선택기/runner의 이 동작이 바뀌면 정본 함수를 다시 읽고 이 적용 조건을 재검토한다.
