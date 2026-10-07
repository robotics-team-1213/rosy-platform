# 같이 하는 깃 — 공유 체크아웃 착수 순서

- **대상:** 실험실 PC에서 `main` 체크아웃 하나를 여러 AI 세션과 같이 쓰는 사람·에이전트
- **팀원 개인 클론이라면** 이 문서 대신 [팀 가이드](team-guide.md)를 따른다.
- **갱신:** 2026-10-06 — README에서 옮김. 명령 전문은 [AGENTS.md](../../AGENTS.md) 「같이 하는 깃」.

## 같이 하는 깃

여러 세션이 이 저장소의 `main` 체크아웃 하나와 git 인덱스 하나를 같이 쓴다.
GitHub에 보이는 이 절이 착수 순서의 공개 기준이다. 같은 규칙의 명령 전문은
`AGENTS.md`의 「같이 하는 깃」에 적는다. 문구를 바꿀 때는 두 절을 한 커밋에서
같이 고친다. 실험실 PC의 우산 문서 `F:\Dev\Control\Robot\Rosy\Agents.md`도
같은 절차를 적는다. 명령 카드는
[`.claude/skills/rosy-land-on-main/SKILL.md`](../../.claude/skills/rosy-land-on-main/SKILL.md)다.
브랜치 이름과, 남의 미커밋을 지우지 않는 이유는
[D-372](../adr/D-372-topic-branch-names-and-shared-checkout-wip.md)다.

제품 파일을 고치기 전에 1번과 2번이 끝나 있어야 한다. 끝난 기준은 `git worktree list`에
자신의 `.worktrees/<짧은이름>`이 있고, 그 디렉터리의 브랜치가 `main`이 아닌 것이다.

1. **작업 위치를 만든다.** 저장소 루트에서 `git status --short --branch`와
   `git worktree list`를 본 다음
   `git worktree add --relative-paths .worktrees/<짧은이름> -b <type>/<topic> main`
   을 실행한다. `<type>`은 내용과 맞는 `feat`, `fix`, `refactor`, `docs`, `uiux`
   가운데 하나다(D-372). worktree는 이 저장소의 `.worktrees/`에만 둔다. 공유
   `main` 체크아웃은 `git merge --ff-only`로 착지할 때만 쓴다. 거기에 커밋되지
   않은 변경을 남기면 다른 세션의 fast-forward가 거절된다. 스크래치, 로그,
   pytest 출력은 저장소 밖에 둔다. 실험실 PC에서는 `X:\DevTemp`다.
2. **자기 경로만 스테이징한다.** `git add`에는 이번 작업에서 자신이 만든 경로만
   적는다. `git add -A`, `git add .`, 디렉터리 단위 add는 쓰지 않는다. 인덱스
   하나가 모든 세션의 것이라 넓은 add 한 번이 다른 세션의 파일을 커밋에 넣는다.
   자신이 쓰지 않은 경로는 그대로 둔다. stash, revert, checkout, restore, reset,
   clean, amend, 삭제로 치우지 않는다. 루트의 추적되지 않은 `list.txt`는 로컬
   메모라 커밋하지 않는다. 머지나 체크아웃이 그 파일 때문에 거절되면 파일을
   그대로 두고 거절 문구를 사용자에게 알린다.
3. **계약을 읽고 고친다.** 제품 파일을 고치기 전에 [README 「핵심 계약」](../../README.md#핵심-계약)과
   `AGENTS.md`의 Working In This Directory를 읽는다. 외부 API, 모드, 프로토콜
   필드는 그 문서가 가리키는 SRS, API reference, ADR에 있는 것만 쓴다. 읽기가
   끝난 기준은 바꾸려는 경로의 모듈 `AGENTS.md` 또는 해당 ADR을 연 것이다.
4. **ADR 번호는 파일을 만들기 직전에 도구로 선점한다.** 다른 세션이 몇 분 사이에
   같은 번호를 가져간다. `python tools/harness/adr_reserve.py next "<주제>"`를
   돌리고 찍힌 번호를 쓴다. 도구가 로컬 ref `refs/adr/D-nnn`을 만들고, 같은 ref는
   한 세션만 만들 수 있다(D-510). 그 ADR이 브랜치와 같이 착지하지 않거나 충돌로
   못 쓰게 되면 `tools/harness/adr_gaps.txt`에 `D-nnn 이유` 한 줄을 넣는다.
   ADR 파일과 Log 행은 한 커밋이다. 자세한 내용은 `AGENTS.md`의 「같이 하는 깃」
   4번에 적혀 있다.
5. **테스트는 기존 실패와 비교한다.** 워크트리에서 관련 pytest 결과를 저장소
   밖의 `run.txt`에 남기고 `python test/known_failures.py`에 그 파일을 넘긴다.
   실험실 PC의 경로는 `X:\DevTemp\<이름>\run.txt`다. exit 1의 `NEW`는 그
   브랜치의 실패다. 고친 실패의 줄은 같은 커밋에서 `test/known_failures.txt`에서
   뺀다. 그 브랜치가 만든 실패를 그 파일에 넣지 않는다. 호스트 pytest 통과는
   장치, ARM64 이미지, 현장 수용을 대신하지 않는다.
6. **착지와 푸시는 사용자가 말한 뒤에만 한다.** 기본 방법은 워크트리에서
   `python tools/land.py --tests auto`다. 손으로 할 때 착지는 워크트리에서 `git merge main`을
   하고 관련 테스트를 다시 돌린 다음, `main` 체크아웃에서
   `git merge --ff-only <브랜치>`를 한다. `--ff-only`가 거절되면 그 문구를
   알리고, 다른 세션 파일을 치운 뒤 다시 시도하지 않는다. 푸시 순서는 `AGENTS.md`의
   D-427 4항이다. `git fetch` 하고 `origin/main` 위로 rebase 한 뒤
   `python tools/harness/rosy_harness.py generate`를 하고, pre-push 검사를
   통과한 다음에 push 한다. force-push는 하지 않는다. 로컬 `main`이
   `origin/main`보다 앞에 있으면 그 커밋의 CI 증거는 아직 없다.

착수 다음에 손댈 제품 규칙은 [README 「핵심 계약」](../../README.md#핵심-계약)이다.
