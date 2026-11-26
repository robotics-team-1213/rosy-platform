<!-- Parent: ../AGENTS.md -->
# web/ (web_node dashboard UI)

**Parent context:** `../AGENTS.md`

## Purpose
Control-stack diagnostic page served by `robot_web/web_node.py` (installed to `share/control/web/`). It is **not** the operator console (D-77: that is CORE `/dashboard`). D-150 keeps it a debug surface: no operational launch or deploy includes it, and its ports (28181/28182) plus the `web_node` executable are pinned out of deploy configs by `test/test_control_launch_boundary.py`. Launched only from legacy `robot.launch.py`, never from `deploy/robot/pinky_pro/compose.yaml`.

Files: `diagnostic.html` plus `diagnostic.css` and `diagnostic-{core,map,input}.js` (D-766 split; classic scripts sharing one global scope, loaded in that order). `web_http` serves them from `/diagnostic/<name>` (allowlist `DIAGNOSTIC_ASSETS`), `setup.py` installs them, and the backend port reaches the JS through `<meta name="backend-port">`.

## For AI Agents

### Working In This Directory
- Dependency-free on purpose: no framework, build step or webfonts; served from the robot's share dir with no internet.
- **Three regions, not a card stack.** `감지` reports, `관측` is the map hero, `조작` is the only place that moves the robot. Keep anything that commands the robot in `조작`.
- Distances are shown in centimetres against the robot's own body (desk-scale maze: 12 cm stop, 7.6 cm chassis, 2 cm US blind zone). Gauges stay neutral grey and take a status colour only when a threshold is crossed.
- Thresholds come from `state.limits` (`web_node.read_limits` from `config/robot.yaml`, `LIMIT_PARAMS`/`LIMIT_KEYS`), the numbers safety runs on. `CFG.lim` is only the no-safety-node fallback; never hardcode a second copy of a stop distance.
- Flags have polarity: `bad:true` means true is the alarm (cliff, tilt); otherwise true is the good state. Off-states stay rendered.
- The nose bearing is `scan.nose_yaw`, resolved by web_node from the base←scan TF, the same one safety uses. If missing, the page refuses to guess a mount angle (`noseYaw` returns null, `scan_reason` explains).
- Distance gauges use `/safety/*` only; isolated Gazebo labels synthetic sensors via `evidence_scope` and does not invent F/L/R from `/scan`.
- Design tokens live in the `:root` CSS block and the `T` object in the script (keep in sync); the PNG palette in `web_node.render_png` must match the canvas tokens. Red is reserved for status/critical.
- Map view: base-fit composed with user zoom `{z, A}`; pan is clamped to the raster; overlay strokes stay screen-constant (`* dpr`, never `* z`); the robot is a true-scale body circle (`limits.radius`).
- Controls bind via addEventListener (`data-post`, `data-hold`, `data-view`), no inline onclick; element ids are the poll()/draw() contract, so add ids and JS together. Teleop clamps must match web_node's `/teleop`, and `data-post` values must be in its `POST_VERBS`.
- Canvas draw functions must early-return on a zero-size canvas: `tools/test_dashboard_*.cjs` run the IIFE with stub elements.

### Testing Requirements

Dashboard IIFE tests (when present) in `tools/test_dashboard_*.cjs`. Host browser contract: `Rosy OS/test/test_dashboard_browser.py`. Do not require a live robot for HTML structure checks.

<!-- MANUAL: -->
