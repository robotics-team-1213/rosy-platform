---
module: tools
date: 2026-10-25
last_updated: 2026-11-02
problem_type: workflow_issue
component: development_workflow
severity: high
tags: ["worktree", "windows", "shared-checkout", "prune", "land", "land-async"]
applies_when: "land.py·land_async.py·worktrees.py prune을 거친 워크트리 폴더에서 git 명령(특히 branch 전환)을 다시 실행할 때"
---

# 지워진 워크트리의 빈 폴더에서 실행한 git은 공유 main에서 동작한다

## 증상

`tools/land.py`가 착지를 마치고 그 워크트리를 정리했다. 같은 세션은 그 폴더 경로에서 다음 동기화를 이어 갔다(`git merge --ff-only main`, `git merge origin/main`). `git status`에 `../../deploy/logs.md` 같은 상위 경로가 보였고, 공유 `main` 체크아웃에 충돌 파일 15개가 생겼다. `git merge --abort`로 몇 분 안에 되돌렸다.

## 원인

Windows에서는 어느 프로세스든 그 폴더를 현재 위치로 쓰고 있으면 `git worktree remove`가 등록만 지우고 폴더는 지우지 못한다. 남은 빈 폴더에는 `.git` 파일이 없다. 그래서 git은 위로 올라가 `.worktrees/`를 품은 공유 체크아웃을 저장소로 잡는다. 셸의 현재 위치는 그대로라, 명령은 평소처럼 성공한다.

## 해결

- 구조 수정 `0210c973b8`(로컬 main `5743aef1ee`, 담당 robot-0d): 정리 뒤 폴더가 남으면 비어 있을 때 지운다. 지울 수 없으면 존재하지 않는 경로를 가리키는 `.git` 묘비 파일을 써서, 그 안의 git이 128로 끝나고 main에 닿지 않게 한다. 다음 prune은 묘비 폴더를 바로 지우고, `worktrees.py new`는 같은 이름의 묘비를 치우거나 프로세스가 잡고 있으면 거절한다. 실제 git 하위 프로세스로 시험한다.
- 사고 복구: 공유 main에서 `git rev-parse -q --verify MERGE_HEAD`로 진행 중인 병합을 확인하고 `git merge --abort`로 되돌렸다. 병합 전 HEAD와 같고 추적 파일 변경이 없음을 확인했다. stash·reset은 쓰지 않았다(남의 미커밋 보호).

## 재발 (2026-10-31): 파일이 남은 폴더, 묘비 없음

`land_async.py`가 "this worktree is free now"라고 알린 워크트리(`cell-catalog`)를 다음 브랜치에 여러 번 다시 썼다. 어느 시점에 그 폴더의 `.git` 파일이 사라졌다. 폴더에는 작업 파일이 그대로 남았고 묘비 파일도 없었다. 그 상태에서 `git switch -c feat/omx-devices-scan main`을 실행하자 **공유 main 체크아웃이 새 브랜치로 바뀌었다**. `git add`가 `.worktrees` 무시 경고를 낸 뒤에야 알아챘다.

- 복구: 공유 체크아웃의 `git reflog`에서 직전이 `main`인지 확인하고 `git switch main`. 그 사이 커밋은 없었으므로 빈 브랜치를 지웠다(약 2분).
- 폴더는 지우지 않고 `Rosy/artifacts/worktree-backups/`로 옮겼다. `worktrees.py prune`은 이 폴더를 `orphan`으로만 표시하고 남겼다.
- `.git`이 사라진 경위는 확인하지 못했다. 위 구조 수정(빈 폴더 삭제·묘비)은 이 경로를 막지 못했다. 등록이 지워졌는데 파일이 남은 폴더에서는 git이 여전히 상위 공유 체크아웃을 잡는다.

## 재발과 복구 (2026-11-02): 상대 경로 preview와 남은 감시 프로세스

등록을 제거한 install-seat 폴더가 WinError 32로 남았다. 프로세스 명령행에 워크트리
이름이 없어 단순 경로 검색으로는 원인을 찾지 못했다. 읽기 전용 현재 디렉터리 점검에서
부모가 사라진 sample UI 서버 43개가 같은 폴더를 잡고 있었다. 명령은 모두
`python -X utf8 applications/fleet/dev/serve.py --mode sample --scenario normal --port 4173`였고,
한 시간 이상 지난 프로세스였다. 상대 경로 명령도 시작한 폴더의 핸들을 계속 보유한다.

각 PID의 명령·생성 시각·부모 부재·sample 모드를 다시 확인한 뒤 그 43개만 종료했다.
오래된 로그 감시 shell의 자식도 정리했다. 반면 release-corrector 폴더의 Isaac batch
coordinator는 부모가 없어도 실제 작업과 소유 세션의 감시가 남아 있어 보존했다.
부모 부재만으로 모든 Python이나 shell을 종료하면 안 된다.

ignored `.impeccable/`는 먼저 우산의 `artifacts/worktree-backups/` 아래 zip으로 보관하고,
다시 열어 모든 파일의 SHA256을 원본과 비교했다. 등록 제거 뒤 남은 폴더에는 묘비를
유지했다. 검증된 고아 프로세스 종료 후 공식 prune이 install-seat·fleetreg·publish-full2
세 폴더를 실제로 제거했다. 파일 보존·프로세스 종료·등록 제거·폴더 제거는 별도 확인이다.

이전 `http_host.make_server`는 Windows에서 같은 포트의 두 bind를 허용하는 것을
실제 socket으로 재현했다. 수정은 Windows의 exclusive bind를 켜고 address reuse를
끄며, 모든 플랫폼에서 port reuse를 끈다. 원격 관련 시험 15개가 통과했고, Windows에서
exclusive 값 1·두 번째 bind 오류 10048·닫은 뒤 재bind를 확인했다. 이 guard는 같은 포트에
preview가 쌓이는 것을 막는다. 단일 백그라운드 프로세스의 자동 종료 기능은 아니므로,
호출자가 PID와 자식 수명을 관리하고 워크트리 회수 전에 종료해야 한다.

## 다음에 적용할 조건

- 착지한 워크트리에서 다음 작업을 이어 하지 않는다. 새 일은 `worktrees.py new`로 새 워크트리에서 시작한다.
- 같은 경로를 다시 쓰기 전에 `git rev-parse --show-toplevel`이 그 워크트리 경로인지 먼저 확인한다. 상위 체크아웃이 나오면 멈춘다.
- `land_async.py`가 "free now"라고 한 워크트리를 다시 쓸 때도 같다. branch 전환·reset·commit 직전마다 위 확인을 하고, 공유 체크아웃은 `git -C <공유 체크아웃> branch --show-current`가 `main`인지 함께 본다.
- 백그라운드 실행을 멈출 때(`TaskStop`) 자식 프로세스가 남아 폴더를 잡을 수 있다. 그 폴더는 다음 prune이 묘비로 막는다.
