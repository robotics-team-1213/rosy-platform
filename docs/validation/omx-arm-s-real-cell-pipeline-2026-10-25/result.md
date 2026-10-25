# Arm S real runs: guard teacher mode, coarse map, autonomous grasps, stops — 2026-10-25

Supply arm S on the Fleet PC, a person at the power switch for every motion. Tools ran from test copies of the branch (`~/rosy-test/omx-tools-<sha>`); each was tested remotely before it reached the cell. The arm is driven only by `chunk_runner` inside `record_session.py --chunks`, through the guard's teacher mode (D-872 §2.1). Frames in `evidence/` are 320×240 copies of the cell's top and wrist cameras.

## What worked

| Step | Evidence |
|---|---|
| Guarded session, rise-turn-descend travel at the guard's speed | `goto above_pick` ~157 s, settled, no fault ([02](evidence/02-above-box-top.jpg), [03](evidence/03-above-box-wrist.jpg)) |
| Coarse top-camera map by the jaws | the empty jaws visited 5 known points 10 cm up; opening and closing them marked the jaws in the top view at every point |
| Autonomous grasps from the coarse map | 3 grasps, all judged holding by jaw position and current (189, 201, and one more ~200 mA) |
| Reset to the start | the arm placed the box at its start point; the measured start pixel (160, 215) was recorded as a candidate beside the taught reference |
| Recovery | 4 remote recoveries, 3 after guard stops and 1 after the jaw stall (seed at the present pose, lift, place or park), all `safe_end` with torque off and caps restored |

## What stopped, and what changed

| # | Stop | Cause | Change |
|---|---|---|---|
| 1 | Guard: stale motor-health sample (0.62 s) while holding over the box ([05](evidence/05-guard-stop-resting-on-box-top.jpg)) | a bus read stalled the loop; the runner's own health reads doubled bus traffic beside the guard's | runner reads health once a second (`HEALTH_PERIOD_S`); lesson `docs/solutions/runtime-errors/omx-guard-stale-health-sample-drops-held-arm-2026-10-25.md` |
| 2 | Jaws pushed at the PWM cap when asked to close to 40 | the follower jaws end at 48.5; the taught closed value 46.6 is a leader value | runner never asks below the taught closed value; the pipeline waits for the jaws to stop, and the measured end competes with the taught value in the choices ledger |
| 3 | Reset judged "off the start" twice after correct placements | the taught top reference belongs to the taught replay, not to the top-down plan (about 4 cm apart) | start reference per plan, chosen by outcome (taught 0/1, measured 1/1) |
| 4 | Guard: wrist following error placing at a grid point ([06](evidence/06-contact-stop-box-in-jaws-top.jpg), [07](evidence/07-contact-stop-box-in-jaws-wrist.jpg)) | the box's edge overhung the Pinky frame | grid points checked against the tray's flat zone (half a box inside) before the arm goes; grid centred on that zone, 10 mm spacing; affine map instead of a homography |
| 5 | Guard: wrist following error descending to grasp ([09](evidence/09-yaw-turn-contact-top.jpg)); the box later left the tray ([10](evidence/10-box-off-tray-top.jpg)) | a 25° yaw read from a 30 px box turned the jaws onto its corners | grasp yaw is a ledger choice (site yaw vs camera turn), the turn capped at 10° until the wrist view is learned |

Every guard stop is a torque-off with the arm extended. To keep that from being the first response to contact, `chunk_runner` now holds with torque on when a joint lags the guard's sent command by 1.5 units for 2 ticks during descend/grasp/release, retreats along the path it came and parks (`retreat`); the pipeline logs the case and the judge seat decides a retry. `cell_pipeline --stage recover --person-at-switch` codifies the recovery done by hand four times. Decisions now keep the frames they used next to the receipts.

## Not shown

- A full calibration of the tray or belt on the real arm (3 of 8 tray points measured before stop 4).
- An A/B cycle by the pipeline on the real arm.
- The soft contact stop on the real arm (remote tests and a mutation check only).
- The third camera service (`arm_a_wrist`) has no device on this PC; the LG camera is the laptop's own; rosy cam watches the site, not this cell.

Logs, receipts, the choices ledger and full-size frames stay on the Fleet PC under `~/rosy-test/omx-record-prep-20261019/` (`session-guard-*.log`, `motor-health-*.jsonl`, `cell-pipeline/receipts/`, `cell-pipeline/choices.json`, `judge-frames/`).
