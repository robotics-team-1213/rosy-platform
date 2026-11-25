---
title: safety 태그 파일을 main이나 앞선 큐 항목과 같이 고친 PR은 큐의 병합 커밋에서 Safety-Review 검사에 튕긴다. main을 브랜치에 합쳐 병합 커밋을 검토한다
date: 2026-11-25
category: workflow-issues
module: tools/harness (safety_review.py), .github/workflows/ci.yml (scope job), tools/pr_land.py, docs/reference/shared-checkout.md
problem_type: workflow_issue
component: development_workflow
severity: medium
root_cause: queue_merge_commit_changes_a_safety_tagged_path_unreviewed
resolution_type: workflow_improvement
symptoms:
  - "PR CI는 모두 통과하고 자동 병합으로 큐에 들어갔는데 몇 분 뒤 github-merge-queue[bot]이 PR을 큐에서 꺼내고 자동 병합이 꺼진다. PR은 열린 채 남고 GitHub가 보고하는 상태에는 실패가 나타나지 않는다(이번 경우 CLEAN)"
  - "큐 안 CI(merge_group)의 scope 작업 Safety-Review trailer (D-430) 단계가 큐가 만든 병합 커밋을 거절한다. 로그는 safety-tagged changes without a Safety-Review trailer 와 touches <safety 태그 경로> 다"
  - "큐에서 나온 경우에는 PR의 statusCheckRollup과 mergeStateStatus에 이 실패가 보이지 않아 PR 목록만 보면 원인을 알 수 없다"
applies_when:
  - "PR이 platform_parts.yaml의 safety_review_paths, safety_modules, concern: safety 경로를 고친다"
  - "main이 PR base보다 앞으로 갔고 그 사이 같은 파일이 바뀌었다. git 충돌은 없다"
  - "같은 safety 태그 파일을 고치는 다른 PR이 큐에서 이 PR보다 앞에 있거나 자동 병합으로 대기 중이다"
tags: [merge-queue, merge-group, safety-review, d-430, d-1055, pr-land, safety-tagged-path, diff-tree-cc]
---

# safety 태그 파일을 main이나 앞선 큐 항목과 같이 고친 PR은 큐의 병합 커밋에서 Safety-Review 검사에 튕긴다. main을 브랜치에 합쳐 병합 커밋을 검토한다

지금 큐에서 나온 PR을 처리하는 사람은 「복구 방법」부터 본다.

이 문서에서 `BEHIND`는 main이 PR base보다 앞으로 간 상태를 뜻한다. 이 저장소 문서가 쓰는 말이다. GitHub는 이 저장소에서 그 상태를 `CLEAN`으로 보고한다. ruleset이 최신 main을 요구하지 않는다.

## 증상

- PR #763(`feat/omx-calibrate-check-targets`). 2026-11-24T21:44Z에 PR CI(`pull_request`)가 시작돼 21:47Z에 모두 통과했고 같은 시각 자동 병합으로 큐에 들어갔다. 21:55Z에 `github-merge-queue[bot]`이 큐에서 꺼냈다. 자동 병합은 꺼졌고 PR은 열린 채 `CLEAN`으로 남았다.
- 큐 안 CI(`merge_group`)의 `scope` 작업, "Safety-Review trailer (D-430)" 단계 로그:

  ```text
  [safety-review] safety-tagged changes without a `Safety-Review: <reviewer/lane> <evidence>` trailer (D-430 section 5):
  <sha> Merge pull request #763 from robotics-team-1213/feat/omx-calibrate-check-targets (author livsbittt)
      touches deploy/robot/omx/cell_job_spec.py
  ```

- 이 병합 커밋은 main에 들어오지 않았다. 어느 ref에서도 닿을 수 없어 `git branch -a --contains`가 빈다.

- 거절된 커밋은 PR의 커밋이 아니라 큐가 만든 병합 커밋이다. 로컬 게이트(`pr_land.py --dry-run`, `safety_review.py origin/main HEAD`)는 브랜치 head에서 통과했다. PR CI는 PR head를 그때 main과 합친 커밋에서 통과했다.

## 원인

