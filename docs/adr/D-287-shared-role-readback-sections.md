## D-287 역할 패널의 읽기 전용 섹션은 공용 readback 배치를 사용한다

**Status:** Accepted (2026-09-26)

Related: [D-194](D-194-web-shared-components.md),
[D-254](D-254-design-philosophy-and-token-inventory.md),
[D-278](D-278-role-based-surface-ux-and-palette-review.md),
[D-286](D-286-shared-role-readout-layout.md).

**Context:**

Role panels group read-only system, token, safety, network, and SLAM information
into sections or `div` containers. Across host, system security, and setup
panels these use the same local `surface-readback` layout: a shrinkable grid
with shared gaps and a heading whose browser margin is reset. The repeated
structure frames different facts and actions, so content and ownership remain
specific to each panel.

**Decision:**

1. Add `.ui-readback` to the shared component stylesheet. It owns only
   `min-width: 0`, grid display, existing tokenized gap, and direct `h3`/`h4`
   margin reset.
2. Keep native `section` and other semantic elements. The class does not add
   ARIA roles or generate content.
3. Migrate role panels from `.surface-readback` and remove its dashboard-local
   layout rules. Each panel retains its own heading, facts, controls, status,
   responsive sizing, and data behavior.
4. Do not merge `.ui-readback` with `.ui-readout`: the first groups content;
   the second lays out semantic definition-list label/value pairs.

**Alternatives:**

- Keep the section grid local: rejected because the same container geometry is
  repeated across host, setup, and system panels.
- Put headings and data inside a generated generic component: rejected because
  it would take ownership of role-specific content and actions.
- Use the readout component for the full section: rejected because group
  spacing and label/value layout have distinct jobs and compositions.

**Consequences:**

Role panels share predictable section shrink and heading spacing while preserving
native markup and panel ownership. New visual variants require repeated use with
a different task intent; one-off section behavior stays local.

**Validation:**

Shared-control tests verify tokens and migration coverage. Chromium layout tests
check section shrink, heading margin, and horizontal overflow at desktop and
mobile viewports.
