<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-08 | Updated: 2026-10-08 -->

# device_test

## Purpose

D-512: an agent session runs a supervised device test on a real Pinky by itself. The tool does the checks, the temporary CORE overlay, the drive, the evidence and the undo; the agent does the peer check (`ListAgents`) and judges the camera frames. Operator PC only; never installed on a robot.

## Key Files

| File | Description |
|------|-------------|
| `run.py` | `--preflight-only` (identity by SSH hostname, health/battery/D-395 localization, overhead Rosy Cam frame via the site Vision lease, robot front/raw frame, LiDAR scan + advisory RobotBody gap, `camera_verdict.json` template), then `--camera-verdict FILE` (fail-closed verdict: digests, `judged_by`, age, pose; D-412 update hold; `RESTORE_PENDING.json` before the first robot write; allowlisted overlay keys, atomic temp-file write validated on the robot, CORE restart shown to read that path without config errors; D-379 recording; CAMERA_LINE under a hold deadman; 10 Hz `status.jsonl` + `events.jsonl`; unlisted stop = abort). Cleanup ignores SIGINT/SIGTERM, runs every step, checks each result, keeps the hold and marker when the restore is not verified. `--restore DIR` finishes a dead run. `--dry-run` makes no call. Exit 0 pass, 1 completed but an expected state/reason/event not seen, 2 aborted or cleanup failed |
| `plan_rules.py` | Plan loading: exact overlay `RULES` (value rules, bridge values only more conservative than defaults), `WAIVERS` that need an `accepted_risks` entry, fixed `OVERLAY_PATH`, `hold_s` ≤ 1 s; `check_verdict()`; `sanitize()` walks summary values (keeps `sha256:`, recording and release ids) |
| `tether.py` | D-512 개정 1 tether guard: `check()` of the verdict `tether` (`cable_m` in `CABLES_M` 2.0/5.0, `charger_robot_frame` [forward_m, left_m] of the charger at capture, `how`; charger within `cable_m - margin_m` at start; `cable_attached` without a tether refused; `visual_check_ok` true for the values `tether_check.jpg` showed). `tether_check()` (`run.py --tether-check VERDICT --plan PLAN`, no robot call): approved site calibration `map_to_image` (`GET /api/fleet/calibrations`) for the overhead source and frame size, localized map capture pose, else refused; draws charger, radius circle, robot + heading into `tether_check.jpg`, records its digest and a value binding in the verdict. `Guard.tick()` each drive tick: `trail.jsonl` (pose samples ≥ 1 cm), charger placed in the start pose, unwrapped cumulative yaw. Over the radius or `max_turn_deg`: line-follow OFF confirmed, MANUAL, reverse along the recorded trail (pure pursuit, `RETRACE_SPEED` 0.03 m/s, `RETRACE_MAX_ANG`) under the RobotBody rear gap until slack (`|turn| ≤ max_turn − 90`, distance ≤ limit − 0.1 m) or the trail start; pose gap, estop, mode change, off-trail > `RETRACE_TOL_M`, rear block, teleop refusal, `STOP` file, `RETRACE_MAX_S` stop it (zero + IDLE). Always an abort (exit 2) |
| `identify.py` | D-512 amendment 2: `--tether-check` proves the drawn robot is the target. 4 s of baseline overhead frames (a blob that already changes there is refused), `POST /host/lamp/identify` (one wait + retry on 429), frames every 0.2 s for 6 s; per-pixel change > 60 joined within 15 px into blobs ranked by frames changed; the strongest (≥ 3 frames) and every blob with ≥ half its frames must lie within 1.5 × RobotBody rotation radius (px at the calibration scale) of the drawn robot, else refused (also 404, `IDENTIFY_COLOR_UNSET`). Evidence in `tether.identity` (request id, colour, blob bbox, pixel count, distance, `identify_NN.jpg` digests) Blobs off the floor (calibration `track_bounds_m` projected, no margin) are recorded as `off_floor`, not judged (2026-10-10); so are blobs away from the pick that already changed in the baseline (`background`). |
| `live_transport.py` | `Live`: CORE HTTPS (`edge_drive.Core`), key-only SSH returning raw bytes, site Vision lease frame, overhead source id, approved camera-to-map calibrations |
| `plans/d476_bridge_9dfk.yaml` | D-476 rev 2 bridge test on 9dfk (`abort_on_events: safety.*` with `ok_events: [safety.policy_off]`, the only name `plan_rules.OK_EVENTS` allows; overlay `bridge_enabled`, `ir_guard_enabled`, `site_floor_map_id: map_v2_fleet`; `tether_policy` 0.3 m / 360°; 120 s / 8 m; expects `RECOVERING` + `lane_bridge`) |
| `test/test_device_test_run.py` | Fake robot (no network, no SSH, virtual clock): phase order, abort/SIGTERM/Ctrl-C in cleanup → OFF/IDLE/revert/release, cleanup failures exit 2, failed restore keeps hold + marker and `--restore` finishes, temp-file/readback/effective-config aborts, peer and invalid holds, verdict gates, pose unknown, unexplained stop, NOT_LOCALIZED, overlay allowlist, sanitized summary, preflight and dry-run make no change; tether: charger transform, overlay pixels from a known homography, `--tether-check` drawing and fail-closed paths, visual check required for the current values, radius/turn trip (unwrap across ±π) with retrace, trail end, rear block, pose gap, off-trail, no motion before OFF, declaration gates, policy bounds |

