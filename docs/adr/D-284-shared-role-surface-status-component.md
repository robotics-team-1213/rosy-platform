## D-284 역할 화면의 상태·복구 표현은 공용 UI 부품과 Rosy 토큰을 사용한다

**Status:** Accepted (2026-09-26)

Related: [D-254](D-254-design-philosophy-and-token-inventory.md),
[D-277](D-277-rosy-brand-colour-tokens.md),
[D-278](D-278-role-based-surface-ux-and-palette-review.md),
[D-279](D-279-role-aware-empty-state-recovery.md).

**Context:**

Role-aware console and host panels report loading, known empty data, ready data,
warnings, request failures, unavailable agents, and authorization failures.
Panels also repeat action groups and sometimes override shared button geometry.
Their copy, role checks, and local layout belong to each panel, while status
semantics, button target sizes, reusable action grouping, and palette meaning
must stay consistent. D-254 defines the existing component and token inventory.

**Decision:**

1. Add `ui-status` to the shared `src/hmi/web/ui.js` and `components.css` inventory.
   It defaults to `role="status"` and `aria-live="polite"` and accepts the closed
   states `pending`, `empty`, `ready`, `warning`, `error`, `unavailable`, and
   `forbidden`. Its `hidden` attribute must suppress rendering.
2. `ui-button` maps the closed sizes `secondary`, `primary`, and `irreversible`
   to the existing `--target-secondary` (44px), `--target-primary` (48px), and
   `--target-irreversible` (58px) tokens. The kind provides its default size;
   panels may request another named size but may not set a raw height. Teleop
   controls use the named primary target size.
3. Add `ui-actions` as a shared layout primitive for responsive, wrapping action
   groups. It owns spacing from existing `--space-*` tokens; panels still own
   the group's content, label, order, and task-specific arrangement.
4. Shared components and browser surfaces consume existing semantic palette
   tokens. Neutral progress, empty, and ready states use the existing nominal
   foreground. Warning, error, unavailable, and forbidden use the existing
   `--status-warn` token. A selected segment uses `--ground-card-2`; browser
   scrollbars use existing ground tokens. ROSY rose remains brand identity and
   is not used to encode health or permission state. This decision adds no color
   values or spacing tokens.
5. Panels retain ownership of truthful copy, endpoint-specific recovery, role
   checks, and actions. They use `ui-status` for live status rather than painting
   or recoloring a local control. Details and actions remain composed by the
   panel around the shared primitives.
6. An unknown status or size is marked as a contract error and falls back to the
   secondary visual size without inventing another palette meaning. Server
   authorization and role manifests remain the authority for access and recovery
   links.

**Alternatives:**

- Keep status paragraphs, action groups, and button geometry local: rejected
  because repeated accessibility, sizing, and layout behavior would continue to
  drift.
- Put endpoint copy and recovery actions inside a generic component: rejected
  because it would blur panel ownership and role-specific decisions.
- Add new colors for each failure class: rejected because existing semantic
  tokens already represent attention and D-254 keeps the palette closed.

**Consequences:**

Shared status, button sizing, and action group layout are consistent across role
surfaces while content and recovery stay close to the endpoint owner. New states,
sizes, or color semantics require an ADR and updates to the shared component
gates. This does not change the global palette or the security boundary.

**Validation:**

`src/hmi/web/test/test_shared_controls.py` verifies registration, closed states,
ARIA defaults, palette tokens, button-size mappings, action-group ownership, and
panel adoption. Browser tests verify state visibility, role restrictions, and
recovery behavior.
