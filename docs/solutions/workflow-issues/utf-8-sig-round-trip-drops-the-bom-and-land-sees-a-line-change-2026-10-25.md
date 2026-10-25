---
title: utf-8-sig로 읽고 utf-8로 쓰면 BOM이 사라지고 land가 기존 줄 변경으로 오판한다
date: 2026-10-25
category: workflow-issues
module: tools/land_merge.py, docs/logs.md (추가 전용 로그의 손병합)
problem_type: workflow_issue
component: development_workflow
severity: medium
applies_when:
  - "충돌난 추가 전용 로그(docs/logs.md, ADR Log 등)를 스크립트나 편집기로 고칠 때"
  - "손병합 뒤 lint는 0 errors인데 land 회차가 병합 단계에서 멈출 때"
tags: [bom, utf-8-sig, hand-merge, append-only, land-py, docs-logs]
---

# utf-8-sig로 읽고 utf-8로 쓰면 BOM이 사라지고 land가 기존 줄 변경으로 오판한다

## Context

2026-10-25 동기화 브랜치(`fix/sync-origin-20261025`)에서 origin/main PR #201-#207을 머지하며 추가 전용
로그 5파일 충돌을 Python 한 번 스크립트로 풀었다. 스크립트는 `open(..., encoding="utf-8-sig")`로 읽고
`open(..., "w", encoding="utf-8")`으로 썼다. `rosy_harness.py lint`는 0 errors였다. 대기열에서 앞선
착지들이 끝난 뒤 돌아온 land 회차는 1라운드 병합에서 바로 멈췄다:

```
[land] STOP: merge aborted; resolve by hand in the worktree:
  docs/logs.md: a side changed existing lines, not only appended
```

## Root cause

`utf-8-sig` 디코딩은 BOM을 읽으면서 버리고, `utf-8` 인코딩은 BOM을 다시 붙이지 않는다.
`docs/logs.md`는 UTF-8 BOM(`\xef\xbb\xbf`)을 가진 파일이라 1줄이 `\ufeff# docs logs`에서
`# docs logs`로 바뀌었고, `tools/land_merge.py`의 추가 전용 판정기("a side changed existing lines,
not only appended")는 1줄부터 비교하므로 순수 추가가 아니라고 본다. `rosy_harness.py lint`는 날짜 순서와
항목 형식을 검사할 뿐 BOM을 검사하지 않아서, 실패는 lint가 아니라 대기열 뒤의 land 병합에서
한 회차 뒤에야 드러났다(약 40분 손실).

## Guidance

- 추가 전용 로그를 손병합할 때는 바이트로 읽고 쓴다. `rb`로 읽어 BOM(`raw[:3] == b"\xef\xbb\xbf"`)과
  EOL(LF/CRLF)을 기록해 두고, 같은 접두로 되돌려 쓴다.
- 커밋 전 두 가지 확인: (1) `git show HEAD:<file>`의 첫 3바이트와 작업 파일의 첫 3바이트가 같은지,
  (2) base 대비 3-way diff의 `@@` 헤더가 파일 끝에만 있는지(순수 추가). 이번 건은 첫 확인에서
  `@@ -1,4 +1,4 @@`로 바로 드러난다.
- BOM을 가진 파일: `docs/logs.md`, `docs/reference/ROSY ADR Log.md`(2026-10-25 기준 검증).
  모듈 `logs.md`·`index.md`는 없지만 파일마다 확인한다. lint는 BOM을 보지 않는다.
- 이 교훈의 반영은 아직 착지 대기 중인 동기화 브랜치에 있다(커밋 예정, 미병합).

## Applicability

이 저장소의 BOM 있는 추적 텍스트(docs/logs.md, ADR Log)를 스크립트·편집기로 다시 쓰는 모든 손병합.
Windows에서는 편집기·도구마다 BOM·EOL 기본값이 달라 위험이 크다.
