<!-- Parent: ../AGENTS.md -->

# device_test

**Parent context:** `../AGENTS.md`

## Purpose

D-512: an agent session runs a supervised device test on a real Pinky by itself. The tool does the checks, the temporary CORE overlay, the drive, the evidence and the undo; the agent does the peer check (`ListAgents`) and judges the camera frames. Operator PC only; never installed on a robot.

## Tools (D-512)

`run.py` (`--preflight-only`, `--camera-verdict FILE`, `--restore DIR`, `--dry-run` makes no call), `bay_dock.py` (D-512 extension: staging-bay pink-line docking), `tether.py`, `identify.py`, `plan_rules.py`, `live_transport.py`. Exit: 0 pass, 1 expected state/event not seen, 2 aborted or cleanup failed.

## For AI Agents

### Working In This Directory

- Reuse `tools/capture/edge_drive.py` (`Core`, `tls_context`, `rec_start`/`rec_stop`, `front_frame`); do not copy them here.
- Addresses, the site URL, tokens and CA files are command-line or env values (`ROSY_CORE_OPERATOR_TOKEN_FILE`, `ROSY_SITE_URL`, `ROSY_SITE_TOKEN_FILE`). Plans hold no address.
- Raw evidence (frames, JSONL) stays outside the public repo (default `$ROSY_SCRATCH/device-test/`); only `summary.json` with `sha256:` digests and a README go to `docs/validation/<topic>-<date>/`.
- The RobotBody gap in the camera phase is advisory (user decision 2026-10-07); CORE's D-422 stop is authoritative. The camera verdict is the agent's and is a gate.
- Every change the tool makes must have its undo in `cleanup()`, and the undo must run when anything before it failed. Add a fake-robot test for each new change.
- Before the update hold succeeds the robot may be a peer's: send nothing that moves or changes it.
- CORE is the motion authority while the loop stalls (line-follow hold session ≤ 1 s, D-422, teleop watchdog). Keep loop calls at one attempt with a short timeout (`LOOP_CALL_S`).
- New plan overlay keys go into `RULES` (or `WAIVERS` with an `accepted_risks` entry) in `plan_rules.py` with a value rule; a bridge value may only move to the conservative side of its default; never allow a key that turns a safety function off.
- `--restore` reads first and sends nothing unless the hold is ours or gone, line-follow is `OFF` and the overlay digest is the one this run wrote or the original.
- During a retrace (MANUAL `/teleop`) CORE applies only E-Stop, limits and the teleop watchdog; D-422 does not act, so `tether.py`'s rear-gap check (`SCAN_STALE_S`) is the only obstacle stop. Keep it and the real 10 Hz send (`RETRACE_MAX_PERIOD_S`).
- Pre-D-395 robots (odom pose, `localization: null`, e.g. 9dfk): use pixel mode, `tether.pixels {robot_center, robot_front, charger}` on `before_overhead.jpg`; the Fleet active SiteMap must be the calibration's map.
- Tethered driving (2026-10-08): judge from the overhead frame which cable (2 m or 5 m) is plugged in and where its charger is; fill `tether`, run `--tether-check`, set `tether.visual_check_ok: true` only if `tether_check.jpg` matches. `tether_policy` may only be stricter.
- Windows kills are TerminateProcess (no SIGTERM handler): the marker and `--restore` are the only protection then.

### Testing Requirements

```bash
python -m pytest tools/device_test/test tools/capture/test -q -p no:cacheprovider
```

<!-- MANUAL: -->
