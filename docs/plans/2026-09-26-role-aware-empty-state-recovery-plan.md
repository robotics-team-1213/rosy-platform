# Role-Aware Empty States and Recovery Guidance Implementation Plan

> **For implementation:** Use `executing-plans` and complete these tasks in order, with test-first changes and a review after each task.

**Goal:** Replace ambiguous map and Host Agent waiting/error messages with accurate role-aware status and next-step guidance.

**Architecture:** Keep `/console`, `/setup`, and `/device` as they are, with their existing role and API boundaries. Use structured CORE error codes and Host Agent `available`, `code`, and `recovery` fields as the source of truth; panels translate those states into concise Korean messages and actions the current role can actually perform. Keep the D-277 Rosy rose brand identity, D-254 closed token vocabulary, shared shell, and universal E-stop. Use shared `ui-status` for status semantics and existing semantic palette tokens; do not add panel-local colors.

**Tech Stack:** CORE FastAPI, vanilla JavaScript ES modules, existing `ui-*` components and tokens, pytest, Playwright with a local real CORE process.

---

## Scope and decisions to settle first

The previous visible CORE review showed two concrete gaps. This plan also extracts their repeated live-status semantics into the shared UI inventory under D-284:

- `GET /api/v1/map` returns structured `NOT_FOUND` when no occupancy map has arrived, while the console says it is still waiting for map data.
- Administrator device cards can report that Host Agent is unreachable. The API already returns `code` and `recovery`, but `host/operations.js` currently renders the detail and does not present recovery guidance as a distinct next step. The Windows CORE host used for review also returned an English socket limitation; that host-only detail must not be presented as the robot's production condition.

Before implementation, audit the exact response contracts and write a D-279 ADR (verify the next available number at execution time). Decide and document this state vocabulary:

| State | Evidence | UI treatment |
|---|---|---|
| Loading | Request is still pending | Brief progress copy; do not imply failure |
| Ready | Valid snapshot/readback | Show supplied data and its existing freshness/health evidence |
| Empty / not configured | Known endpoint returns its documented `NOT_FOUND` code for absent data | Say what is absent; give only a role-authorized next step |
| Unsupported | Capability state or documented unsupported response | Name the unsupported capability; do not offer the action |
| Unavailable | Host Agent payload says `available: false` | Show source status and its supplied recovery guidance |
| Forbidden | HTTP 403 | State that the role cannot open or perform this action; never relabel it as missing data |
| Request error | Network, timeout, or other unexpected HTTP failure | Say the latest state could not be read; preserve last-known data only with a stale label |

Do not infer a stale map without a backend freshness field, translate arbitrary socket text as a diagnosis, create a new top-level menu, add a server recovery command, or weaken API authorization.

## Task 1: Confirm contracts and record D-279

**Files to inspect:**

- `src/runtime/api_web/core_api_web/api/v1/map.py`
- `src/runtime/api_web/core_api_web/api/v1/host.py`
- `src/runtime/api_web/core_api_web/api/host_agent_client.py`
- `src/runtime/api_web/core_api_web/api/errors.py`
- `src/hmi/dashboard/client.js`
- `src/hmi/dashboard/map.js`
- `src/hmi/dashboard/panels/console/map.js`
- `src/hmi/dashboard/panels/host/operations.js`
- `src/hmi/dashboard/panels/host/system.js`
- `docs/adr/D-278-role-based-surface-ux-and-palette-review.md`

**Steps:**

1. Exercise map ready and absent responses and Host Agent reachable/unreachable replies using the existing FastAPI test fixtures. Record exact status, `error.code`, `available`, `code`, `detail`, and `recovery` fields; do not derive behavior from the Windows-only English socket string.
2. Check `panels.yaml` and direct API roles for the affected panels. Record which role can reach `/setup` and `/device` before proposing any CTA.
3. Write the D-279 failing-case matrix and compare a shared generic error screen, endpoint-specific recovery messages, and hiding missing data. Choose the smallest option that keeps endpoint ownership and role rules clear.
4. Record D-279 as the accepted role-aware behavior decision. D-284 formalizes the shared status component and palette contract before those UI changes are integrated.

## Task 2: Preserve structured API errors in the dashboard client

**Files:**

- Modify: `src/hmi/dashboard/client.js`
- Modify: `src/hmi/dashboard/shell/shell.js` (pass the current surface manifest to panels)
- Test: `test/test_role_surface_states_browser.py` (new; mount the real client/module code with controlled HTTP responses)

