# Role console entry, action groups, and map readout implementation plan

**ADR:** [D-289](../adr/D-289-role-console-entry-actions-map-readout.md)  
**Branch:** `feat/uiux-followup`

## Goal

Make the role-oriented console the clear continuation of authentication, make action-group metadata single-source, and let map users read the target coordinates before confirming. Preserve D-283's fixed three-region grammar and the existing command authorization path.

## Ordered work

1. **Return to the requested role surface after authentication.** Add validation and tests first for allowed paths, malformed/external paths, direct `/dashboard` use, and both token and pairing-code completion. Implement a same-tab, same-origin return path without credentials in query strings or storage keys.
2. **Make action-group metadata single-source.** Test catalog schema, uniqueness, group references, manifest fields, and browser order. Put id/title/order in `panels.yaml`, expose validated metadata through the surface manifest, and remove the browser's duplicate map and Python's duplicate allowlist.
3. **Add map target readout.** Test known world-to-cell transforms for pointer and keyboard interactions, including out-of-bounds state and confirmation behavior. Add a shared readout element and update it only for intentional crosshair movement; preserve role/capability/confirmation checks.
4. **Use available desktop observe space.** Add CSS/layout checks for 1366×768 and 1440×900 desktop plus 390×844 mobile. Let the map canvas fill the remaining observe slot and keep action controls and E-stop visible.
5. **Verify and land.** Run focused unit and browser suites after each step, the relevant combined suites and harness lint at the end, compare failures with `test/known_failures.py`, inspect visible browser screenshots, commit the isolated change, merge local `main` safely, and rerun the relevant checks after integration. Do not claim device/field acceptance from host results.

## Scope and constraints

- Preserve the `/dashboard` legacy screen for direct visits during this migration.
- Accept return paths only for `/console`, `/setup`, or `/device`; default invalid targets to `/console`.
- Keep exactly the three D-283 groups in this implementation.
- Keep map selection preview separate from explicit confirmation and server command checks.
- Preserve unrelated dirty work in the shared main checkout; use explicit staging paths.
- Store logs and screenshots under `X:\DevTemp\rosy-uiux-followup\`.

## Acceptance checklist

- [ ] ADR D-289 and ADR Log row pass repository harness lint.
- [ ] Authentication returns to the allowed requested surface for both supported login methods.
- [ ] Direct `/dashboard` compatibility behavior remains covered.
- [ ] Registry and browser consume the same ordered action-group catalog.
- [ ] Keyboard and pointer map readout announces valid world coordinates and out-of-map state.
- [ ] No command is sent without explicit confirmation.
- [ ] Desktop and mobile visible-browser layout passes the D-283 affordance constraints.
- [ ] Targeted and combined tests pass with no new known failures.
- [ ] Commit is integrated into local `main`; remote push and device acceptance remain separate gates.
