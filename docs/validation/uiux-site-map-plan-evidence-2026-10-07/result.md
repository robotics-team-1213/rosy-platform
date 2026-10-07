# Fleet site map state and width review — LOCAL

`/console/site-map` was replayed in Chromium at **1440×1000, 390×844, and 320×568** against the current local branch. The fixture backed site-map and robot requests; no robot moved. Screenshots and logs are under `X:/DevTemp/projects/rosy-platform/2026-10-07--site-map-plan-evidence/`.

| D-153 state or task | Three captures (`site-map-<name>-<width>x<height>.png`) | Observed result |
|---|---|---|
| First browser boot | `first-boot` | Access required, no invented map, preview and stop disabled |
| Fresh map and plan | `fresh`, `preview` | Active map and calculated plan shown; preview did not issue a navigation goal |
| Delayed and disconnected read | `delayed`, `disconnected` | Elapsed wait, then a distinct connection failure |
| Unavailable evidence | `map-error`, `robot-state-error` | Map failure named; a failed roster leaves an independently loaded map visible and blocks preview |
| Empty or unregistered | `empty`, `no-robot`, `offline` | Missing map or robot names the next step; unavailable robot cannot be offered for preview |
| Error and denial | `auth-rejected`, `viewer`, `conflict` | Stale map and actions clear; viewer controls are blocked; conflicting draft stays unsaved |
| SAFE_STOP and unknown safety | `safety-stopped`, `safety-unknown` | Robot choice names the state. Route calculation remains explicitly a preview with no execution path in D-488 M1. |
| Irreversible confirmation | `confirm` | Active-map replacement names its effect and shows cancel and confirm actions |

All **48 PNGs** are nonempty. The final-code site-map browser suite passed **50/50**, the capture-only replay passed **15/15**, and D-153 G1 passed **90/90**; each log yielded `known_failures.py` **0 NEW**. Earlier red checks showed that changing a destination left the old route visible and that a late route response restored it after the target changed. The page now clears the route, summary, and action list when the robot, destination, or coordinate target changes, and discards a response from an earlier target. The six stopped or unknown safety checks were also red before the state labels were added.

This covers the D-153 minimum **LOCAL browser** states and declared widths for the site-map route. It does not prove a physical first boot, an installed site candidate, map and robot readback on the site PC, a user's 320px pan and label review, or the eight G3 items. The overall `console` surface and product remain **HOLD**.
