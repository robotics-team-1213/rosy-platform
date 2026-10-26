---
title: A bare 40-digit git id in a validation record reads as a high-entropy token and blocks every push
date: 2026-10-07
last_updated: 2026-10-26
category: workflow-issues
module: docs/validation, test/test_release_boundary_guards.py, tools/hooks/pre-push
problem_type: workflow_issue
component: development_workflow
severity: medium
applies_when:
  - "writing a docs/validation record that names the commit or image it was produced from"
  - "any tracked markdown that quotes a full 40-digit git object id, including CLI code blocks"
tags: [secret-scan, validation-records, git-ids, pre-push-gate, false-positive]
---

# A bare 40-digit git id in a validation record reads as a high-entropy token and blocks every push

## Context

같은 날 두 번 일어났다. `docs/validation` 회차 문서가 기준 커밋을 빈백(백틱만) 40자리 SHA로 적으면
`test_release_boundary_guards.py::test_no_secrets_in_tracked_files`의 high-entropy-token 매처가 이를
시크릿으로 판정한다. 이 시험은 pre-push 훅과 CI가 모두 돌리므로, 문서 하나가 **내려온 모든 커밋의
push를 막는다** — 2026-10-07 오전(`db006d7cf`로 고침, uiux-site-g3-readiness 회차)과 저녁
(`db30e1a0a` 착지 직후 다시 발생, uiux-current-width-device 회차). 저녁 사례는 58커밋이 쌓인 push를
두 차례 거부했다.

이 절의 과거 ID와 아래 예시 ID는 당시 기록 또는 표기 예시다. 현재 main의 도달성이나 현재 공개 배포를 증명하는 용도로 쓰지 않는다.

## Guidance

- 검증 회차 문서에서 기준 git id를 쓸 때는 SHA 앞에 `commit` 을 붙여라: `` `commit befcc5d0…` ``.
  스캐너는 이 접두어를 git id 신호로 읽고 매처를 통과시킨다(`scan_files`의 허용 규칙).
- 컨테이너 이미지·펌웨어 등 git id가 아닌 16진수는 `SHA-256:` 처럼 종류를 앞에 적으면 같은 효과다.
- 허용 단어는 **같은 줄**에 있어야 한다. 원본 해시를 표로 적을 때 머리글(`| 파일 | sha256 |`)만으로는
  통과하지 않는다 — 각 행 셀에 `` sha256 `<64-hex>` ``로 적는다(2026-10-23 vlm-question-bench 회차가
  머리글만 적어 9행이 걸렸고 착지가 멈췄다).
- 9자리 단축 SHA(`961b5d654`)는 매처에 걸리지 않는다 — 접두어 없이 써도 된다.
- CLI 코드블록도 검사 대상이다. `--sha` 값에 설명용 `commit`을 끼우지 말고, 전체 SHA는 본문에서 `commit` 접두어로 기록한다. 실행 예시에는 같은 객체로 해석되는 짧은 revision을 쓰고 축약 예시임을 밝힌다. 실제 명령·결과 원본은 그대로 보존한다.
- 회차 문서를 착지하기 전에 확인하라. pytest는 노트북에서 돌리지 않으므로(D-584) 원격으로
  `python tools/remote/remote_pytest.py -- test/test_release_boundary_guards.py::test_no_secrets_in_tracked_files`
  를 돌리거나, 시험이 쓰는 순수 함수를 파일 하나에 직접 부른다:
  `python -c "import sys; sys.path.insert(0, 'deploy/robot/pinky_pro/release'); import secret_scan as s; p='<path>'; print(s.scan_text(p, open(p, encoding='utf-8').read()))"`
  (인자 순서는 path, text). 빈 목록이면 통과다. push 훅에서 깨지는 것보다 여기서 깨지는 게 싸다.

## Why This Matters

2026-10-26의 site three/four-service 검증 기록은 본문과 표에 접두어가 있었지만 CLI 예시의 `--sha` 뒤에 전체 Git ID를 그대로 적어 같은 guard를 실패시켰다. commit `7b2dbeb623`의 관련 gate는 1 FAIL/1093 PASS/2 SKIP였고, 단독 재실행도 실패했으며 main commit `e6e7c47b3c`에서는 통과했다. 해당 값이 실제 commit 객체임을 확인한 뒤 실행 예시만 고유한 12자리 revision으로 줄이고 전체 SHA는 본문에 유지했다. 수정 commit `6d493681e4`에서 동일 원격 guard가 1 PASS, runner/outer exit0, NEW0/known0/flaky0이었다. scanner·시험·allowlist는 바꾸지 않았다. 코드블록을 예외로 생각하면 같은 실수가 반복된다.

위 2026-10-26 ID는 현재 로컬 검증 지점이다. 공식 재착지와 공개 PR 게시를 기다리는 기록이며, 공개 main/배포 완료 증거로 인용하지 않는다.

- push 훅은 공유 체크아웃의 **모든 세션**이 같이 쓴다 — 한 문서의 오탐이 동료의 푸시까지 막는다.
- CI도 같은 시험을 돌리므로 오탐이 원격에 올라가면 main 초록불(최우선 규칙)이 꺼진다.
- "기록은 얼어 있다"(docs/validation AGENTS)와 충돌하지 않는다 — `commit` 접두어는 관측 결과를
  바꾸는 게 아니라 스캐너가 읽는 표기일 뿐이고, `db006d7cf`가 같은 수정의 선례다.

## When to Apply

- docs/validation 회차 문서 작성·착지 시 (필수)
- 어떤 추적 파일에든 40자리 16진수를 남길 때 (권장: 종류 접두어 `commit`/`SHA-256:` 달기)

## Examples

- 오탐(40자리를 그대로 적은 경우): `` 기준 소스는 로컬 `main` `befcc5d05f4e…`다 `` — 실제로는 40자리 전체
- 통과: `` 기준 소스는 로컬 `main` commit `befcc5d05f4e…`다 `` — `commit` 접두어 뒤라면 40자리 전체도 안전하다
- 선례 커밋: `db006d7cf`(오전 사례), 이 문서를 남긴 커밋(저녁 사례)

## Related

- `test/test_release_boundary_guards.py` — `scan_files`, `test_no_secrets_in_tracked_files`
- `tools/hooks/pre-push` — push 게이트에서 이 시험이 돌는 자리
- `docs/solutions/workflow-issues/adr-numbers-collide-between-concurrent-sessions-2026-09-25.md` — 같은
  공유 체크아웃에서 "문서 하나가 전체 흐름을 막는"류의 다른 사례
