---
title: "Determine the tested GitHub pull request merge commit before retrying CI"
date: 2026-11-25
module: GitHub Actions pull request CI and D-1061 records lint
category: workflow-issues
problem_type: workflow_issue
component: development_workflow
severity: medium
tags: [github-actions, pull-request, merge-ref, records-lint]
applies_when: "A PR repeats a main-branch failure after the upstream repair, or records lint reports a generated file the PR never changed"
---

# CI를 다시 실행하기 전에 실제 검사 커밋을 확인한다

GitHub Actions 작업의 Checkout 로그에서 SHA를 확인한다. PR 화면의 head
SHA, 이벤트의 base SHA, GitHub가 만든 시험용 병합 커밋은 서로 다를 수 있다.
시험 커밋의 첫 부모는 그 검사에 포함된 기준 브랜치의 커밋이다.

```powershell
git fetch origin refs/pull/735/merge
git show --no-patch --format='%H %P' FETCH_HEAD
git diff --name-status 'FETCH_HEAD^1' FETCH_HEAD -- deploy/logs.md
```

현재 PR 병합 참조는 실행이 시작된 뒤 갱신될 수 있다. 로그의 SHA와 다르면
해당 실행을 진단할 때 로그의 SHA를 사용한다.

## Wave 4에서 확인한 두 경우

- D-371 수정 #768이 병합된 뒤 #735를 검토 준비 상태로 전환해도 CI의
  체크아웃에는 아직 수정이 빠져 있었다. 소스 변경 없이 빈 커밋을
  기존 PR 제출 경로로 푸시하자 synchronize 이벤트가 새 시험 커밋을
  만들었다. 새 체크아웃에 #768이 포함됐고 D-371 검사가
  통과했다. [이전 CI](https://github.com/robotics-team-1213/rosy-platform/actions/runs/45533284559) · [새 D-371 검사](https://github.com/robotics-team-1213/rosy-platform/actions/runs/45535511561/job/138941358489)
- 새 시험 커밋의 첫 부모는 `7d5be326fe`였다. 기록 검사는 이벤트의
  `c855750732`를 받았다. 같은 체크아웃에서 기록 규칙을 실행하니 이벤트
  SHA로는 기록 봇의 `deploy/logs.md` 변경이 오류가 됐다. 첫 부모로는
  오류가 사라졌다. #775는 `pull_request` 병합 참조에서 체크아웃한
  `HEAD`가 실행의 `GITHUB_SHA`와 일치하고 부모 둘을 확인하면 기록
  검사에 첫 부모를 사용한다. 원격 회귀 시험에서 PR이 직접 편집한
  버전 행을 계속 거부하는 것도 확인했다.
  [실패한 기록 검사](https://github.com/robotics-team-1213/rosy-platform/actions/runs/45535511561/job/138941358522) · [#775](https://github.com/robotics-team-1213/rosy-platform/pull/775)

필요한 upstream 수정이 시험 커밋에 빠져 있을 때만 새 PR 이벤트로
검사를 갱신한다. 실행 로그에서 새 SHA와 첫 부모를 확인한 뒤 결과를
판단한다. 기록 검사 오류가 남으면 해당 파일의 첫 부모 대비 diff를
확인하고 실제 PR 편집은 조각 파일로 옮긴다.
