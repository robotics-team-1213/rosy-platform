---
title: 무채색을 섞는 color-mix는 oklab으로 한다 — Chromium은 oklch에서 회색의 색상각을 0°로 풀어 붉게 섞는다
date: 2026-09-30
category: logic-errors
module: hmi/web_common tokens.css (D-359 파생 토큰)
problem_type: logic_error
component: frontend
severity: medium
symptoms:
  - "파생 선·장막·세척 토큰이 원래 hex 값보다 미세하게 붉게 계산된다(실측 ΔE_OK 최대 0.019)"
  - "바탕·잉크처럼 채도가 거의 0인 팔레트 색에서만 나타나고 status·series 색에서는 보이지 않는다"
root_cause: wrong_api
resolution_type: code_fix
related_components:
  - design_tokens
  - testing_framework
tags: [css, color-mix, oklch, oklab, chromium, tokens, theme, d-359]
applies_when: "팔레트 색에서 알파·혼합 파생 토큰을 color-mix()로 만들 때"
---

# 무채색을 섞는 color-mix는 oklab으로 한다

## Problem

D-359 US-001에서 RGB로 굳어 있던 파생 토큰 약 30개를 `color-mix()`로 팔레트에서 만들게 바꿨다.
처음 초안은 `color-mix(in oklch, var(--ink) 14%, transparent)`였다. 계산된 색이 원래 값과 맞지 않았다.

## Symptoms

- 선(`--line-*`)·장막(`--scrim*`)·`--panel-fill`처럼 바탕·잉크를 섞는 값이 붉은 쪽으로 기울었다.
  Chromium 계산값과 옛 hex의 차이는 ΔE_OK 최대 0.019였다.
- `--status-crit-a45` 같은 유채색 파생은 정상이었다.

## What Didn't Work

- 혼합 비율을 손으로 조정하는 것. 원인은 비율이 아니라 색상각이라 비율로는 사라지지 않는다.

## Solution

파생 블록의 모든 혼합을 `in oklab`으로 쓴다(`src/hmi/web_common/tokens.css` 파생 블록 머리 주석,
ADR [D-359](../../adr/D-359-theme-ready-tokens-shared-controls-and-responsive-tiers.md) §1.2, 커밋 `fdb428de`).

```css
--line-14: color-mix(in oklab, var(--ink) 14%, transparent);
--scrim: color-mix(in oklab, var(--ground-deep) 84%, transparent);
```

## Why This Works

oklch는 극좌표다. 채도가 거의 0인 색은 색상각이 무력(`none`)으로 풀린다. Chromium은 혼합할 때
그 `none`을 0°(붉은 쪽)로 채운다. 그래서 회색끼리, 또는 회색과 `transparent`를 섞어도 결과에
0° 색상이 생긴다. oklab은 직교 좌표(a, b)라 색상각이 없고, 무채색은 a·b가 0으로 남는다.

## Prevention

- 파생 토큰의 혼합 공간은 oklab이다. oklch는 팔레트 값을 **생성**할 때만 쓴다.
- 새 파생 토큰을 더하면 브라우저 계산값을 한 번 확인한다. `RosyPalette.readColour()`는
  계산된 색을 캔버스로 되읽으므로 실측 비교에 그대로 쓸 수 있다.
- 시험 파서(`src/hmi/web_common/test/token_themes.py`)는 `color-mix(in oklab, …)`를 풀어
  대비를 계산한다. oklch 혼합을 더하면 파서도 같은 규칙을 알아야 한다.
