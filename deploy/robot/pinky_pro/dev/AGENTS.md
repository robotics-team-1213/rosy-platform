<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-24 | Updated: 2026-09-24 -->

# dev

## Purpose

Bench-only CORE overlay (D-179). These files restart `rosy-core` with an allowlisted Python tree. They are not the product install.

## Key Files

| File | Description |
|------|-------------|
| `core_dev_overlay.py` | Allowlist, bind targets, hash check, marker |
| `sync-core-dev.ps1` | Windows upload of that allowlist |
| `apply-core-dev.sh` | On-robot apply |
| `clear-core-dev.sh` | Remove the marker, drop-in, and dev compose file |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- Do not call `install-pi.sh` from here.
- A device with this overlay stays HOLD until `clear-core-dev.sh`.

### Testing Requirements

```bash
python -m pytest test/test_core_dev_sync.py -q
```

### Common Patterns

The apply script finds `core_dev_overlay.py` next to itself.

## Dependencies

### Internal

- A robot that already has `/opt/rosy/deploy/robot/compose.yaml`

### External

- Docker on a development bench, or systemd on a native bench

<!-- MANUAL: -->