- `tools/harness/safety_review.py`는 병합 커밋을 `git diff-tree --cc --no-commit-id --name-only`가 나열하는 경로만 본다. 이는 모든 부모와 한 번에 다른 경로다. 목록에 safety 태그 경로가 있으면 그 병합 커밋에 `Safety-Review:` 트레일러가 필요하다(D-430 §5).
- 검사 범위는 이벤트마다 다르다. `.github/workflows/ci.yml`의 `scope` 작업은 `SAFETY_BASE`를 `pull_request`에서는 PR base, `merge_group`에서는 `merge_group.base_sha`로 잡고 `safety_review.py "$SAFETY_BASE" HEAD`를 돌린다. `merge_group`의 HEAD는 큐가 만든 병합 커밋이고 거기에는 트레일러가 없다.
- 큐는 PR을 차례로 쌓는다. 앞선 항목을 main에 아직 넣지 않은 채 그 항목의 병합 커밋 위에 다음 PR을 합친다. #763이 21:47Z에 큐에 들어갈 때 #762와 #754가 먼저 있었다. 그래서 #763 큐 실행의 `SAFETY_BASE`는 21:47Z 당시 main(`3b01a2f01e`)이 아니라 #754의 큐 병합 커밋 `8317d6e924`였다. #754는 `cell_job_spec.py`의 `build_argv` 두 줄을 바꿨고, 그 변경은 3분 전 #763 PR CI가 합쳐 본 main에는 없었다. #754는 21:55Z에 main에 들어왔고 #763은 같은 초에 큐에서 나왔다.
- 그 결과 큐의 병합 커밋에서 그 파일은 양쪽 부모 어느 쪽과도 다르다. git 충돌은 아니라서 `mergeable`은 `MERGEABLE`이다.
- 규칙(`docs/reference/shared-checkout.md` 「main 따라가기」)은 `BEHIND`인 PR의 main을 합치지 않는다. 이 사례는 그 규칙을 지켜서도, 큐에 넣기 전에 main을 합쳐서도 막을 수 없었다. 원인이 된 변경이 그때는 main에 없고 큐에 있었다.
- 로컬 게이트는 브랜치 head만 본다. PR CI는 PR head와 그때 main을 합친 커밋(`refs/remotes/pull/N/merge`)만 본다. 둘 다 큐가 앞선 항목을 쌓은 위에서 만든 병합은 보지 못한다.

## 해결

force-push와 rebase는 쓰지 않는다(D-1055). 원인이 된 PR이 main에 들어온 뒤에 main을 브랜치 쪽에 합쳐 병합을 미리 만들고 검토한다.

1. 브랜치 워크트리에서 `git fetch origin && git merge --no-edit origin/main`. 충돌이 없으면 그대로 둔다.
2. `git diff-tree --cc --name-only HEAD`로 그 병합 커밋이 양쪽 부모와 다르게 쓰는 경로를 본다. 태그 경로가 있으면 병합 결과를 독립 리뷰(D-430 §5)가 승인해야 한다. 리뷰는 `git show --cc HEAD -- <경로>`에 두 부모와 한 번에 다른 줄이 없는지와 두 변경이 같은 함수에서 서로 방해하지 않는지를 본다.
3. 합친 head에서 시험 PC 시험을 다시 돌린다(`tools/remote/remote_pytest.py` 뒤에 `python test/known_failures.py <log>/run-1.txt`).
4. 병합 커밋 메시지에 `Safety-Review:` 트레일러를 단다. 푸시 전이면 메시지만 바꾸고 트리가 같은지 확인한다.
5. `python tools/pr_land.py --evidence`로 다시 큐에 넣는다. 큐의 병합 커밋은 브랜치 head에 앞서 쌓인 것을 더한 트리다. `--cc`는 양쪽에서 바뀐 경로만 나열하므로, 쌓인 것이나 새 main이 이 브랜치의 태그 경로를 건드리지 않으면 목록이 비고 검사를 통과한다. 같은 태그 파일을 고치는 PR이 큐에 앞서 있으면 다시 튕긴다.

## 검증 근거

