<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-08 | Updated: 2026-10-08 -->

# device_test

## Purpose

D-512: an agent session runs a supervised device test on a real Pinky by itself. The tool does the checks, the temporary CORE overlay, the drive, the evidence and the undo; the agent does the peer check (`ListAgents`) and judges the camera frames. Operator PC only; never installed on a robot.

## Key Files

| File | Description |
|------|-------------|
| `run.py` | `--preflight-only` (identity by SSH hostname, health/battery/D-395 localization, overhead Rosy Cam frame via the site Vision lease, robot front/raw frame, LiDAR scan + advisory RobotBody gap, `camera_verdict.json` template), then `--camera-verdict FILE` (fail-closed verdict: digests, `judged_by`, age, pose; D-412 update hold; `RESTORE_PENDING.json` before the first robot write; allowlisted overlay keys, atomic temp-file write validated on the robot, CORE restart shown to read that path without config errors; D-379 recording; CAMERA_LINE under a hold deadman; 10 Hz `status.jsonl` + `events.jsonl`; unlisted stop = abort). Cleanup ignores SIGINT/SIGTERM, runs every step, checks each result, keeps the hold and marker when the restore is not verified. `--restore DIR` finishes a dead run. `--dry-run` makes no call. Exit 0 pass, 1 completed but an expected state/reason/event not seen, 2 aborted or cleanup failed |
| `plan_rules.py` | Plan loading: overlay `ALLOW`/`DENY`, speed cap, `hold_s` ≤ 1 s, stop rules; `sanitize()` for public summary text |
| `live_transport.py` | `Live`: CORE HTTPS (`edge_drive.Core`), key-only SSH returning raw bytes, site Vision lease frame |
| `plans/d476_bridge_9dfk.yaml` | D-476 rev 2 bridge test on 9dfk (overlay `bridge_enabled`, `ir_guard_enabled`, `bridge_site_no_dropoffs`; 120 s / 8 m; expects `RECOVERING` + `lane_bridge`) |
| `test/test_device_test_run.py` | Fake robot (no network, no SSH, virtual clock): phase order, abort/SIGTERM/Ctrl-C in cleanup → OFF/IDLE/revert/release, cleanup failures exit 2, failed restore keeps hold + marker and `--restore` finishes, temp-file/readback/effective-config aborts, peer and invalid holds, verdict gates, pose unknown, unexplained stop, NOT_LOCALIZED, overlay allowlist, sanitized summary, preflight and dry-run make no change |

## For AI Agents

### Working In This Directory

- Reuse `tools/capture/edge_drive.py` (`Core`, `tls_context`, `rec_start`/`rec_stop`, `front_frame`, `advisory`, `lidar_forward_deg`); do not copy them here.
- Addresses, the site URL, tokens and CA files are command-line or env values (`ROSY_CORE_OPERATOR_TOKEN_FILE`, `ROSY_SITE_URL`). Plans hold no address.
- Raw evidence (frames, JSONL) stays outside the public repo (default `X:/DevTemp/device-test/`); only `summary.json` with `sha256:` digests and a README go to `docs/validation/<topic>-<date>/`.
- The RobotBody gap in the camera phase is advisory (user decision 2026-10-07); CORE's D-422 stop is authoritative. The camera verdict is the agent's and is a gate.
- Every change the tool makes must have its undo in `cleanup()`, and the undo must run when anything before it failed. Add a fake-robot test for each new change.
- Before the update hold succeeds the robot may be a peer's: send nothing that moves or changes it.
- CORE is the motion authority while the loop stalls (line-follow hold session ≤ 1 s, D-422, teleop watchdog). Keep loop calls at one attempt with a short timeout (`LOOP_CALL_S`).
- New plan overlay keys go through `ALLOW`/`DENY` in `plan_rules.py`; never allow a key that turns a safety function off.

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
