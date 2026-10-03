<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-02 | Updated: 2026-10-02 -->

# web

## Purpose

Static Fleet console UI (vanilla ES modules, no build step), served at `/console/assets/*`. It talks only to the Fleet server (`/api/fleet/*`), never to a robot API directly. `__init__.py` makes the folder a package so it ships with the install.

## Key Files

| File | Description |
|------|-------------|
| `index.html` | Shell; loads shared `/common/` tokens, theme, components and `ui.js`, then `console.js` |
| `styles.css` | Console styles (shared tokens come from `/common/tokens.css`, not this folder) |
| `console.js` | Shell: token, polling cadence, click-to-goal; composes the modules below |
| `map-view.js` | Site map grid, coordinate transforms, robots, goals, overlays |
| `roster.js` | Robot cards and attention/intervention queues |
| `formation.js` | Formation panel |
| `signals.js` | Traffic-signal cards |
| `site-layer.js` | Ceiling-camera sightings layer (pure; display and cross-check only) |
| `vision-view.js`, `field-view.js`, `field-layers.js` | Camera preview, field proposal/rectified view, layer toggles |
| `map-fit.js`, `map-fit-view.js` | D-375 lane-paint map fit proposal (pure math / view) |
| `enrollment.js`, `camera-pairing.js` | Robot enrollment (D-361) and camera pairing approval (D-341) panels |
| `address-drift.js`, `localization-badge.js`, `poll-gate.js`, `authorization.js` | Pure helpers: address drift text, localization badge, 404 poll gate, role-lock reasons |
| `package.json` | `{"type": "module"}` so node can run the tests |

## For AI Agents

### Working In This Directory

- CSP is `style-src 'self'; script-src 'self'` (`static_routes.py` `CONSOLE_CSP`): no inline scripts, no `style=` attributes, no `el.style.x =`. Express colour and layout with classes.
- A new asset must be added to the allowlist in `../static_routes.py`; unlisted files are not served.
- Robot pose is in the shared `map` frame (TF `map` to `<ns>base_footprint`); never introduce per-robot map frames in the drawing code.
- Keep DOM-free logic in pure functions (the `*-view` / `createXPanel` files wire the DOM) so node tests cover it. Sightings and proposals are display-only: never feed them into goals or `cmd_vel`.
- Do not call CORE directly or hold robot tokens in the browser.

### Testing Requirements

```bash
node --test src/site/fleet/test/web/
python -m pytest src/site/fleet/test/test_server_app.py src/site/fleet/test/test_console_palette.py src/site/fleet/test/test_console_disabled_features.py -q
```

`node --check <file>.js` is a quick syntax check.

### Common Patterns

Factory functions (`createMapView`, `createFormation`, ...) return handlers the shell wires; operator-facing strings are Korean.

## Dependencies

### Internal

- `../static_routes.py` (allowlist, CSP), `../app.py`, `src/hmi/web_common` (`/common/` assets)

### External

- None at runtime (browser only); node for tests