- #763: 거절 뒤 #754가 main에 들어간 다음 위 절차로 main을 합치고 병합 커밋을 검토받아 다시 큐에 넣었다. 한 번에 병합됐다. 합친 head에서 영향 범위 시험 260 + 461개, 보정 관련 109개 통과.
- #774(`fix/omx-s3-dry-run-release`): 시험 파일이 #763과 충돌해서 어차피 main을 합쳐야 했다. 합치면서 병합 커밋을 검토받고 트레일러를 달아 큐에 넣었다. 큐에서 나오지 않고 병합됐다. 영향 범위 260 + 484개, 작업·릴리스 관련 268개 통과.
- 두 PR 모두 `known_failures.py` 0 new.

## 복구 방법

1. `gh api repos/<owner>/<repo>/issues/<N>/timeline`에서 `added_to_merge_queue`와 `removed_from_merge_queue`를 확인한다.
2. `gh run list --event merge_group`에서 `gh-readonly-queue/main/pr-<N>-…` 실행을 찾고 `gh run view <id> --log-failed`로 `scope` 작업 로그를 읽는다. 큐에서 나온 경우라서 PR의 `statusCheckRollup`에는 나오지 않는다.
3. 거절된 커밋을 구분한다. PR의 커밋이면 그 커밋에 트레일러가 없는 것이다. 제목이 `Merge pull request #N`이면 큐가 만든 병합 커밋이다. 제목이 `Merge <head> into <base>`이면 GitHub가 만든 시험용 병합 커밋이고, 이때는 실패가 PR의 `statusCheckRollup`에 보인다. 병합 커밋 둘 다 이 교훈의 경우이니 「해결」을 따른다.
4. 같은 태그 파일을 고치는 다른 PR이 큐에 있거나 자동 병합으로 대기 중이면(`gh pr list --state open --json number,files,autoMergeRequest`, `python tools/merge_queue.py list`) 그것이 앞서 들어갈 때 같은 일이 다시 생긴다. `git diff --name-only <합친 main> origin/main -- <태그 경로>`는 이미 main에 들어온 변경만 보인다.

## 다음에 적용할 조건

- safety 태그 경로를 고친 PR을 올리기 전에 같은 경로를 고치는 다른 PR이 열려 있거나 큐에 있는지 본다(`gh pr list --state open --json number,files,autoMergeRequest`, `python tools/merge_queue.py list`). 있으면 그 PR이 먼저 들어간 뒤 이 PR이 큐에서 나올 것으로 간주하고 「해결」을 바로 할 준비를 한다.
- main에 이미 들어온 변경은 `git diff --name-only $(git merge-base HEAD origin/main) origin/main -- <그 경로>`로 보인다. 이때는 큐에 넣기 전에 「해결」을 먼저 한다. PR CI의 `scope`도 같은 검사를 하므로 같은 메시지로 실패할 것으로 보인다. 관측하지는 않았다.
- PR CI가 통과했다는 것은 큐의 병합 커밋이 통과한다는 뜻이 아니다. 큐는 앞선 항목까지 쌓은 위에서 합친다. 큐에서 나온 PR은 PR 상태가 아니라 큐 안 실행을 본다.
- PR 병합을 기다리는 스크립트는 `statusCheckRollup`의 실패만 보지 않는다. 타임라인의 `removed_from_merge_queue`도 보되, 그것은 병합 성공 때도 남는다(`merged`와 같은 초). PR state가 아직 `OPEN`일 때만 빠진 것으로 센다. 큐에 들어간 PR은 `autoMergeRequest`가 `null`이 되므로 그것만으로 빠진 것으로 판정하지 않는다. 같은 head에서 같은 이름의 검사가 두 번 잡히면 옛 실행이 `CANCELLED`로 남을 수 있다(#763의 `review-gate`).

## 관련

- `docs/solutions/workflow-issues/pr-path-cutover-needs-a-real-end-to-end-run-2026-11-20.md`: 큐 안 시험 실패로 큐에서 나온 경우.
- `docs/solutions/workflow-issues/check-the-tested-pull-request-merge-commit-2026-11-25.md`: CI를 다시 돌리기 전에 실제로 시험한 시험용 병합 커밋을 확인하는 방법.
- `docs/adr/D-430-safety-as-a-separate-concern.md` §5, `docs/adr/D-1055-pr-merge-queue-only-merge-path-land-retired.md`, `docs/reference/shared-checkout.md` 「main 따라가기」.
