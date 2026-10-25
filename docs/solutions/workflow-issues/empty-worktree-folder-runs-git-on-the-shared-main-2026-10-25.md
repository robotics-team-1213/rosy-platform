---
module: tools
date: 2026-10-25
problem_type: workflow_issue
component: development_workflow
severity: high
tags: ["worktree", "windows", "shared-checkout", "prune", "land"]
applies_when: "land.py 또는 worktrees.py prune이 워크트리를 지운 뒤 그 폴더에서 git 명령을 다시 실행할 때"
---

# 지워진 워크트리의 빈 폴더에서 실행한 git은 공유 main에서 동작한다

## 증상

`tools/land.py`가 착지를 마치고 그 워크트리를 정리했다. 같은 세션은 그 폴더 경로에서 다음 동기화를 이어 갔다(`git merge --ff-only main`, `git merge origin/main`). `git status`에 `../../deploy/logs.md` 같은 상위 경로가 보였고, 공유 `main` 체크아웃에 충돌 파일 15개가 생겼다. `git merge --abort`로 몇 분 안에 되돌렸다.

## 원인

Windows에서는 어느 프로세스든 그 폴더를 현재 위치로 쓰고 있으면 `git worktree remove`가 등록만 지우고 폴더는 지우지 못한다. 남은 빈 폴더에는 `.git` 파일이 없다. 그래서 git은 위로 올라가 `.worktrees/`를 품은 공유 체크아웃을 저장소로 잡는다. 셸의 현재 위치는 그대로라, 명령은 평소처럼 성공한다.

## 해결

- 구조 수정 `0210c973b8`(로컬 main `5743aef1ee`, 담당 robot-0d): 정리 뒤 폴더가 남으면 비어 있을 때 지운다. 지울 수 없으면 존재하지 않는 경로를 가리키는 `.git` 묘비 파일을 써서, 그 안의 git이 128로 끝나고 main에 닿지 않게 한다. 다음 prune은 묘비 폴더를 바로 지우고, `worktrees.py new`는 같은 이름의 묘비를 치우거나 프로세스가 잡고 있으면 거절한다. 실제 git 하위 프로세스로 시험한다.
- 사고 복구: 공유 main에서 `git rev-parse -q --verify MERGE_HEAD`로 진행 중인 병합을 확인하고 `git merge --abort`로 되돌렸다. 병합 전 HEAD와 같고 추적 파일 변경이 없음을 확인했다. stash·reset은 쓰지 않았다(남의 미커밋 보호).

## 다음에 적용할 조건

- 착지한 워크트리에서 다음 작업을 이어 하지 않는다. 새 일은 `worktrees.py new`로 새 워크트리에서 시작한다.
- 같은 경로를 다시 쓰기 전에 `git rev-parse --show-toplevel`이 그 워크트리 경로인지 먼저 확인한다. 상위 체크아웃이 나오면 멈춘다.
- 백그라운드 실행을 멈출 때(`TaskStop`) 자식 프로세스가 남아 폴더를 잡을 수 있다. 그 폴더는 다음 prune이 묘비로 막는다.
