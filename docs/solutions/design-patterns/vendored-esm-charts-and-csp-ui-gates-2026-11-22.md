---
title: 엄격 CSP(style-src 'self')와 UI 게이트 아래 외부 ESM 차트 벤더링 및 렌더링 검증 규칙
date: 2026-11-22
category: design-patterns
module: shared/web/vendor + applications/fleet/web (cockpit-telemetry.js, roster-workspace.js)
problem_type: design_pattern
component: frontend
severity: high
symptoms:
  - "uPlot ESM 차트가 0 CSP 오류로 마운트되고 canvas.getImageData()에 16,995 px가 찍히는데도 실제 화면에서는 64px 빈 상자로 보인다"
  - "shared/web/vendor/에 uPlot.min.css를 함께 두면 test_palette_gates.py 및 test_surface_typography_focus_contracts.py가 원시 색·토큰 위반으로 실패한다"
  - "panel sections.status()가 root.hidden = false 전에 호출되어 plotHost.clientWidth가 0이거나, 로봇·로봇팔 전환 시 scales.y.range 클로저가 이전 범위를 유지해 240 mA 파형이 잘린다"
root_cause: csp_and_scanner_boundary
resolution_type: code_fix
related_components:
  - web_common
  - fleet_console
  - testing_framework
tags: [vendor, csp, uplot, threejs, c15, patterns-registry, metrics, d-766]
applies_when: "shared/web/vendor/에 JS 시각화 라이브러리를 추가하거나 patterns.yaml 상태를 built로 승격해 UI 회귀 게이트를 검증할 때"
---

# 엄격 CSP와 UI 게이트 아래 외부 ESM 차트 벤더링 및 렌더링 검증 규칙

## Problem

Fleet 콘솔은 `style-src 'self'; script-src 'self'` CSP와 `shared/web/test/`의 정적 게이트(원시 색, 요소 `.style` 금지, 공유 컨트롤 재도색 금지, 파일 600줄 상한 D-766) 아래에서 동작한다.

1. `test_no_element_style.py`, `test_shared_dedupe.py`, `test_patterns_registry.py`는 `vendor/`를 건너뛰지만, **`test_palette_gates.py`와 `test_surface_typography_focus_contracts.py`는 `vendor/*.css`를 그대로 스캔한다.** 서드파티 CSS를 `vendor/`에 넣으면 정적 게이트가 실패한다.
2. 반대로 `uPlot.esm.min.js`만 벤더링하고 `uPlot.min.css`를 빼면, uPlot이 `<canvas>` 앞에 삽입하는 `.u-under` / `.u-over` div가 `position: static`으로 남아 `height: 64px` 흐름 공간을 차지한다. 결과적으로 `<canvas>`가 `.telemetry-chart-plot { overflow: hidden }` 바깥으로 밀려 **화면 픽셀은 0개인데 `ctx.getImageData()`만 16,995 px로 잡히는 거짓 양성**이 생긴다.

## Solution

1. **JS-only 벤더링 + 구조 CSS 보완 (`shared/web/vendor/uPlot.esm.min.js`, `roster.css`):**
   - `shared/web/vendor/`에는 줄 수 600줄 이하인 ESM 번들(`.js`)과 `.LICENSE`만 두고(`shared/web/test/test_asset_manifest.py` `NOT_SHARED`·`shared-assets.json`·`CMakeLists.txt` 등록), 서드파티 `.css`는 넣지 않는다.
   - 대신 표면 CSS(`roster.css`)에서 `.telemetry-chart-plot > div > div`에 `position: relative`, `> div > div > div`(`.u-under`/`.u-over`)에 `position: absolute; inset: 0; pointer-events: none;`을 부여한다(미사용 클래스 검사 회피).
2. **동적 바운드·숨김 폭 동기화 (`cockpit-telemetry.js`):**
   - `scales.y.range`가 초기 클로저를 잡지 않도록 `id`·`yBounds` 키 변경 시 플롯을 재생성하고, 비동기 `await import(...)` 중 들어온 갱신은 `pendingRedraw`로 재생한다.
   - `createRobotPanel`이 `root.hidden = false` 전에 `sections.status()`를 호출하므로, `clientWidth === 0`일 때는 `requestAnimationFrame`으로 노출 직후 `setSize`를 맞춘다.
3. **실제 보이는 영역 기준 픽셀 게이트 (`ui_capture_review.py`):**
   - `ctx.getImageData()` 대신 `.telemetry-chart-plot`과 `canvas`의 **교차 `getBoundingClientRect()`** 위에서 스크린샷 PNG 실측 픽셀(`telemetry_chart_nonzero_pixels`)을 센다.
4. **C15 Three.js 승격 (`patterns.yaml` + `component-controls.css`):**
   - `patterns.yaml`의 `status: built` 승격은 표면 채택 파일(`roster-workspace.js`)과 `product_hook` 클래스명 일치가 필요하며, `.robot-view*` 스타일은 `ui-button` 재도색 금지를 피하기 위해 공용 `shared/web/component-controls.css`에 둔다.

## Verification

- `test/architecture/test_module_structure.py`: **46/46 통과** (`cockpit-telemetry.js`를 `applications/fleet/web/shared/`로 이동해 루트 단위 10,000줄·파일 600줄 상한 준수).
- `ui_preflight.py`: 정적 UI 게이트 통과(`fleet-cockpit-v3` 단독 커밋 `51d70cabc3`에서 158/158 + 88 Node 통과; 이후 PR #507 경유 `origin/main` 합류분 `measured-calibration-view.js:75` 기존 `setOff` 1건만 별도 실패).
- `ui_capture_review.py` 7뷰포트 캡처: 전 뷰포트 `page_errors: []`, `csp_errors: []`, `telemetry_chart_nonzero_pixels` 6,015–8,997 px, `robot_3d_nonzero_pixels` 29,408–52,160 px 실측 확인.