## For AI Agents

### Working In This Directory

- Reuse `tools/capture/edge_drive.py` (`Core`, `tls_context`, `rec_start`/`rec_stop`, `front_frame`, `advisory`, `lidar_forward_deg`); do not copy them here.
- Addresses, the site URL, tokens and CA files are command-line or env values (`ROSY_CORE_OPERATOR_TOKEN_FILE`, `ROSY_SITE_URL`, and `ROSY_SITE_TOKEN_FILE` for the read-guarded Fleet calibration and site-map routes). Plans hold no address.
- Raw evidence (frames, JSONL) stays outside the public repo (default `X:/DevTemp/device-test/`); only `summary.json` with `sha256:` digests and a README go to `docs/validation/<topic>-<date>/`.
- The RobotBody gap in the camera phase is advisory (user decision 2026-10-07); CORE's D-422 stop is authoritative. The camera verdict is the agent's and is a gate.
- Every change the tool makes must have its undo in `cleanup()`, and the undo must run when anything before it failed. Add a fake-robot test for each new change.
- Before the update hold succeeds the robot may be a peer's: send nothing that moves or changes it.
- CORE is the motion authority while the loop stalls (line-follow hold session ≤ 1 s, D-422, teleop watchdog). Keep loop calls at one attempt with a short timeout (`LOOP_CALL_S`).
- New plan overlay keys go into `RULES` (or `WAIVERS` with an `accepted_risks` entry) in `plan_rules.py` with a value rule; a bridge value may only move to the conservative side of its default; never allow a key that turns a safety function off.
- `--restore` reads first and sends nothing unless the hold is ours or gone, line-follow is `OFF` and the overlay digest is the one this run wrote or the original.
- During a retrace (MANUAL `/teleop`) CORE applies only E-Stop, limits and the teleop watchdog; the D-422 body stop does not act, so `tether.py`'s rear-gap check on fresh scans (`SCAN_STALE_S`) is the only obstacle stop. Keep it, and keep the real 10 Hz send (`RETRACE_MAX_PERIOD_S`).
- Pre-D-395 robots (odom pose, `localization: null`, e.g. 9dfk): use pixel mode, `tether.pixels {robot_center, robot_front, charger}` as [u, v] on `before_overhead.jpg` instead of `charger_robot_frame`; `--tether-check` computes the charger from the inverted calibration and the Fleet active SiteMap must be the calibration's map.
- Tethered driving (user decision 2026-10-08): per run, judge from the overhead frame which cable (2 m or 5 m) is plugged in and where its charger is (the radius is measured from the charger, not the wall outlet), relative to the robot's pose at capture (forward/left metres), and fill `cable_attached` and `tether {cable_m, charger_robot_frame, how}` in the verdict. Then run `--tether-check`, look at `tether_check.jpg` and set `tether.visual_check_ok: true` only if the red charger dot, the yellow radius and the green robot match the picture; change a value and the check must be run again. `cable_in_path_or_wheels: true` then means that tether; a foreign cable in the path is `path_clear: false`. `tether_policy` in a plan may only be stricter (`margin_m` ≥ 0.2, `max_turn_deg` ≤ 360).
- Windows kills are TerminateProcess (no SIGTERM handler): the marker and `--restore` are the only protection then.

### Testing Requirements

```bash
python -m pytest tools/device_test/test tools/capture/test -q -p no:cacheprovider
```

## Dependencies

### Internal

- `tools/capture/edge_drive.py`, `contracts/foundation/core_common` (`robot_body`, `calibration_store`)
- Robot: `/opt/rosy/native-runtime/rosy_auto_update.py` (hold), `rosy-core.service` (HOME `/var/lib/rosy/core`)
- Site: `POST /api/fleet/vision/lease`

### External

- `PyYAML`; OpenSSH client with the operator key (`rosy-device-access` skill)

<!-- MANUAL: -->
