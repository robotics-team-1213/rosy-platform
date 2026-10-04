<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-02 | Updated: 2026-10-02 -->

# panels

## Purpose

Panel modules for the role surfaces (D-204): `console` (operate), `setup` (prepare work), `device` (install/service). Each panel does one job and is declared in `../panels.yaml` (id, surface, slot, order, module, css, role). The shell in `../shell/` mounts them; panels never mount themselves.

## Key Files

| File | Description |
|------|-------------|
| `surface-panels.css` | Shared panel layout for all surfaces; tokens only, no raw colors |
| `console/` | `overview`, `map`, `mode`, `teleop`, `docking`, `line-follow`, `camera` (viewer-level operate surface; act panels carry an `action_group`) |
| `setup/` | `waypoints`, `localization`, `docking`, `dock-admin`, `traffic-policy`, `pose-evidence` (operator role; `pose-evidence` exports `poseUnavailableReason`) |
| `host/` | `hardware`, `system`, `operations` (+ `hardware.css`); `system.js` exports `runtimeGap` |
| `system/` | `diagnostics`, `display`, `events` (+ `events.css`), `security` |

## For AI Agents

### Working In This Directory

- Contract: `export function mount(el, ctx)` returning nothing, an `unmount` function, or `{unmount, beforeHide}`. `ctx` gives `store` (polling scopes), `api`, `role`, `surfaces`.
- Get server state only through `ctx.store.poll` and `ctx.api`; the shell closes the scope on unmount, so no stray timers.
- Add a panel by adding the file and a `panels.yaml` entry; also register the asset in `dashboard/CMakeLists.txt` and `dashboard_assets` in `core_api_web/api/app.py`, or it 404s at import time.
- Theme (D-359): colors and sizes come from `web_common/tokens.css`; use shared `ui-*` components (`ui-section`, `ui-empty`, `ui-form`, `ui-readout`, `ui-actions`). No inline script/style (CSP), no `onclick=`.
- Disabled controls give a reason through the `reason` attribute. Irreversible row actions use the confirm pattern (D-371).
- Never claim a motor power cut for an e-stop (it is a software stop). E-stop is owned by the shell, not panels. Hardware/drive truth comes from `capabilities.runtime`, not the `runtime_mode` string.

### Testing Requirements

`middleware/ui/robot/test` (`test_action_groups_browser.py`, `test_host_operations_browser.py`, `test_panel_copy_evidence_browser.py`, `test_map_readout_browser.py`, `test_waypoint_readiness_browser.py`, `test_dashboard_package.py`, `test_web_budgets.py`), plus `shared/web/test` for copy, palette and token gates.

### Common Patterns

Vanilla ES modules, no bundler. Panels import from `/assets/*` (client, vision, camera-capture) and `/common/*` (web_common). Panel copy is Korean operator prose; identifiers are English. Panels fail soft: an exception in one panel only blanks that slot.

## Dependencies

### Internal

- `../shell/` (mounting, store), `../client.js`, `../panels.yaml`, `shared/web`

### External

None (browser APIs only).

<!-- MANUAL: -->
