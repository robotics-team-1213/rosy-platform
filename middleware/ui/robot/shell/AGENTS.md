<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-02 | Updated: 2026-10-02 -->

# shell

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-07

## Purpose

Shell of the role surfaces (D-204). It fetches the panel manifest, assembles panels into slots, and owns only what the three surfaces share: the surface switcher, role indicator, and the single e-stop.

## Key Files

| File | Description |
|------|-------------|
| `shell.js` | Entry: reads `body[data-surface]`, loads the manifest, refreshes every 5 s, renders the SAFE_STOP/e-stop notice, redirects to dashboard login when unauthenticated |
| `mount.js` | `mountPanels(root, panels, contextFor, actionGroups)`: mounts each panel into its slot, groups `act` panels by `action_group` as tabs, isolates failures per panel |
| `store.js` | `createStore(api)`: the only panel window to server state; `scope()` gives per-panel `poll` and is closed on unmount |
| `shell.css` | Layout only (grid, slots, top bar); tokens only |

## For AI Agents

### Working In This Directory

- Import direction: `shell.js` imports `../client.js`, `./mount.js`, `./store.js`, `../surface-navigation.js`. Panels never import the shell.
- A panel import failure or `mount` exception must stay in its slot (`ui-empty`, `data-failed`); the rest and the e-stop keep running. Do not let an exception escape `mountOne`.
- The section is attached before `await import` so screen order equals manifest order. Keep it.
- E-stop stays live and visible at every width and under any dialog (DESIGN.md E-stop First Rule; D-371 non-modal confirm, never `showModal()`).
- The token lives in `sessionStorage` (D-193); the shell reuses the dashboard session and does not store credentials.
- The store is polling only for now. A shared WebSocket subscription is added here when the console moves over.
- CSP: no inline script/style. New files go into `dashboard/CMakeLists.txt` and `dashboard_assets`.

### Testing Requirements

`middleware/ui/robot/test` (`test_surface_layout_browser.py`, `test_surface_entry_browser.py`, `test_surface_viewport_budget_browser.py`, `test_action_groups_browser.py`, `test_role_g2_browser.py`, `test_surface_bridge.py`), `shared/web/test/test_stop_always_live.py`, and `middleware/core/api_web/test/test_ui_manifest.py`.

### Common Patterns

Timers and late responses are cut by closing the store scope, never by flags in panels. Request timeout is `max(2 x interval, 5 s)`; overlapping ticks are skipped.

## Dependencies

### Internal

- `../client.js`, `../surface-navigation.js`, `../panels/`, `../panels.yaml`, `shared/web`

### External

None (browser APIs only).

<!-- MANUAL: -->
