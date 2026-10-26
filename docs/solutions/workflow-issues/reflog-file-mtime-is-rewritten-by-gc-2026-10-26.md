---
module: tools
date: 2026-10-26
problem_type: workflow_issue
component: development_workflow
severity: medium
tags: ["worktree", "branch", "prune", "reflog", "gc"]
applies_when: "브랜치나 워크트리가 최근에 쓰였는지를 .git/logs 아래 파일의 수정 시각으로 판단하는 코드를 만들거나 고칠 때"
---

# reflog 파일의 수정 시각은 gc가 한꺼번에 바꾼다

## 증상

D-886이 착지한 뒤 `python tools/worktrees.py prune --apply`가 착지한 브랜치를 하나도 지우지 않았다(`deleted 0 merged branch(es)`). 착지 전 드라이런은 123개를 셌다. `.git/logs/refs/heads` 아래 파일 501개의 수정 시각이 모두 13:40 근처였고, 각 파일 마지막 항목의 시각은 전날이었다. 같은 시각 근처에 `packed-refs`와 새 pack 파일이 쓰여 자동 gc가 돈 흔적이 있었다.

## 원인

`git reflog expire --all`은 지울 항목이 없어도 모든 reflog 파일을 잠금 파일로 다시 쓴다. gc가 이 명령을 실행한다. 링크된 워크트리의 `.git/worktrees/<이름>/logs/HEAD`도 같이 다시 쓰인다. 항목의 내용과 시각은 그대로다. 브랜치 정리는 "1시간 안에 바뀐 reflog = 방금 만든 브랜치"로 보고 모두 남겼다. 워크트리 활동 판단(`logs/HEAD` 시각)도 쉬던 워크트리를 활동 중으로 읽었다. 둘 다 지우지 않는 쪽으로 틀려 손실은 없었지만, 정리가 멈췄다.

재현: 빈 저장소에서 브랜치와 워크트리를 만들고 두 reflog 파일의 시각을 과거로 바꾼 뒤 `git reflog expire --all`이나 `git gc`를 돌리면 두 파일 모두 현재 시각이 된다. 마지막 항목의 시각은 바뀌지 않는다.

## 해결

`tools/worktree_rules.py`의 `reflog_time()`은 reflog 마지막 항목의 시각 필드(`<old> <new> <이름> <메일> <unix> <tz>\t<메시지>`)를 읽는다. 브랜치 정리와 `tools/worktrees.py`의 워크트리 활동 판단이 이 함수를 쓴다. 회귀 시험은 `test/test_worktrees_tool.py`의 `test_gc_rewriting_logs_head_does_not_make_an_idle_worktree_active`와, 브랜치 정리 시험 안의 `os.utime` 단계다.

## 다음에 적용할 조건

- `.git/logs/**`·`packed-refs`·pack 파일의 수정 시각은 사람이나 세션의 활동 근거가 아니다. 시각이 필요하면 reflog 항목이나 커밋 시각을 읽는다.
- 정리 도구가 갑자기 "모두 활동 중"이나 "0개"를 보이면 먼저 `find .git/logs -newermt <시각>`으로 파일이 한꺼번에 다시 쓰였는지 본다.
- 작업 트리 파일과 워크트리의 `.git` 파일 시각은 gc가 건드리지 않으므로 계속 쓸 수 있다.
