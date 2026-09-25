---
name: rosy-dashboard-drive
description: Use when an agent must operate, verify, or screenshot the Rosy CORE dashboard (/dashboard on a robot, or the local tree's src/hmi/dashboard) with Playwright — changing mode, hold-to-drive teleop, measuring stop latency, reading safety/commissioning/hardware state, checking the device card — or when a Playwright script hangs on page.goto, a mode click does nothing, or teleop buttons stay disabled.
---

# Driving the CORE dashboard with Playwright

## Overview

Use `tools/dashboard_drive.py` first; write a custom script only for what it does not
cover, and then copy its patterns. Four dashboard facts break naive scripts:

| Fact | Consequence |
|---|---|
| The token lives in `sessionStorage['rosy.dashboard.token']` | Inject it with `page.add_init_script` **before** `goto`, not by typing into `#token-input` |
| The page polls and streams forever | `goto(..., wait_until="load")`. `networkidle` never settles and times out |
| Mode changes (and Cyclone apply) go through `window.confirm` | Register `page.on("dialog", lambda d: d.accept())`, or the click is silently cancelled |
| Teleop is hold-to-drive on `pointerdown`/`pointerup` | `click()` sends one tick and a stop. Use `hover()` + `mouse.down()` … `mouse.up()` |

Get a token first: **rosy-device-access** (`sudo rosy-login-code --role administrator`, pair,
log out afterwards). Keep the token in a file under `X:\DevTemp`, never in the repo.

## The tool

```bash
T="--base-url http://<robot-ip>:8080 --token-file X:/DevTemp/rosy.token"
python tools/dashboard_drive.py $T status                       # robot/safety/commissioning/hardware JSON
python tools/dashboard_drive.py $T mode MANUAL                  # exit 1 if the robot did not follow
python tools/dashboard_drive.py $T teleop --direction forward --seconds 1.0
python tools/dashboard_drive.py $T screenshot --view inspect --out X:/DevTemp/inspect.png
```

`teleop` prints velocity samples while held and `stop_latency_s`: time from release until
`/api/v1/robot/state` reports zero velocity. **Wheels lifted** and a person at the robot
before any teleop (motor mode: rosy-hw-bringup). Hold is capped at 5 s.

## Element map

| Element | Selector |
|---|---|
| Mode buttons | `.mode-control [data-mode="IDLE"\|"MANUAL"\|"NAVIGATION"]` (other `data-mode` chips exist) |
| Shown mode | `#robot-mode` |
| Bench safety tick (teleop gate) | `#bench-safety-confirmed` |
| Teleop pad | `[data-teleop="forward"\|"backward"\|"left"\|"right"]` |
| Views | `#view-operate`, `#view-inspect` |
| Device card (D-247) | `#hardware-card` (inspect view) |
| Teleop reason line | `#teleop-message` — read it when buttons stay disabled |

Teleop is enabled only when: token set, `capabilities.teleop`, mode `MANUAL`, no E-Stop,
fresh pose/velocity evidence, and the bench tick. In `core` runtime mode it never enables —
`#teleop-message` shows the `motion_reason`.

## Read-only APIs worth reading directly

`GET /api/v1/robot/state`, `/api/v1/safety/state`, `/api/v1/host/commissioning`
(`runtime_mode`, `motion_reason`), `/api/v1/host/hardware` (device rows). Viewer role is
enough. `POST /api/v1/host/hardware/refresh` is administrator-only.

## Render the local tree without a robot

`test/test_dashboard_browser.py::_launch_page(playwright, extra_init=...)` serves
`src/hmi/dashboard` at `http://rosy.test/dashboard` with a mocked API. Override the mock in
`extra_init`, for example a recorded device result:

```python
from test_dashboard_browser import _launch_page     # run from test/ on sys.path
hw = json.load(open("X:/DevTemp/hardware-api.json", encoding="utf-8"))  # GET /api/v1/host/hardware body
browser, page = _launch_page(p, extra_init=f"window.__rosyHardware = {json.dumps(hw)};", width=1366, height=900)
page.goto("http://rosy.test/dashboard", wait_until="load")
```

Other hooks: `window.__rosyStateOverrides`, `__rosyInfoOverride`, `__rosyCapabilitiesOverride`,
`__rosyCommissioningOverride`. Use this for UI checks instead of dev-overlaying `main` onto
an older release. `test/test_dashboard_drive.py` runs the tool against these fixtures.

## Common mistakes

- `wait_until="networkidle"` → 30 s timeout on every load.
- `page.click('[data-mode=IDLE]')` without a dialog handler → nothing is sent.
- Asserting the mode from `#robot-mode` right after the click → read `/api/v1/robot/state` until it changes.
- Browser tests: `ROSY_RUN_BROWSER_TESTS=1 python -m pytest test/test_dashboard_browser.py`; they skip without it.
