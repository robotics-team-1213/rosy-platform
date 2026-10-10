<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-07 | Updated: 2026-10-07 -->

# capture

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-07

## Purpose

Robot side of the edge-capture loop: short supervised drives over the CORE API that record a Pilot session for pixel drafts (D-379, D-465). Runs on the operator PC with the operator at the robot and Fleet watching. The data side is `learning/training/perception/dataset/edge_capture_session.py`; the whole run order is in `learning/training/perception/dataset/AGENTS.md` ("Edge-capture loop").

## Key Files

| File | Description |
|------|-------------|
| `edge_drive.py` | `nudge` (MANUAL teleop within 0.08 m/s, 0.6 rad/s, 4 s, then IDLE and save the front and raw frames), `drive` (recording + CAMERA_LINE under a 1 s hold deadman until a stop reason, 3 s still or `--max-s`), `rec start|stop`, `cam-watch` (raw frames + road-band clipping). One kept-alive HTTPS connection; Operator token from `--token-file` or `ROSY_CORE_OPERATOR_TOKEN_FILE`; `--ca-file` or an explicit `--insecure` |
| `ceiling_record.py` | D-563 3: site ceiling camera beside a collection drive. Leases the Rosy Cam preview, saves raw frames + `frames.jsonl` (`seq`, `captured_at` site clock, `saved_at`), snapshots the approved tracking calibration (`map_to_image`, lens) once. Site URL/token from `--site`/`--token` or `ROSY_SITE_URL`/`ROSY_SITE_TOKEN` |
| `test/test_edge_drive_advisory.py` | Body advisory on synthetic scans, LiDAR angle source order, a warned nudge still drives and ends with zero + IDLE |

## For AI Agents

### Working In This Directory

- The RobotBody check before a nudge is advisory (user decision 2026-10-07): it prints `WARN` and the robot moves anyway. CORE's own stop stays authoritative. Do not turn it into a gate without the user.
- The LiDAR forward angle is the URDF nominal (`core_common.robot_body.PINKY_PRO`), refined by the device's accepted `lidar_mount` record in `data/calibration/` (`--device`), overridden by `--lidar-forward-deg`. No hard-coded per-robot angle.
- Robot addresses, tokens and CA files go on the command line or in env only; examples use `<robot-ip>`.

### Testing Requirements

```bash
python -m pytest tools/capture/test -q -p no:cacheprovider
```

## Dependencies

### Internal

- `contracts/foundation/core_common` (`robot_body`, `calibration_store`)

### External

- `opencv-python`, `numpy` for `cam-watch` only

<!-- MANUAL: -->
