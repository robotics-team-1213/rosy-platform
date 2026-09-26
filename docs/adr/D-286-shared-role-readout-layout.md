## D-286 역할 패널의 라벨·값 목록은 공용 readout 배치를 사용한다

**Status:** Accepted (2026-09-26)

Related: [D-194](D-194-web-shared-components.md),
[D-254](D-254-design-philosophy-and-token-inventory.md),
[D-278](D-278-role-based-surface-ux-and-palette-review.md),
[D-285](D-285-shared-role-form-layout-and-field-labels.md).

**Context:**

Console, setup, host, and system panels render read-only label/value pairs with
semantic `<dl>`, `<dt>`, and `<dd>` elements. They repeat the same desktop
two-column grid, subdued labels, tabular values, and mobile single-column
stacking through dashboard-local `.surface-readout` rules. The same information
pattern therefore has the same purpose across role panels but is owned by one
consumer stylesheet.

**Decision:**

1. Add `.ui-readout` to the shared `src/hmi/web/components.css` inventory. It
   styles semantic definition lists with a label/value grid, existing spacing
   and foreground tokens, and tabular numerals.
2. At the existing 30rem breakpoint, stack labels and values in one column,
   allow long values to wrap, and preserve separation between each value and
   the next label.
3. Migrate role panels using `.surface-readout` to `.ui-readout` and remove the
   duplicate dashboard-local layout rules. Keep `<dl>`, `<dt>`, and `<dd>` so
   assistive technology retains their relationship.
4. Panels continue to own which facts appear, their labels, ordering, formatting,
   and empty/error behavior. This decision adds no palette or spacing tokens
   and does not combine readouts with the enclosing section layout.

**Alternatives:**

- Keep the repeated grid in dashboard CSS: rejected because the same semantic
  readout is already used across console, setup, and host roles.
- Replace definition lists with generic rows or cards: rejected because it
  loses native label/value semantics and adds no task value.
- Move the surrounding `surface-readback` section layout as well: rejected
  because section composition and heading spacing are separate from the
  reusable label/value pattern.

**Consequences:**

Role panels share the layout and numerical alignment of read-only facts. New
readout variants require repeated evidence with a distinct intent; content and
task-specific density remain local to each panel.

**Validation:**

`src/hmi/web/test/test_shared_controls.py` checks shared tokenized styles and
panel adoption. Dashboard Playwright tests verify desktop and mobile layout,
wrapping, and tabular numerals.
