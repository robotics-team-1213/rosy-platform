## D-761 워크트리는 관문 도구로 만들고, 끝난 워크트리는 손실 없는 청소로 치운다

**Status:** Proposed (2026-10-14). 사용자가 워크트리 증가를 글로 된 규칙이 아니라 프로그램 관문으로 관리하라고 요청했다. 이 결정 자체는 아직 승인되지 않았다. 2026-10-14 독립 리뷰(높음 5, 중간 6)를 반영해 고쳤다. 착지는 디스패처가 한다.

### Context

여러 에이전트 세션이 체크아웃 하나를 같이 쓰고, 세션마다 `.worktrees/<이름>`을 만든다(D-372). 만드는 절차는 있었지만 지우는 절차는 없었다.

- 2026-10-13에 워크트리가 279개, 로컬 브랜치가 1,246개였다.
- 그날 손으로 정리한 뒤 하룻밤 사이에 워크트리가 다시 124개가 됐다.
- 손 정리에 쓴 일회성 스크립트가 세 가지를 확인했다. 깨끗하고 main에 들어간 워크트리는 그냥 지워도 잃는 것이 없다. 커밋하지 않은 내용은 임시 인덱스로 커밋을 만들어 남기면 작업 트리와 브랜치를 건드리지 않고 보존된다. gitignore된 파일 가운데 캐시가 아닌 것(자격 정보, 수집 자료, 에이전트 상태)은 git이 깨끗하다고 답해도 워크트리 삭제와 함께 사라진다.

`AGENTS.md` 「같이 하는 깃」 1번은 `git worktree add`를 직접 치게 했다. 그 문장만으로는 개수가 줄지 않았다.

### Decision

1. **만드는 관문은 하나다.** 워크트리는 `python tools/worktrees.py new <짧은이름> <type>/<topic>`으로 만든다. 도구는 `<type>`이 `feat`, `fix`, `refactor`, `docs`, `uiux` 가운데 하나인지(D-372), 브랜치 이름이 `git check-ref-format --branch`를 통과하는지, 짧은이름이 경로 한 마디이고 `.`으로 끝나지 않는지, 경로와 브랜치가 아직 없는지 본 다음 `git worktree add --relative-paths .worktrees/<짧은이름> -b <type>/<topic> main`을 실행한다. `--relative-paths`를 모르는 git(2.48 미만)에서는 그 옵션 없이 다시 실행한다. 만든 사람(`user.name`, `user.email`, 있으면 `CLAUDE_CODE_SESSION_ID`)을 `branch.<브랜치>.description`에 적고 `status`가 보여 준다. 청소는 이 값을 읽지 않는다. 누구 것인지 사람이 판단할 때 쓴다.
2. **다른 명령의 부수 효과로는 아무것도 지우지 않는다.** `new`와 `tools/land.py`는 손실 없는 청소가 지울 수 있는 개수를 한 줄로 알리기만 한다(`N finished worktree(s) can be removed: python tools/worktrees.py prune --apply`). `--prune`을 주면 그 청소를 실제로 하고, `--no-prune`을 주면 알림도 하지 않는다. `land.py`에서 이 단계가 실패하면 경고만 찍고 착지를 계속한다.
3. **손실 없는 청소(`prune --apply`)의 조건.** 다음을 모두 만족하는 워크트리만 지운다. 수정·스테이징·미추적 파일이 없다. HEAD가 `main`의 조상이다. 잠겨 있지 않다. 브랜치가 `main`이 아니다. rebase, merge, cherry-pick, revert, bisect가 진행 중이 아니다. 캐시가 아닌 gitignore 파일이 없다(6항). 72시간 넘게 쉬었다(4항). main 체크아웃과 도구를 실행한 워크트리는 어떤 옵션으로도 지우지 않는다. 지우기 직전에 그 워크트리의 HEAD sha, 브랜치, 잠금, 쉰 시간을 다시 읽고, 처음 본 것과 다르면 지우지 않는다. 깨끗한 워크트리는 `--force` 없이 지워서 git이 한 번 더 확인하게 한다. 브랜치는 그 sha가 `refs/heads/main`의 조상일 때 `git update-ref -d refs/heads/<브랜치> <sha>`로 지운다. 그 사이 브랜치가 움직였으면 이 명령이 실패하고 브랜치가 남는다. 적용하는 청소 두 개가 섞이지 않도록 공통 git 디렉터리에 `worktrees-prune.lock`을 만들고 끝나면 지운다. 30분이 지난 잠금 파일은 넘겨받는다.
4. **쉰 시간.** 다음 가운데 가장 최근 시각부터 잰다. 브랜치 끝 커밋 시각, 워크트리의 `.git` 파일 수정 시각(만든 시각의 하한), `logs/HEAD` 수정 시각, `git status`가 보여 주는 파일의 수정 시각. `logs/HEAD`가 없거나 읽히지 않으면 활동 중으로 본다. 인덱스 파일의 수정 시각은 쓰지 않는다. `git status`만 돌려도 바뀌기 때문이다. 기본값은 72시간이다.
5. **커밋 안 된 작업은 `refs/wip` 아래에 남긴 뒤에만 지운다.** `prune --snapshot`은 사람이나 디스패처만 돌린다. 쉬고 있는 워크트리 가운데 더럽거나 main에 들어가지 않은 것도 다룬다.
   - 더러운 워크트리는 임시 인덱스(`GIT_INDEX_FILE`)에 `read-tree HEAD`, `add -A`, `write-tree`, `commit-tree`를 해서 워크트리의 HEAD를 부모로 하는 커밋을 만든다. 워크트리의 인덱스와 브랜치는 건드리지 않는다.
   - 스냅샷은 작업 파일의 상태를 담는다. 스테이징한 뒤 다시 고친 파일은 디스크에 있는 내용으로 남고, 스테이징했던 중간 내용은 남지 않는다. 인덱스 트리를 따로 남기지 않는 쪽이 더 단순해서 이렇게 정했다.
   - 같은 임시 인덱스로 두 가지를 확인한다. `git diff --stat <커밋>`이 비어 있다. `git status --porcelain --untracked-files=all`에 `??`와 작업 트리 쪽 변경이 없다. 둘 다 맞을 때만 ref를 만들고 `git worktree remove --force`를 한다.
   - 임시 인덱스에 모드 160000 항목이 있으면(추적되지 않은 중첩 git 저장소) 스냅샷을 거절하고 워크트리를 남긴다. 포인터만 저장되고 그 저장소의 역사는 사라지기 때문이다.
   - HEAD가 분리돼 있고 main의 조상이 아닌 워크트리는 깨끗해도 HEAD를 같은 이름 공간의 ref로 남긴 뒤 지운다.
   - ref 이름은 `refs/wip/<YYYY-MM-DD>/<워크트리 이름>`이다. 같은 이름이 있으면 `-2`, `-3`을 붙인다. 태그가 아닌 이유는 이 저장소가 공개 저장소이고 `git push --tags`가 커밋 안 된 내용을 내보내기 때문이다. `refs/wip`는 기본 push 대상이 아니다.
   - 목록은 `git for-each-ref refs/wip`다. 되살릴 때는 `git worktree add <경로> <ref>` 또는 작업 트리에서 `git checkout <ref> -- .`를 쓴다.
   - main에 들어가지 않은 브랜치는 지우지 않고 워크트리만 지운다.
