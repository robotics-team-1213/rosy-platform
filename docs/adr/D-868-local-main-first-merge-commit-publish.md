## D-868 로컬 main에 먼저 착지하고, 공개 main에는 그 로컬 main을 merge commit으로 올린다

**Status:** Accepted (2026-10-25, 사용자 결정)

잇는 결정: [D-427](D-427-platform-three-parts-middleware-operations-learning.md) 4항(push 순서, 이 ADR이 대체한다) · [D-762](D-762-main-gateway-pull-request-merge-queue.md)(main으로 가는 길, squash 전용 설정을 이 ADR이 바꾼다) · [D-372](D-372-topic-branch-names-and-shared-checkout-wip.md)(같이 하는 깃) · [D-803](D-803-landing-queue-before-delta-rerun.md)(착지 대기열).

### Context

2026-10-16(#54) 뒤로 로컬 `main`과 `origin/main`이 갈라졌다. 실험실 세션은 `tools/land.py`로 로컬 `main`에 착지했고, 같은 작업의 일부는 `origin/main` 기반 브랜치의 PR로 올라가 **squash** 병합됐다. squash 커밋은 원래 커밋과 다른 커밋이라 두 이력은 다시 만나지 못했다. 2026-10-25에 로컬 `main`은 2,222 커밋 앞, 120 커밋 뒤였고, 두 이력을 합치는 병합에서 333개 파일이 충돌했다. squash는 브랜치 커밋의 `Safety-Review:` trailer도 지워서 `safety_review_exempt.json`에 사후 연결 항목이 다섯 번 필요했다(#82, #86, #110, #126, #168). origin 기반 PR 브랜치는 로컬 `main`의 도구(`ROSY_SCRATCH` 등)도 받지 못했다.

### Decision

1. **모든 변경은 먼저 로컬 `main`에 착지한다.** 주제 브랜치는 로컬 `main`에서 만들고(`tools/worktrees.py new`), `tools/land.py`로 `--ff-only` 착지한다. `origin/main`에서 주제 브랜치를 만들지 않는다.
2. **공개 `main`에는 로컬 `main`만 올린다.** 순서:
   1. `git fetch`. `origin/main`이 로컬 `main`의 조상이 아니면, 워크트리에서 `git merge origin/main`으로 합치고 `tools/land.py`로 착지한다.
   2. `python tools/harness/rosy_harness.py generate`. 생성 문서가 바뀌면 커밋해 착지한다.
   3. 로컬 `main`의 끝을 `publish/main-<YYYYMMDD>[-n]` 브랜치로 push한다(pre-push 검사 통과). 그 브랜치로 `main` 대상 PR을 연다.
   4. `ci-result`가 녹색이면 `gh pr merge <PR> --merge --match-head-commit <SHA>`로 **merge commit** 병합한다.
   5. `git fetch` 다음 `main` 체크아웃에서 `git merge --ff-only origin/main`. 이제 로컬 `main`과 `origin/main`은 같은 커밋이다.
3. **squash와 rebase 병합은 쓰지 않는다.** 저장소 설정과 `main-protection` ruleset의 허용 병합 방식은 `merge` 하나다. 팀원 PC의 PR도 merge commit으로 병합하고, 실험실 세션은 다음 착지 전에 1번 순서로 그 병합을 로컬 `main`에 받는다.
4. **force-push는 하지 않는다.** 이미 게시한 커밋은 고쳐 쓰지 않는다.

### Consequences

- 두 이력이 하나로 유지되어 원래 커밋과 `Safety-Review:` trailer가 그대로 `main`에 남는다. squash 연결용 예외 항목이 더는 생기지 않는다.
- `origin/main`의 이력은 PR 단위 한 줄이 아니라 착지 커밋 전체다. 요약은 merge commit 제목과 PR 본문이 맡는다.
- PR 하나가 여러 주제를 담는다. 검토는 [PR 파이프라인](../reference/pr-pipeline.md)의 범위 검토를 그 PR의 base..head에 적용한다.
- D-762의 끝 상태(공유 로컬 `main` 없애기)는 보류한다. 로컬 `main`이 통합 브랜치로 남는다.

### 확인하지 못한 것

- merge commit PR의 `ci-result` 소요 시간. 첫 게시(2,222 커밋)의 CI에서 잰다.
