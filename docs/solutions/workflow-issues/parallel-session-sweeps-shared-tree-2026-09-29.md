---
title: 병행 세션이 같은 작업 트리를 git add -A로 쓸어 담는다 — 미완성 작업이 타 세션 커밋에 실리고 번호가 충돌한다
date: 2026-09-29
category: workflow-issues
module: 저장소 전체(공유 main 체크아웃에서 병행 세션이 작업할 때)
problem_type: workflow
component: development_workflow
severity: high
symptoms:
  - "작업 트리에 둔 미커밋 ADR Log 행·저널 항목이 병행 세션 커밋(f6416e4d, 5a930e23)에 그대로 실림"
  - "같은 ADR 번호가 표에 두 행 생김(D-337, 2026-09-29) — 기존 parser는 dict 축소로 조용히 묻힘"
  - "내 커밋이 아닌 커밋 메시지로 내 변경이 착지해 기록·저널 의무가 소실됨"
root_cause: workflow
resolution_type: process_and_tooling
applies_when: 하나의 저장소 작업 트리를 여러 세션이 동시에 사용할 때
---

# 증상

2026-09-29 하루에 작업 트리 흡수가 2회, 번호 충돌이 동일 날 3회 기록됐다(`adr_gaps`의 D-223·D-324 노트, D-337 재부여). 커밋 author가 전부 동일(`pl3`)해 attribution 방어가 불가능하다.

# 근본 원인

- `git add -A` 습관: 병행 세션의 스테이징이 내 작업 트리 전체를 포함한다.
- 긴 커밋 창: 문서·구조 파일을 고치고 커밋까지 시간이 걸리면 그 창이 흡수된다.
- 표 행 중복을 못 보던 parser(dict 축소).

# 해결

1. **짧은 커밋 창 규칙** — 공유 main 트리에서 문서·구조 파일(ADR Log, 저널, 구조 시험)을 고치는 세션은 그 즉시 커밋한다. 본문·저널은 뒤따르는 별도 커밋으로 채운다(D-346 Decision 5).
2. **번호 선점** — ADR 번호는 표에 행을 넣는 즉시 커밋으로 선점한다(D-346 Decision 4). 분기 예약은 `adr_gaps`에 사유를 남긴다.
3. **긴 작업은 worktree 격리** — `.worktrees/`에서 작업하면 흡수 자체가 불가능하다.
4. **방어망** — `parse_adr_log`가 표 행 중복을 `duplicate index row` 에러로 보고한다(도구 수단, D-346).

# 확인

- D-337 충돌: 흡수 커밋 직후 표에 2행 → 재부여로 해소(docs/logs.md 2026-09-29 정정 항목).
- D-218/219/220 잠복 중복: 새 검사가 복구 전 상태(710a8a86)에서 3건 모두 적발, 복구 후 녹색(변이 증명 기록).
