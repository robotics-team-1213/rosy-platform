# ROSY shared typography and interaction token plan

**Decision:** [D-294](../adr/D-294-shared-typography-and-interaction-tokens.md)
**Status:** In progress

## Goal

Complete the shared web component token contract for typography and interaction feedback while preserving the current visual metrics, role meanings, and surface-owned layout.

## Steps

1. Add failing contract tests for the closed typography and interaction vocabulary and for `components.css` consuming it.
2. Add the D-294 tokens and migrate shared component CSS without changing rendered values. Keep 1px borders and separators as literal rules.
3. Update the living styleguide with production component specimens for hierarchy, focus, and disabled controls.
4. Run focused contract tests, the full browser-enabled HMI suites, dashboard API route/manifest tests, and harness lint/generation.
5. Review styleguide and real CORE-backed operator/admin views in a visible Chromium window on desktop and mobile; record screenshots/evidence under `X:\DevTemp`.
6. Append module journals, refresh progress/index files, commit the scoped work, merge the branch into local `main`, and verify final status/ancestry. Do not push.

## Acceptance

- No shared component declaration carries a raw numeric font weight, line height, tracking value, focus/contract outline dimension, or disabled opacity.
- Browser-visible component metrics match the current values; keyboard focus is visible and remains distinct from status color.
- Desktop/mobile operator and administrator screens have no new page errors or horizontal overflow.
- Local source/browser acceptance is recorded separately from device or field acceptance.