**Steps:**

1. Add a browser test that receives `NOT_FOUND` from an API response and proves the client error retains HTTP status and structured error code. Add cases for 403 and an unstructured network error.
2. Run `python -X utf8 -m pytest test/test_role_surface_states_browser.py -q` and confirm the new assertions fail before implementation.
3. Extend the existing `api()` error object with the response's structured error code. Retain the current message and status behavior; do not expose token data or change URL/auth handling.
4. Run the focused browser test and confirm that 404 `NOT_FOUND`, 403, and network errors remain distinguishable.

## Task 3: Give the console map truthful empty and recovery states

**Files:**

- Modify: `src/hmi/dashboard/map.js`
- Modify: `src/hmi/dashboard/panels/console/map.js`
- Modify: `src/hmi/dashboard/panels/surface-panels.css` (accessible recovery link/disclosure styling using current tokens)
- Test: `test/test_role_surface_states_browser.py`
- API contract tests: existing `src/runtime/gateway/test/test_map_snapshots.py`

**Steps:**

1. Add an API regression proving absent occupancy map is the documented `NOT_FOUND` response and valid map snapshots still return normally.
2. Add browser cases for loading, missing map, valid map, 403, and transport failure. Assert visible copy, accessible status announcement, and that unexpected errors do not become the empty-map state.
3. Run the new browser test and focused API case; keep the missing-map assertion red before changing the panel.
4. Update the map request path to classify only its known `NOT_FOUND` response as empty. Keep retry/poll behavior for temporary failures and clear the empty/error message after valid data arrives.
5. Show Viewer an explanation that an operator must prepare the map. Show Operator/Administrator a link to `/setup` only when the current manifest grants that surface. Do not expose disabled mutation controls as the only recovery route.
6. Verify map click and keyboard selection still require the role and Navigation capability introduced under D-278, with server authorization unchanged.

## Task 4: Make Host Agent absence actionable without guessing

**Files:**

- Modify: `src/hmi/dashboard/panels/host/operations.js`
- Modify only if evidence requires it: `src/hmi/dashboard/panels/host/system.js`
- Test: `test/test_role_surface_states_browser.py` or focused additions to `test/test_surface_device_browser.py`
- Contract tests: existing `src/runtime/api_web` Host Agent and `src/runtime/gateway/test/test_host_cards.py` tests; locate exact file names during implementation

**Steps:**

1. Add browser cases for `available: false` with and without `recovery`, `available: true` with a warning, and a request-level 403/error.
2. Confirm that the current admin release/network controls remain disabled while Host Agent is unavailable and that no request is sent by keyboard or pointer.
3. Run the focused device-browser test and confirm the recovery case fails before implementation.
4. Render the server-provided recovery separately from the short status sentence, using an accessible disclosure only when detail is useful. Keep diagnostics text as text; do not inject markup.
5. Localize only stable, known state labels. Preserve unrecognized backend detail as diagnostic detail and avoid claiming a cause or recovery command the backend did not provide.
6. Confirm a successful later poll clears the unavailable state and re-enables only the controls allowed by existing capability/readback rules.


## Task 5: Share button sizes, action groups, status semantics, and palette

**Files:**

- Modify: `src/hmi/web/ui.js`, `src/hmi/web/components.css`
- Modify: `src/hmi/web/test/test_shared_controls.py`
- Migrate repeated role-panel action groups to `ui-actions`; use named `ui-button` sizes
- Migrate console map and host operation status nodes to `ui-status`
- Record: `docs/adr/D-284-shared-role-surface-status-component.md`

**Steps:**

1. Define button sizes `secondary`, `primary`, and `irreversible` against the existing 44px, 48px, and 58px target tokens. Button kind supplies a default; special controls may request a named size, never a raw height.
2. Define `ui-actions` for responsive wrapping and tokenized spacing. Panels keep control order, labels, and task-specific layout.
3. Define one closed status vocabulary for pending, empty, ready, warning, error, unavailable, and forbidden. The shared element owns the polite status announcement, hidden behavior, and visual token mapping.
4. Use only existing semantic tokens: neutral states remain neutral, attention states use the existing warning token, selected segments use the raised neutral surface, and browser scrollbars use existing ground tokens. ROSY rose remains brand identity. Add no palette values.
5. Keep recovery wording, endpoint detail, links, role checks, and command gating in the owning panel.
6. Add shared-control gates for status states, ARIA defaults, palette tokens, button-size mapping, responsive action groups, and panel adoption.

