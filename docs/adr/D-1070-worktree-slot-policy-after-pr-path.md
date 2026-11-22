## D-1070 깨끗한 워크트리는 6시간 뒤 누구나 지우고, 브랜치는 adopt로 다시 붙인다

**Status:** Accepted (2026-11-21, 조정 세션 지시). [D-886](D-886-worktree-budget-cap-and-merged-branch-sweep.md)의 한도 14는 그대로 두고, [D-790](D-790-worktree-rules-landed-orphan-stale-flaky.md) 이후 "병합되지 않은 것은 72시간" 규칙을 깨끗한 워크트리에 한해 바꾼다.

잇는 결정: D-761 · D-790 · D-886 · [D-1055](D-1055-pr-merge-queue-only-merge-path-land-retired.md).

### Context

- 2026-11-21 20:25 KST 실측: `.worktrees/` 43개 중 38개가 깨끗하고(미커밋 0) 모두 커밋되어 있었다. PR이 열린 것은 3개였다. 한도 14에 걸려 모든 세션의 `new`가 거절되었다.
- D-1055 뒤 브랜치는 PR로 `origin/main`에 병합되고 로컬 `main`은 자주 뒤처진다. 병합 판정은 이미 `origin/main` 조상도 포함한다(`worktree_rules.merge_targets`). 병합되지 않은 브랜치의 워크트리는 72시간을 기다렸다.
- 깨끗하고 커밋된 워크트리는 브랜치에 모든 것이 있다. 지워도 잃는 것이 없고, 다시 붙이는 길만 있으면 된다. `new`는 기존 브랜치를 거절했다.

### Decision

1. 깨끗하고(추적 파일 변경·스테이징·추적 안 된 파일 0, 캐시 밖 무시 파일 없음), 잠기지 않았고, 브랜치에 있는 워크트리는 `CLEAN_IDLE_HOURS`(6시간, `--idle-hours`가 더 작으면 그 값) 쉬면 `prune --apply`가 지운다. 병합 여부와 소유자는 보지 않는다. `main`에 없는 브랜치는 남기고 제거 줄에 `adopt` 명령을 적는다. `adopt`가 붙일 수 없는 브랜치(`<type>/<topic>` 형식 밖, `stale-history`)는 잃는 것 없음 전제가 깨지므로 제외하고 기존 72시간(미병합은 `--snapshot`) 규칙을 따른다.
2. `python tools/worktrees.py adopt <짧은 이름> <type>/<topic>`은 기존 로컬 브랜치를 `.worktrees/<짧은 이름>`에 붙인다. 이름 형식·한도·`--force-over-cap`·소유자 기록은 `new`와 같다. `stale-history` 브랜치는 거절한다.
3. 쉰 시간의 정의, 미커밋 워크트리의 72시간, 잠금, 72시간 안의 소유자 기록, 분리 HEAD, `stale-history`, `--snapshot` 규칙은 바꾸지 않는다.
4. 운영 정본은 `docs/reference/shared-checkout.md` 「워크트리 한도와 슬롯 운영」이다.

### Consequences

- PR을 기다리는 깨끗한 워크트리가 슬롯을 6시간 넘게 잡지 않는다. 브랜치는 남으므로 PR·착지 흐름은 그대로다.
- 브랜치만 남은 미착지 브랜치는 14일 뒤 `archive_abandoned`가 `refs/archive/`로 옮긴다. 그 뒤에는 `git branch`로 되살린 다음 `adopt`한다.
- 소유자 기록이 있는 새 워크트리는 여전히 72시간 보호된다. 슬롯 압박이 계속되면 이 보호 기간을 다음에 다시 본다.

### 개정 2026-11-22: 쉰 시간에서 index 제외, 소유자 기록 24시간

- **배경.** 이 저장소는 `core.fsmonitor=true`·`core.untrackedcache=true`라서 `git status` 한 번이 index를 다시 쓴다. 도구 자신도 `_status`로 남의 워크트리를 읽으므로 `status`·`doctor`·`new`가 볼 때마다 쉰 시간이 되살아났다(자기 오염). 그 쓰기는 `index.lock`도 잡아 그 워크트리 세션의 `git add`·`commit`과 겹칠 수 있다.
- **바꾸는 것(3항).** 쉰 시간은 팁 커밋, 워크트리 `logs/HEAD`의 마지막 항목, `.git` 파일, 캐시 밖 파일 mtime 가운데 가장 늦은 것이다. index 파일 시각은 보지 않는다. 도구의 `git status`는 `--no-optional-locks`로 돌려 index를 쓰지 않는다.
- **바꾸는 것(소유자 기록).** 깨끗하고 `adopt`할 수 있는 워크트리의 소유자 기록은 24시간(`NOTE_IDLE_HOURS`, `--idle-hours`가 더 작으면 그 값) 지킨다. `adopt` 형식 밖 이름은 72시간 그대로다. 미커밋 파일이 있으면 72시간 규칙이 따로 지킨다.
- **남는 위험.** 편집·커밋 없이 6시간 넘게 읽기만 하는 세션의 깨끗한 워크트리는 지워질 수 있다. 브랜치는 남아 `adopt`로 되돌린다. 그런 워크트리는 `git worktree lock`으로 잠근다.
- **검증.** `test/test_worktrees_tool.py`: index만 새로운 깨끗한 워크트리 제거, `status` 표가 index를 쓰지 않음, 소유자 기록 24시간 뒤 제거.

### Validation

- `test/test_worktrees_tool.py`: `origin/main` 병합 판정, 깨끗한 미병합 워크트리의 6시간 제거(브랜치 유지), 미커밋·잠김·최근 소유자 기록 유지, `adopt` 성공·형식 거절·한도 거절·`stale-history` 거절.
