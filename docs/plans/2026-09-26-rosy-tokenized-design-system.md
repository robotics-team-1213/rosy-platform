# ROSY Tokenized Design System Rollout

## Goal

Apply [D-292](../adr/D-292-design-tokens-and-component-layout-contract.md): keep ROSY's accepted rose palette and product philosophy, give repeated component spacing named semantic tokens, and make future menu pages use the shared visual contracts without forcing their task-specific layout into one template.

## Scope and constraints

- `src/hmi/web/tokens.css` remains the single source for color, type, base dimensions, and component-role spacing.
- `src/hmi/web/components.css` owns shared control paint and component spacing.
- HMI surfaces, Fleet, games, face LCD, map raster, and sensing diagnostics keep their existing ownership and palette boundaries. Do not blanket-recolor them or bring the parked diagnostics surface into scope.
- Preserve user changes already present in the main checkout. Work in `.worktrees/design-system`; do not touch robot profiles or deployment/runtime behavior.
- Layout geometry such as task-specific grids, widths, order, and positioning remains with its surface owner.

## Implementation steps

1. Add contract tests for the D-292 component-role tokens, their references into the base spacing scale, and their use by shared components.
2. Run the focused token suite red and record the missing semantic roles.
3. Add the named aliases to `tokens.css`; migrate common buttons, fields, actions, forms, labels, readouts, readback sections, headings, and shell spacing in `components.css` to those aliases.
4. Extend the token contract to reject raw spacing dimensions in shared component CSS while allowing borders, line rules, and layout geometry owned by a surface.
5. Run HMI shared-web tests, dashboard tests, and relevant API web route/asset tests. Run harness generation and lint after updating the ADR log and module evidence.
6. Review the real local CORE web path with visible Chromium at desktop and narrow widths. Check menu state, keyboard focus, overflow, target sizes, and semantic color roles. Correct measured issues within scope.
7. Record evidence and remaining acceptance limits. Commit the implementation and documentation as a focused change, merge locally only after ancestry/path checks; do not push.

## Acceptance

- Existing palette values and safety/status/focus meanings are unchanged.
- Each repeated shared spacing decision uses an explicit component-role token backed by the base spacing scale.
- No shared component duplicates arbitrary spacing values; surface-owned grids and dimensions remain local.
- Focused tests, harness lint, visible browser checks, and `git diff --check` pass. Device and field evidence stay separate.
