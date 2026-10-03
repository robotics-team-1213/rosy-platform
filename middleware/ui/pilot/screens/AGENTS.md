<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-02 | Updated: 2026-10-02 -->

# screens

## Purpose

Pilot screens (D-323): connect, drive, input settings, and the OMX sim arm practice. `../app.js` mounts one at a time into its root.

## Key Files

| File | Description |
|------|-------------|
| `connect.js` | `mountConnect`: login code pairing or token, whoami, capabilities, driver gate; calls `onReady`/`onEnter` |
| `drive.js` | `mountDrive`: drive session, hold-to-drive loop with `slewCommand`, camera preview, calibration view, mode labels |
| `drive-view.js` | DOM building for drive: `el`, `mountDriveView`, `buildStage`, `buildControls` |
| `drive-auto.js` | `mountAutoMode`: autonomy intent controls over `../autonomy.js` |
| `inputs.js` | `mountInputs`: stick/gamepad settings (deadzone, curve, preset, invert) via `../input-state.js` |
| `arm.js` | `mountArm`: OMX-AI Gazebo practice; each press sends one bounded trajectory goal through the `omx_sim` driver |

## For AI Agents

### Working In This Directory

- Hold-to-drive: on release, hidden tab, leaving the screen, or gamepad loss, publish zero immediately and release all inputs. Keep that path in every new control.
- Import direction: `../client.js`, `../link.js`, `../stick.js` and `/common/*` (web_common) flow into screens; screens never import `../app.js`. `stick.js` stays pure.
- Look up devices via `driverFor(kind)`, not literal endpoints. Operator wording uses `MODE_LABEL` from `/common/core_ui_logic.js`.
- Theme (D-130.3, D-359): colors and type from `tokens.css`; no inline script/style (CSP), no `onclick=`. The primary device is a landscape tablet.
- Tokens: sessionStorage by default (D-193); never in URL, cookie, or console. No real addresses or accounts in code (they live in `private/`).
- New file: add it to `pilot_assets` in `core_api_web/api/app.py` and to `../CMakeLists.txt`.

### Testing Requirements

```bash
python -m pytest middleware/ui/pilot/test src/runtime/api_web/test/test_pilot_route.py -q
```

`test_pilot_browser.py` covers the screens; `test_autonomy.py`, `test_calibration_view.py`, `test_stick.py` cover their pure helpers. Shared UI gates are in `shared/web/test`.

### Common Patterns

Each screen exports a `mount*` function taking a root element (and callbacks) and builds DOM; teardown goes through the callbacks. Vanilla ES modules, no bundler.

## Dependencies

### Internal

- `../drivers/`, `../client.js`, `../link.js`, `../stick.js`, `../input-state.js`, `../autonomy.js`, `../calibration.js`, `../vision.js`, `shared/web`

### External

None (browser APIs only).

<!-- MANUAL: -->
