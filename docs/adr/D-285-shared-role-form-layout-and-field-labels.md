## D-285 역할별 패널은 공용 폼 배치와 필드 라벨 패턴을 사용한다

**Status:** Accepted (2026-09-26)

Related: [D-194](D-194-web-shared-components.md),
[D-254](D-254-design-philosophy-and-token-inventory.md),
[D-278](D-278-role-based-surface-ux-and-palette-review.md),
[D-284](D-284-shared-role-surface-status-component.md).

**Context:**

Role panels compose native forms for setup and operations. Multiple panels
repeat the same wrapping row layout and stacked label/control spacing through
`surface-form`, `surface-inline-form`, and `surface-field` rules local to the
dashboard. The shared `ui-field` currently paints the control itself; it does
not own the form's label or layout. This leaves the same interaction pattern
with local names and responsive behavior.

**Decision:**

1. Keep native `<form>`, `<label>`, `<input>`, and `<select>` elements so browser
   submission, label association, validation, and keyboard behavior remain
   native.
2. Add the shared `.ui-form` layout class and `.ui-field-label` grouping class
   to `src/hmi/web/components.css`. They use existing `--space-*` tokens and
   collapse to a full-width vertical layout at the existing 30rem breakpoint.
3. Role panels use these shared classes instead of dashboard-local form and
   label classes. Panels continue to own field meaning, order, validation,
   control types, endpoint behavior, and form copy.
4. Keep input appearance, width constraints tied to the surface, and any
   domain-specific form geometry at the consumer. This ADR adds no new color,
   typography, spacing, or target-size tokens and does not change `ui-field`'s
   API.

**Alternatives:**

- Keep form layout local: rejected because the same row, label, and mobile
  behavior already repeats across role panels.
- Replace native forms and labels with a custom element: rejected because it
  would add a non-native submission boundary without improving the repeated
  pattern.
- Extend `ui-field` to own label, validation, and controls: rejected because
  current panels need native form controls and domain-specific validation; the
  existing component only owns control appearance.

**Consequences:**

Role panels gain one shared form layout contract while retaining native form
semantics and endpoint ownership. Future variants require repeated use with a
distinct intent and an ADR; one-off geometry stays with its panel.

**Validation:**

`src/hmi/web/test/test_shared_controls.py` checks shared styles, token use,
mobile collapse, and panel adoption. Dashboard panel tests and browser layout
tests check composition and visible behavior.