6. **캐시 목록.** gitignore 파일이 다음 디렉터리 안에만 있으면 캐시로 본다. 판정은 디렉터리 이름으로 한다.
   - 어느 깊이에서나: `__pycache__`, `.pytest_cache`, `node_modules`, `.ruff_cache`, `.mypy_cache`, `.gradle`, `.kotlin`, `.cxx`, `.venv`, `graphify-out`, `*.egg-info`.
   - `build`, `install`, `log`, `dist`는 워크트리 루트에 있을 때, 또는 생성물임을 증명하는 표시가 옆에 있을 때만 캐시다. colcon은 같은 층에 `build/`, `install/`, `log/`가 모두 있고 그 가운데 하나에 `COLCON_IGNORE`가 있거나 `install/setup.*`가 있는 경우다. gradle은 그 디렉터리의 부모에 `build.gradle*`가 있는 경우다. 그 밖의 위치(예: `data/log/run.bag`)는 "holds ignored data"로 남는다.
   - `.omc/`는 캐시가 아니다. 에이전트 상태다.
   - git이 내용 전체가 무시된 디렉터리를 한 줄로 보고하면 도구가 그 안을 걸어서 캐시 밖 파일이 하나라도 있는지 본다.
7. **지우다 실패한 디렉터리.** `git worktree remove`가 실패했는데 git 목록에서는 빠지고 디렉터리가 남으면(Windows의 열린 핸들, 긴 경로) `ORPHAN <경로>`를 찍고 브랜치를 남긴다. exit 상태는 바꾸지 않는다. `status`는 `.worktrees/` 아래의 등록되지 않은 디렉터리를 `orphan`으로 보여 주고, 상한 계산에 넣는다. 손실 없는 청소는 비어 있는 orphan 디렉터리만 지운다.
8. **상한은 40개이고 비상구가 있다.** `new`는 `.worktrees/` 아래가 40개 이상이면 exit 1로 거절한다. 가장 오래 쉰 열 개와 판정을 찍고, `python tools/worktrees.py status`와 손실 없는 `prune --apply`를 알려 준다. `--snapshot`은 사람이나 디스패처가 돌린다고 적는다. `--force-over-cap "<이유>"`를 주면 상한을 넘겨 만들고 이유를 찍고 `branch.<브랜치>.description`에 남긴다. 빈 이유는 거절한다. 사고 대응 중에 막히는 것이 워크트리 하나가 더 생기는 것보다 나쁘기 때문이다.
9. **lint는 경고만 한다.** `python tools/harness/rosy_harness.py lint`는 워크트리가 상한 이상이거나, main에 들어갔고 72시간 넘게 쉰 워크트리가 있으면 `WARN`을 찍는다. 문구는 8항과 같은 안내다. 이 검사는 워크트리마다 `git status`를 돌리지 않는다. CI와 `.worktrees/`가 없는 체크아웃에서는 아무것도 찍지 않고, 어떤 예외가 나도 lint를 실패시키지 않는다.
10. **절차 문서.** `AGENTS.md` 「같이 하는 깃」 1번과 6번, `docs/reference/shared-checkout.md`의 같은 절, `rosy-land-on-main` 스킬을 이 도구로 바꾼다. 실험실 PC 우산 문서는 저장소 밖이라 사람이 같이 고친다.

