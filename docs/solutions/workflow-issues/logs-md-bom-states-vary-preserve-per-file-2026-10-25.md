---
module: docs
tags: [logs-md, bom, append-only, landing]
problem_type: workflow
---

# 모듈 logs.md 의 BOM 상태가 제각각이라 append 만 해도 append-only 검사가 깨진다

2026-10-25, D-865 P2a 착지에서 발견.

## 증상

`operations/fleet/logs.md`에 항목을 추가했을 뿐인데 착지 병합이
`a side changed existing lines, not only appended`로 거부됐다. diff는 9추가/1삭제 —
첫 줄 `# fleet logs`가 `﻿# fleet logs`(BOM 추가)로 바뀌어 있었다.

## 원인

모듈별 logs.md의 BOM 상태가 파일마다 다르다. `docs/logs.md`는 UTF-8 BOM + CRLF,
`operations/fleet/logs.md`는 **BOM 없음**이다. PowerShell의
`[IO.File]::WriteAllText(..., UTF8Encoding($true))`로 일괄 append하면 BOM 없는
파일에 BOM이 생기고, land_logs.py의 append-only 검사는 이를 기존 행 수정으로
본다. 오류 메시지에는 BOM이라는 단어가 없어 원인이 바로 보이지 않는다.

또한 Windows PowerShell의 `Get-Content`는 BOM 없는 UTF-8을 ANSI(cp949)로 읽어
한글을 파괴할 수 있다. 실제로 BOM 없는 파일을 Get-Content→WriteAllLines로
다시 쓰면 내용 전체가 깨진다.

## 해결

- append 전에 대상 파일의 첫 바이트를 읽고 **BOM 유무를 그대로 보존**한다
  (BOM 있으면 `UTF8Encoding($true)`, 없으면 `$false)`).
- 한글이 섞인 파일을 다룰 때는 `Get-Content`/`Set-Content` 대신
  `[IO.File]::ReadAllText/WriteAllText` + 명시적 UTF-8 인코딩을 쓴다.
- 이미 망가진 경우: `git show <side>:<path>`로 양쪽 본문을 바이트 그대로 꺼내
  합집합(날짜순)으로 재구성하고, 커밋된 항목은 원문 그대로(재타이핑 금지) 옮긴다.

## 검증

- `git diff --numstat <merge-base> HEAD -- <logs.md>`가 추가만(삭제 0)인지 확인.
- `python tools/harness/rosy_harness.py lint` 0 errors.

## 다음에 적용할 조건

모듈 logs.md에 항목을 붙이는 도구·세션은 모두 이 규칙을 따른다. 근본 대책은
BOM 상태를 통일하는 변경이지만 그 전까지 append 도구가 파일별 상태를 보존한다.
