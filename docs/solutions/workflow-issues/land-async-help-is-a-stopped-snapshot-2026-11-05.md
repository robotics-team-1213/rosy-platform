---
title: "land_async의 --help도 snapshot을 만들므로 종료 코드만으로 착지를 판정하지 않는다"
date: "2026-11-05"
category: workflow-issues
module: tools/land_async.py
problem_type: workflow_issue
component: development_workflow
severity: low
applies_when:
  - "비동기 착지 도구의 옵션을 조회하거나 종료 코드를 해석할 때"
tags: [git, land-async, help, ancestry, stopped]
---

# 비동기 착지의 도움말과 실제 main 반영을 구분한다

## 관측

2026-11-05 옵션 조회를 위해 `python tools/land_async.py --help`를 실행했지만 새 snapshot과 비동기 표가 만들어졌다. 자식 `land.py`는 도움말을 출력하고0으로 종료했으나 실제 main에는 반영하지 않았다. supervisor는 숨은 worktree를 보존하고 `land.py exit 0`이라는 `.stopped` 기록을 남겼다.

이 관측 당시 snapshot 소스 commit은 `7883232cb56fffae24a3b0504a6c7366c2376ffd`였다. 이는 당시 로컬 미게시 식별자이며 공개 PR 병합 사실을 주장하지 않는다. main ancestry 검사 결과는1이었다. 이후 정식 검증·착지의 결과와 이 도움말 실행을 섞지 않는다.

## 원인과 안전한 사용

`tools/land_async.py`의 `main()`은 `orphans`, `--supervise`, `resume`만 별도 처리하고 나머지 인수를 `start()`에 전달한다. 따라서 이 wrapper의 `--help`는 읽기 전용 조회가 아니다. 옵션 확인은 먼저 이 파일의 모듈 설명과 `main()` 또는 [정본 절차](../../reference/shared-checkout.md)를 읽는다. 실제 착지에는 정본의 명시적인 시험 옵션을 사용한다.

같은 파일의 `_supervise()`는 자식 종료 코드와 별개로 snapshot이 main의 조상인지 확인한다. 조상이 아니면 종료0이어도 `.stopped`를 남긴다. 따라서 성공 판정은 출력의 `queued`나 종료0이 아니라 실제 main 반영, 착지 사건과 해당 검증 근거를 확인한다.

```text
git merge-base --is-ancestor <snapshot-sha> main
```

이미 도움말로 생성한 표가 있다면 그 표의 로그·`.stopped`와 프로세스 상태를 확인한다. 실행 중인 다른 표를 멈추거나 숨은 디렉터리를 강제 삭제하지 않는다. 이 사례에서는 표가 스스로 종료됐고 원래 소유 worktree도 깨끗했으므로 다음 정식 제출을 준비했다. 종료0을 시험 또는 착지 PASS로 기록하지 않았다.

## 적용 범위

이 기록은 CLI 인수를 전달하는 비동기 wrapper의 동작에 관한 것이다. [게시 절차](../../reference/pr-pipeline.md)의 FULL·독립 리뷰·CI·main ancestry 조건은 그대로이며, 일반 argparse CLI의 도움말까지 같은 동작이라고 일반화하지 않는다. wrapper가 도움말을 별도 처리하도록 바뀌면 그 소스와 회귀를 확인한 뒤 이 기록을 갱신한다.