## Task 6: Review role flows in the visible CORE browser

**Steps:**

1. Start the real FastAPI app and `CoreServices.build()` from the implementation worktree, using the existing dev identities and data under `X:\DevTemp`.
2. In visible Playwright, review Viewer `/console`, Operator `/console` and `/setup`, and Administrator `/device` at 1440px and 390px.
3. Exercise no map → valid map → temporary request error; exercise Host Agent unavailable → supplied recovery → reachable. Never click E-stop, motion, network apply, rollback, or any other state-changing operation during this visual review.
4. Verify direct unauthorized surfaces still return 403, authorized surfaces return 200, navigation reflects the current manifest, and the E-stop stays visible and unchanged for all roles.
5. Check keyboard focus, status announcements, reason links, button disabled states, text contrast, and horizontal overflow. Use the current tokens; add no palette values unless the measured state design requires a new semantic token and D-279 accepts it.
6. Capture screenshots and response evidence only under `X:\DevTemp`; do not claim ROS-SIM, ARM64, device, or field acceptance from CORE browser evidence.

## Task 7: Verify, document, and integrate

**Steps:**

1. Run focused tests:

   ```powershell
   python -B -X utf8 -m pytest src/hmi/dashboard/test src/hmi/web/test src/runtime/api_web/test src/runtime/gateway/test/test_api.py src/runtime/gateway/test/test_map_snapshots.py src/runtime/gateway/test/test_host_cards.py test/test_role_surface_states_browser.py test/test_surface_device_browser.py -q -p no:cacheprovider
   ```

   Expected: all selected tests pass; report any existing unrelated failure separately.

2. Run `python tools/harness/rosy_harness.py generate`, inspect generated paths, and stage only files from this plan.
3. Run `python tools/harness/rosy_harness.py lint` and `git diff --check`. Keep known unrelated WIP format errors visible; do not edit those files as part of this plan.
4. Update D-279 validation, dashboard logs, and the plan's completion notes with role-by-role browser evidence and runtime limits.
5. Commit the verified feature in the isolated worktree. Recheck current `main`, dirty paths, ancestry, changed-path overlap, and merge-tree immediately before local fast-forward integration. Preserve unrelated WIP and do not push.

## Acceptance criteria

- A documented `NOT_FOUND` for an absent occupancy map is visibly different from loading, forbidden access, unsupported capability, and transport/server failure.
- Viewer receives no inaccessible setup action; Operator and Administrator get the setup route only when their manifest permits it.
- Host Agent cards show unavailable state and supplied recovery guidance without converting technical detail into an unsupported diagnosis or enabling host commands.
- Returning valid map/Host Agent data clears the previous empty/error state; stale data, if any, is explicitly labeled from backend evidence.
- Existing role matrix, API 401/403/404 behavior, semantic palette meanings, named 44/48/58px button targets, and universal E-stop remain intact.
- Desktop and 390px visible Playwright review has no horizontal overflow or browser errors.
- Role-owned status panels use shared `ui-status`; every state uses existing Rosy semantic tokens, with rose reserved for brand identity.
- Tests, generated index, lint outcome, local commit SHA, merge SHA, and unperformed runtime tiers are recorded separately.

## Execution record — 2026-09-26

- Focused dashboard, shared UI, API, map, Host Agent, role-browser, and device-browser suites: **241 passed, 3 skipped**.
- Shared browser component contract: **1 passed** for 44/48/58px button targets, segment surface color, status ARIA/hidden behavior, warning token, `ui-actions`, and scrollbar tokens.
- Visible Playwright review: Viewer `/console`, Operator `/console` and `/setup`, Administrator `/device`; 1440px and 390px captures. Unauthorized manifests returned 403, authorized device manifest returned 200, setup-link visibility matched role and empty-map state, no page errors or horizontal overflow, E-stop visible. Capture folder: `X:\DevTemp\rosy-role-empty-state-recovery`.
- `impeccable detect` returned no findings. `git diff --check` passed.
- Harness generation completed after rebasing on current main. Harness lint: **0 errors, 21 last-verified evidence warnings**. Both reserved D-279 gap entries were removed now that the accepted D-279 ADR is present.
- Host-only Windows response and browser review do not establish ROS-SIM, ARM64 image, device, or field acceptance.
