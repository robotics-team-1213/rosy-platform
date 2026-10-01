---
title: 값이 같은 두 토큰은 틀린 참조를 숨긴다 — 두 번째 테마가 역할 오류를 드러낸다
date: 2026-09-30
category: design-patterns
module: hmi/web_common tokens.css + 모든 웹 표면 CSS (D-359)
problem_type: design_pattern
component: frontend
severity: high
symptoms:
  - "밝게 테마에서 위험 채움(비상 정지 각주, 위험 태그, 로그 줄) 위 글자가 짙은 적색 위 짙은 글자로 거의 사라진다"
  - "어둡게 테마에서는 같은 규칙이 완벽하게 보이고 기존 대비 시험도 모두 통과한다"
root_cause: logic_error
resolution_type: code_fix
related_components:
  - design_tokens
  - testing_framework
tags: [tokens, theme, ink-on-crit, contrast, role-tokens, d-359, d-202]
applies_when: "두 토큰이 한 테마에서 같은 값을 가질 때, 또는 새 테마·팔레트를 더할 때"
---

# 값이 같은 두 토큰은 틀린 참조를 숨긴다

## Problem

어둡게 팔레트에서 `--ink`와 `--ink-on-crit`는 같은 값(`#eeeeef`)이다. 위험 채움 위 글자는
`--ink-on-crit`이어야 하지만, 열 개 규칙이 `--ink`를 쓰고 있었다(공용 태그, 불가역 버튼 각주,
Fleet 태그·로그, dashboard 상태·분류, games 손실, styleguide). 한 테마만 있을 때는 틀린 참조가
화면에도 시험에도 드러나지 않았다.

## Symptoms

- D-359 US-002에서 밝게 팔레트를 더하자 `--ink`가 짙은 글자가 되었고, 짙은 적색 채움 위
  글자가 읽히지 않았다.
- 팔레트 게이트(`test_danger_works_as_a_fill`)는 통과했다. 게이트는 **토큰 쌍**의 대비를 보지,
  규칙이 **어느 토큰을 쓰는지**는 보지 않는다.

## Solution

커밋 `2297d11d`: 열 개 규칙을 `--ink-on-crit`(또는 역할 `--flag-danger-ink`·
`--button-irreversible-ink`)로 바꾸고 구조 시험을 더했다.
`src/hmi/web_common/test/test_palette_gates.py::test_text_on_a_danger_fill_uses_the_on_crit_ink`는
위험 채움 배경을 가진 모든 규칙의 글자색이 위험 위 잉크인지 본다.

## Why This Works

값 대비 시험은 "이 두 색이 함께 읽히는가"를 답한다. 역할 오류는 "이 규칙이 올바른 짝을 골랐는가"다.
한 테마에서 값이 같은 두 토큰은 둘을 바꿔 써도 픽셀이 같으므로 값 시험으로는 영원히 잡히지 않는다.
두 번째 테마가 값을 갈라 놓아야 비로소 틀린 짝이 보인다. 구조 시험은 테마 없이도 짝을 검사한다.

## Prevention

- 한 테마에서 값이 같은 토큰 쌍(`--ink`/`--ink-on-crit`, `--status-good`/`--series-goal`)은
  뜻이 다르다는 표시다. 쌍마다 "어느 규칙이 어느 쪽을 쓰는가"를 구조 시험으로 지킨다.
- 새 팔레트를 더하면 값 게이트만 믿지 말고 dark·light 두 테마로 캡처를 보고 채움 위 글자를 확인한다.
- 표면은 팔레트 이름보다 역할 토큰(`--flag-danger-ink`, `--button-irreversible-ink`)을 쓴다.
  역할 이름이 짝을 고정한다([DESIGN.md](../../../DESIGN.md) Colors).
