## D-294 Shared typography and interaction tokens

**Status:** Accepted (2026-09-26). Extends D-254 and D-292 for the shared web component layer. This decision covers browser UI only; it does not change robot, image, device, or field acceptance.

Related: [D-82](D-82-oklch.md), [D-194](D-194-web-shared-components.md), [D-254](D-254-design-philosophy-and-token-inventory.md), [D-277](D-277-rosy-brand-colour-tokens.md), [D-280](D-280-calm-intelligence-product-design-philosophy.md), [D-292](D-292-design-tokens-and-component-layout-contract.md).

## Context

`tokens.css` already closes the font family and size scales, while `components.css` still repeats numeric font weights, line heights, tracking, focus-ring dimensions, missing-contract outlines, and disabled opacity. These values are shared interaction and reading rules. Keeping them inline makes one component drift from another and leaves the styleguide unable to explain the intended hierarchy. At the same time, borders and 1px grid separators are actual lines, not spacing decisions, and should remain direct declarations.

## Decision

1. `tokens.css` remains the only source for shared typography and interaction values. Keep the existing six `--text-*` sizes and add a small closed primitive vocabulary for weight (`--weight-medium`, `--weight-label`, `--weight-emphasis`, `--weight-strong`), line-height (`--leading-flat`, `--leading-dense`, `--leading-control`, `--leading-label`, `--leading-body`, `--leading-copy`), and tracking (`--track-wide`, `--track-state`; retain `--track-label`). Values preserve the currently rendered component metrics.
2. Name shared focus and contract feedback dimensions (`--focus-ring-width`, `--focus-ring-offset`, `--contract-mark-width`, `--contract-mark-offset`) and disabled treatment (`--disabled-opacity`). Keyboard focus remains the blue interaction color from D-82/D-292; missing component contracts remain critical red. Disabled controls continue to use the existing muted opacity.
3. Shared `components.css` consumes these tokens for every font weight, line height, tracking value, focus/contract outline, and disabled opacity it owns. A 1px border/separator remains a literal line width; `border: 0` remains a reset. Surface-owned layout and typography outside the shared component API remain with their surface unless a repeated contract is established.
4. The dashboard styleguide gains a live typography and interaction specimen that demonstrates heading, label, value, focusable control, and disabled control. It uses the production shared components and adds no demo-only token definitions.
5. Tests enforce the token vocabulary, its exact current values, shared component consumption, and the absence of numeric weight/line-height/tracking/focus/disabled values in `components.css`. The existing browser HMI suite and actual visible CORE-backed browser review remain the acceptance gates.

## Consequences

The shared component layer can change its typography hierarchy and interaction feedback from one reviewed vocabulary, while surface layout stays independent. The closed vocabulary intentionally describes recurring roles rather than every CSS number; one-off surface geometry does not become a global token by default.

## Validation

- Run `python -m pytest src/hmi/web/test src/hmi/dashboard/test -q` with browser tests enabled.
- Run dashboard API route/manifest tests.
- Review the live styleguide and real CORE-backed operator/admin screens in visible Chromium at desktop and mobile widths; inspect keyboard focus, disabled treatment, errors, and overflow.
- Run the ROSY harness lint and regenerate module indexes after updating logs/progress. These checks do not claim ROS-SIM, ARM64 artifact, DEVICE, or FIELD acceptance.
