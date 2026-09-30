---
title: PowerShell 리다이렉트가 한글을 물음표로 바꿔 커밋된다 — UTF-8 쓰기를 보장하는 도구로만 문서를 쓴다
date: 2026-09-29
category: workflow-issues
module: docs(ADR Log, 저널 — 모든 한글 거버넌스 문서)
problem_type: workflow
component: development_workflow
severity: medium
symptoms:
  - "ADR Log 행이 'Fleet? OMX ?? owner …'처럼 리터럴 ? 로 깨진 채 커밋(D-336, f12eaeb6)"
  - "D-140 표행도 같은 패턴으로 부식(2026-09-29 발견·복구)"
  - "깨진 행은 Read 검증을 통과한 나머지 행과 달리 복구 없이는 읽을 수 없다"
root_cause: environment
resolution_type: tooling_and_process
applies_when: Windows PowerShell에서 한글이 섞인 파일을 리다이렉트(>)·Out-File·Set-Content로 쓸 때
---

# 증상과 근본 원인

PowerShell 5.1의 `>` 리다이렉트와 기본 `Out-File`은 활성 콘솔 코드페이지(한글 Windows CP949가 아닌 환경에선 더 잦음)로 쓴다. UTF-8 한글 바이트가 코드페이지를 통과하며 물음표로 치환되고, 그대로 커밋된다. D-336과 D-140이 정확히 이 패턴이다.

# 해결

1. **한글 파일 쓰기는 UTF-8을 보장하는 경로로만** — `python -c "pathlib.Path(...).write_text(..., encoding='utf-8')"`, 에디터·API 도구, 또는 `Out-File -Encoding utf8`/`Set-Content -Encoding utf8`(단, PS5.1의 utf8은 BOM 붙음 — BOM 없는 UTF-8이 필요하면 [IO.File]::WriteAllText 계열).
2. **콘솔 출력의 깨짐과 파일 부식을 구분** — `git show`·`Get-Content`의 콘솔 렌더링 `?`는 표시 문제일 뿐이다. **Read 도구나 Python 이중 검증**으로 파일 바이트를 확인한 뒤 판단한다(이 회차 D-338 커밋 메시지 `??` 표시는 표시 문제, D-336 행은 실제 부식이었다).
3. **방어망** — harness lint가 governed 파일(ADR Log·모듈 progress/logs)의 `??` 연속을 `suspicious encoding` 에러로 보고한다(D-346). D-140은 이 규칙의 교정 케이스다.

# 확인

- D-336 복구: 상세문서 제목에서 원문 복원(커밋 5f0ceec4). D-140 복구: 본문문서 제목에서 복원(이 변경).
- 규칙 교정: 복구 전 상태에서 `find_mojibake`가 두 행 모두 적발, 복구 후 녹색.
