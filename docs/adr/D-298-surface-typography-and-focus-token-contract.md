## D-297 Surface typography and focus feedback use shared tokens

**Status:** Accepted (2026-09-27). Extends D-292 and D-294 to repeated typography and keyboard-focus rules in the HMI dashboard, Fleet console, and games board. This decision covers browser UI only; it does not change robot, image, device, or field acceptance.

Related: [D-82](D-82-oklch.md), [D-194](D-194-web-shared-components.md), [D-254](D-254-design-philosophy-and-token-inventory.md), [D-292](D-292-design-tokens-and-component-layout-contract.md), [D-294](D-294-shared-typography-and-interaction-tokens.md).

## Context

D-294 closed the shared component vocabulary, but application-owned CSS still repeats the same font weights, line heights, tracking values, and focus-ring dimensions. Those declarations can drift between the dashboard, Fleet, and games surfaces even though they express the same hierarchy or keyboard interaction. Some values describe a unique brand label, operational state, canvas focus, or longer reading passage and should not be converted into a generic component rule.

## Decision

1. Extend `src/hmi/web/tokens.css` with `--weight-regular: 400` and `--focus-ring-offset-outer: 2px`. Existing weights, leading values, and tracking values from D-294 remain the canonical shared vocabulary.
2. Migrate repeated surface declarations in the HMI dashboard, Fleet console, and games board to the existing semantic tokens, preserving their computed values. Font shorthands that rely on the browser's implicit regular weight use `--weight-regular` explicitly.
3. Migrate 2px blue `:focus-visible` rings to the shared focus width and outer offset. Keep the existing 1px shared offset where already used. The dashboard map canvas retains its 3px focus offset because the larger gap separates its large, spatial viewport from surrounding controls; the warning-colored active teleoperation outline remains operational state feedback, not keyboard focus.
4. Keep unique brand/kicker tracking and longer Fleet log/note leading surface-owned where no repeated role justifies a shared token. Specifically, Fleet brand leading `1.15`, dashboard copy `1.35`, `1.45`, and `1.55`, and Fleet note/log leading `1.6` and `1.7` remain explicit reading roles. Keep status, stale-data, overlay, and disabled-state opacity semantics separate. Do not change the Rosy palette, spacing, layout, or surface information hierarchy.
5. Add a contract test for the three surface CSS domains. It rejects un-tokenized repeated weights, shared line heights/tracking values, and standard keyboard focus dimensions while documenting the narrow surface exceptions above.

## Consequences

Repeated type hierarchy and keyboard focus rules can be reviewed in one vocabulary while each surface retains its own layout and genuinely unique reading or brand treatments. Explicit exceptions prevent a mechanical migration from changing long-form readability or operational feedback. This decision does not claim ARM64 image, device, ROS-SIM, or field acceptance.

## Validation

- Run the surface token contract and browser-enabled HMI suites.
- Run Fleet and games host suites and compare failures against `test/known_failures.txt`; unrelated pre-existing failures remain visible.
- Run dashboard route/manifest checks and harness lint/generation.
- Review actual dashboard, Fleet, and games screens in a browser at desktop and mobile widths for focus visibility, rendering changes, errors, and overflow.
