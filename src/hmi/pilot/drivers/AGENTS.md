<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-02 | Updated: 2026-10-02 -->

# drivers

## Purpose

Device-kind drivers for Pilot (D-323 T5, D-296). A driver owns the endpoints and gate decision for one kind of device; screens ask the registry for it and never hardcode paths.

## Key Files

| File | Description |
|------|-------------|
| `registry.js` | `registerDriver`/`driverFor`/`registeredKinds`; a duplicate kind with a different driver throws, the same driver is idempotent |
| `pinky_core.js` | Pinky CORE driver (`KIND = "pinky_core"`): `assessGate` turns whoami plus capabilities into raw reason codes (`role:`, `teleop_withheld`, `drive_disabled`), plus path actions for mode and safety stop |
| `omx_sim.js` | SIM-only OMX arm transport (`omx_sim`) over `/api/v1/sim/omx`: `discover`, `request`; never uses Pinky teleop, CORE tokens, or `/ws/state` |

## For AI Agents

### Working In This Directory

- Registration happens in `../app.js` (`registerDriver(pinkyCore.kind, ...)`). A new kind needs a driver file plus that line, and an entry in `pilot_assets` and `CMakeLists.txt` (else 404).
- `assessGate` returns raw codes only; operator wording is the screen's job. A server older than API v1.21 has no `runtime` key: the 409 `CAPABILITY_WITHHELD` at command time is the safety net, do not guess.
- OMX final commands stay owned by the OMX local controller (D-296). `omx_sim` is simulation only and must reject targets without `simulation: true`.
- Same-origin only; no tokens in URLs, no secrets or device addresses in code.

### Testing Requirements

```bash
python -m pytest src/hmi/pilot/test/test_drivers.py src/hmi/pilot/test/test_shell_assets.py -q
```

`test_pilot_browser.py` exercises them end to end.

### Common Patterns

Plain object exports with a `kind` string; pure decision functions kept apart from fetch calls. Comments are Korean or English per file; keep the file's language.

## Dependencies

### Internal

- Used by `../screens/connect.js`, `drive.js`, `arm.js` and `../app.js`; `api_web` serves the files.

### External

None (browser `fetch` only).

<!-- MANUAL: -->