### 일부러 하지 않는 것

- 맨손 `git worktree add`를 막지 못한다. git에는 워크트리 생성 훅이 없다. 관문을 거치지 않은 워크트리도 `status`, 청소, lint 경고의 대상은 된다.
- 원격 브랜치를 정리하지 않는다.
- main에 들어가지 않은 브랜치를 지우지 않는다. 로컬 브랜치 수는 이 결정만으로는 main에 들어간 만큼만 준다.
- 이 결정이 Proposed인 동안 자동으로 지우는 경로가 없다. 지우는 것은 누군가 `prune --apply`나 `--prune`을 친 때뿐이다.
- 소유자 표시로 청소를 막거나 허락하지 않는다.
- 설정 파일이 없다. 상한과 기본 쉰 시간은 `tools/worktrees.py`의 상수다.

### D-172와의 관계

D-172는 구조 개편 이전의 미병합 브랜치를 `archive/<YYYY-MM-DD>/<branch>` 태그로 보존하고 그 태그를 지우지 않는다고 정했다. 그 태그는 바뀌지 않는다. 이 결정의 스냅샷은 태그가 아니라 `refs/wip/<YYYY-MM-DD>/<워크트리 이름>`이다. 가리키는 것도 다르다. D-172 태그는 브랜치 끝 커밋이고, `refs/wip` ref는 도구가 만든 커밋 하나(부모가 그 워크트리의 HEAD이고 커밋되지 않았던 내용을 담는다)이거나 분리된 HEAD 자체다. 이 ref도 지우지 않는다. 그 내용을 main에 들일 때는 D-172와 같이 새 주제 브랜치에서 다시 만들고 독립 리뷰를 거친다. `refs/wip` ref를 그대로 머지하지 않는다.

### Consequences

- 착지한 워크트리는 누군가 `prune --apply`를 돌릴 때까지 남는다. `land.py`가 끝날 때 `main` 체크아웃에서 칠 `git worktree remove`와 `git branch -d` 두 줄을 찍는다.
- `.omc/`가 있는 워크트리는 손실 없는 청소로 지워지지 않는다. 이 저장소의 에이전트 워크트리 대부분이 여기에 해당할 수 있다. 그런 워크트리는 `status`에 "holds ignored data"로 남고 사람이 확인한다.
- 캐시 목록에 없는 gitignore 파일(`.vscode/`, `local.properties`)도 같은 방식으로 남는다.
- `refs/wip`는 clone과 기본 push에 실려 가지 않는다. 이 PC에만 있는 보존이다.
- 알림은 `new`와 `land`에 `git worktree list`와 `for-each-ref` 두 번, 그리고 쉬고 있고 main에 들어간 워크트리마다 `git status` 한 번을 더한다.
- 상한 40은 측정으로 정한 값이 아니다. 동시에 일하는 세션 수보다 넉넉하게 잡은 시작값이고 상수 하나를 바꿔 조정한다.

### Validation

- `test/test_worktrees_tool.py`: 임시 저장소에서 실제 git으로 시험한다. 손실 없는 청소와 브랜치 삭제, `--snapshot`의 `refs/wip` 보존과 내용, 캐시 규칙(`.omc`, `data/log`, 루트와 colcon 옆의 `log`), 잠금, 쉰 시간과 `logs/HEAD` 없는 경우, 실행 중인 워크트리 보호, 훑은 뒤 생긴 커밋, 움직인 브랜치, 실패한 삭제와 orphan, 중첩 저장소, 분리된 HEAD, 진행 중인 rebase, 청소 잠금, `new`의 상한·비상구·거절·소유자 기록, `land.py`와 `new`가 `--prune` 없이는 지우지 않는 것을 본다.
- 이 도구의 `prune`과 `new`는 실제 저장소에 대해 아직 한 번도 실행하지 않았다. 다른 세션이 일하는 중이라 임시 저장소에서만 시험했다. Windows에서의 삭제 실패는 git 호출을 바꿔 흉내 냈다.
- `python tools/harness/rosy_harness.py lint`가 오류 0이다.
