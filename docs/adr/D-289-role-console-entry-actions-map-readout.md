## D-289 역할별 콘솔 진입과 조작 메뉴·지도 읽기 개선

**Status:** Accepted  
**Date:** 2026-09-26  
**Owners:** Rosy OS HMI / CORE  
**Deciders:** Product and engineering

## Context

D-263 establishes role-based surfaces and a single surface registry, while D-283 fixes the console's three-region grammar and its three action groups. The current `/dashboard` still owns both authentication and a legacy combined operate/inspect screen. New role surfaces send unauthenticated users there, but a successful login leaves them on the legacy screen without a clear next step. The action-group ids are also repeated in the Python registry validator and the browser shell, so adding a menu item requires coordinated edits in two places. The console map supports keyboard crosshair selection, but its accessible description does not report the crosshair's world coordinates. Its canvas also uses a fixed viewport-height clamp, leaving observation space unused on some desktop sizes.

## Decision

1. **`/dashboard` remains the authentication and compatibility entry for this release.** When a user enters it from a role surface, preserve that same-origin return path in a validated `return_to` query parameter. After successful token or pairing-code authentication, return to the requested role surface. Accept only local paths for the registered role surfaces (`/console`, `/setup`, `/device`); reject schemes, protocol-relative paths, and all other targets to `/console`. Never put credentials in the URL. A direct `/dashboard` visit without a return target continues to show the legacy screen and remains available during migration.
2. **The action-group catalog is declared once in `panels.yaml`.** Each group has an id, Korean title, and order. The registry validates the catalog and panel references, and the surface manifest sends the catalog to the browser. The browser creates tabs from the manifest; it has no second id-to-title map. D-283's three groups remain the accepted set for this release. Adding a fourth group requires an explicit ADR revisiting the fixed act-area fit contract and its acceptance tests.
3. **The map exposes keyboard and pointer target coordinates in world units.** An always-present, polite live readout describes the crosshair's world X/Y to two decimal places, and distinguishes an out-of-map cursor from a valid target. Selecting or moving the crosshair remains a preview only; existing confirmation, role, capability, and server checks still gate commands. No command is sent merely by moving the pointer or keyboard focus.
4. **The desktop observe slot gives the map the height remaining after its heading, layers, camera, and messages.** Keep the D-283 sense/observe/act layout, fixed act controls, and mobile stacked layout. Use the existing container and panel minimum-size constraints; do not introduce page scrolling or hide action controls to enlarge the map.

## Alternatives considered

- Remove `/dashboard` immediately: rejected because D-263 delegates its compatibility window to D-204 and existing sessions/documentation still use it.
- Copy a return URL from arbitrary query input: rejected because it creates an open redirect. Only the three registered local surface paths are accepted.
- Keep action titles in JavaScript and add another backend allowlist: rejected because each menu addition would continue requiring synchronized edits.
- Add arbitrary action groups without revisiting layout: rejected because D-283 fixes three groups and the visible act-area fit contract.
- Announce every pointer pixel through a live region: rejected because continuous announcements are noisy; report deliberate crosshair movement and selection at a throttled, useful cadence.
- Increase map height with a larger fixed `vh` value: rejected because short windows and mobile layouts would lose space or clip sibling controls.

## Consequences

The legacy page remains a compatibility surface but role-based entry can resume at its intended page. The registry becomes the authority for group ids, names, and ordering. Map users can inspect the exact target before confirming it without needing to infer coordinates from pixels. The observe region can use available desktop space while the action area retains its fixed safety affordances. Browser and API tests must cover return-path allowlisting, registry validation and manifest output, coordinate announcements, and layout at desktop and mobile sizes. These checks establish host/browser behavior only; they do not establish Pi image, device, or field acceptance.

## Implementation and validation

| Gate | Evidence | Acceptance |
|---|---|---|
| G1 — Entry routing | API/browser tests for allowed, absent, and hostile `return_to`; token and pairing-code success paths | Only an allowed local surface is selected; direct legacy entry is unchanged; credentials never appear in URLs |
| G2 — Action groups | Registry tests and browser test using manifest-provided group titles and order | Three existing groups render in declared order; invalid or undeclared references fail closed |
| G3 — Map readout | Browser keyboard/pointer tests with a known grid transform | Readout matches world coordinates, indicates outside-map state, and only explicit confirmation invokes the existing action |
| G4 — Layout | Visible browser at 1366×768, 1440×900, and 390×844 | Desktop observe map uses available height; fixed action controls and E-stop remain visible; mobile horizontal overflow is zero |
| G5 — Repository | Relevant pytest suites, known-failure comparison, harness lint | No new known failures; ADR indexes and generated indexes are current |

## References

- [D-263 — Role-based menu extension](D-263-role-based-menu-extension.md)
- [D-283 — Console fixed grammar and action groups](D-283-console-action-groups-fit-fixed-grammar.md)
- [D-284 — Shared role-surface status components](D-284-shared-role-surface-status-component.md)
- [D-259 — Keyboard crosshair behavior](D-259-map-keyboard-operation.md)
