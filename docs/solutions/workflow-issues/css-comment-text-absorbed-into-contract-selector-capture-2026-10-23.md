---
module: shared
tags: [css, contract-test, affected-tier, console, comment]
problem_type: workflow
---

# 콘솔 CSS에서 공용 부품 덧칠 계약은 주석까지 검사하고 affected 등급은 이 시험을 부르지 않는다 (2026-10-23)

## 증상

PR CI(affected 등급)가 초록이어도 main full CI에서
`shared/web/test/test_shared_controls.py::test_surfaces_do_not_repaint_shared_controls`가
콘솔 표면 시트를 거부한다. 같은 위반이 수정 뒤에도 다시 발견된다.

## 원인 (2가지, 같은 실패로 이어짐)

1. **주석이 RULE 정규식의 선택자 캡처에 섞인다.** 계약 시험의 RULE = `([^{}]+)\{([^}]*)\}`는
   마지막 `}` 다음부터 다음 `{` 전까지를 전부 선택자로 읽는다. CSS 주석에 공용 부품 이름
   (`ui-section`, `ui-button` 등 CONTROL 정규식 목록의 낱말)이 있으면 주석 텍스트가 선택자의
   일부로 캡처되고, 다음 규칙의 선언에 paint 속성이 있으면 그 규칙까지 위반으로 보고된다.
   2026-10-23에 `.learning-main > ui-section > p { color }` 규칙을 삭제한 뒤에도 **주석의
   "ui-section" 문구**가 같은 실패를 일으켰다(두 번 연속 같은 원인).

2. **affected 등급이 이 시험을 선택하지 않는다.** `harness.yaml`과 `platform_parts.yaml`의
   매핑에서 `operations/site_ui/console/*.css`는 console 모듈 suite로 가지만
   `shared/web/test/test_shared_controls.py`는 shared 모듈 suite에 있어, console 경로 변경이
   이 시험을 부르지 않는다. main push의 full 등급에서만 드러난다.

## 해결

- CSS 선택자와 **주석 모두** 공용 부품 이름을 쓰지 않는다. 주석에 설명이 필요하면
  "공용 부품"이라는 낱말만 쓰고 태그 이름을 적지 않는다.
- 콘솔 표면 시트를 바꿀 때 원격 시험에 `shared/web/test/test_shared_controls.py`를
  함께 지정한다:
  `python tools/remote/remote_pytest.py -- <경로> shared/web/test/test_shared_controls.py`

## 검증

- b4082e9ab0에서 두 사례 모두 재현→수정→통과 확인(원격 AI PC).
- PR #160(첫 위반)→main full 실패→PR #164(수정)→main full 통과.

## 다음에 적용할 조건

- 콘솔·공용 웹 경로의 CSS를 만지면: PR 올리기 전에 이 시험을 직접 돌린다.
- affected 매핑 개선(콘솔 CSS→shared_controls 시험)은 별도 이슈로 남는다.
