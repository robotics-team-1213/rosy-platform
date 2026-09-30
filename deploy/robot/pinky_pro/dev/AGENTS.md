<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-24 | Updated: 2026-10-01 -->

# dev

## Purpose

Bench-only tools, never the product install:

- CORE overlay (D-179): restart `rosy-core` with an allowlisted Python tree.
- Compact bench recording: republish the raw front camera as JPEG and record that instead of raw `camera/front` (about 7.6 MB/min instead of 110 MB/min at 320x240, 8 fps).

## Key Files

| File | Description |
|------|-------------|
| `core_dev_overlay.py` | Allowlist, bind targets, hash check, marker |
| `sync-core-dev.ps1` | Windows upload of that allowlist |
| `apply-core-dev.sh` | On-robot apply |
| `clear-core-dev.sh` | Remove the marker, drop-in, and dev compose file |
| `jpeg_relay.py` | Standalone rclpy node: `<ns>/camera/front` (Image) to `<ns>/camera/front/compressed` (JPEG, same header), optional `--max-fps` |
| `rec_compact.sh` | `start <reason>` / `stop` / `status` bench recorder; `rosy.recording.session/1` layout like `~/rosy_rec.sh`, runs the relay beside `ros2 bag record` |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- Do not call `install-pi.sh` from here.
- A device with this overlay stays HOLD until `clear-core-dev.sh`.
- `rec_compact.sh` runs from any copy (e.g. `/tmp`); it finds `jpeg_relay.py` next to itself and changes no service. Values reach `session.json` only through environment variables, never by pasting them into Python.

### Testing Requirements

```bash
python -m pytest test/test_core_dev_sync.py test/test_jpeg_relay.py -q
```

### Common Patterns

The apply script finds `core_dev_overlay.py` next to itself.

## Dependencies

### Internal

- A robot that already has `/opt/rosy/deploy/robot/compose.yaml`

### External

- Docker on a development bench, or systemd on a native bench
- Recorder: ROS 2 Jazzy, `simplejpeg` or `cv2` on the robot; `/etc/rosy/runtime.env` readable via `sudo -n`

<!-- MANUAL: -->
