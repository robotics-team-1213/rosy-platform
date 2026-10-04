---
module: docs
tags: [workflow, encoding, powershell, journals]
problem_type: workflow_issue
---

# PowerShell 한글 저널 append가 UTF-8을 망가뜨린다 (2026-10-04, 4회)

## 문제

이 Windows 체크아웃에서 PowerShell로 한글이 섞인 저널 행을 파일에 더할 때 — `Add-Content`, `Set-Content`, `cmd /c "... >> file"`, 그리고 **파이프로 파이썬에 소스를 넘길 때(`@'...'@ | python -`)까지** — 텍스트가 콘솔 코드페이지로 인코딩되어 UTF-8 파일에 물음표(`?`) 런으로 기록된다. 2026-10-04 하루에 4회 발생했다(`docs/logs.md` 1회, `operations/fleet/logs.md` 2회, `deploy/logs.md` 1회 — 마지막은 다른 세션). `?`로 변환된 한글은 **복구 불능**이다: lint(`rosy_harness.py lint`의 mojibake 검사)가 `suspicious encoding ('??' runs)`으로 잡는다.

## 증상

- `rosy_harness.py lint`: `suspicious encoding ('??' runs) at line N…` + `malformed heading '## YYYY-MM-DD ? uncommitted ? …'`
- 깨진 행의 한글이 전부 `?`/`??` 런으로 바뀌어 있다.

## 안전한 방법 (이 체크아웃에서 한글을 쓰는 경우)

1. **에디터 도구의 파일 편집**(찾기·바꾸기) — 파일을 UTF-8으로 읽고 쓴다. 이 문서를 만든 세션의 기본 수단.
2. **파이썬 스크립트를 파일로 두고 실행** — 스크립트 소스가 파이프를 거치지 않는다:
   `python tools/append_journal.py` (파일 안에서 UTF-8 문자열을 정의).
3. 파이썬 `-c`는 ASCII만 쓸 때만 허용.

## 절대 하지 않을 것

- `Add-Content`/`Set-Content`/`>>` 리다이렉션으로 한글 쓰기 — 인자가 올바른 인코딩으로 보여도 파이프/리다이렉션 경로에서 무조건 콘솔 코드페이지를 지난다.
- 깨진 행을 추측으로 복원 — `?`는 정보가 소실된 것이다. 작성 세션이 원문에서 다시 써야 한다.

## 관측된 원인 표면

| 경로 | 결과 |
|---|---|
| `Add-Content -Path docs\logs.md -Value '…한글…'` | 전체 행 mojibake |
| `cmd /c "python … > file"` (스크립트 파일) | 무관 — 파일 리다이렉션은 파이썬 stdout 인코딩을 따른다; 파이썬이 UTF-8로 쓰면 무결 |
| `@'…한글…'@ | python -` | heredoc 소스의 한글이 깨짐 |
| 편집 도구(파일 경유) | 무결 |
