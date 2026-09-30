<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-24 | Updated: 2026-09-30 -->

# dev

## Purpose

Bench-only CORE overlay (D-179). These files restart `rosy-core` with an allowlisted Python tree. They are not the product install.

`install-learned-perception.sh` (D-373) is the recorded bench install of the learned-perception image layer on a card baked before it.

## Key Files

| File | Description |
|------|-------------|
| `core_dev_overlay.py` | Allowlist, bind targets, hash check, marker |
| `sync-core-dev.ps1` | Windows upload of that allowlist |
| `apply-core-dev.sh` | On-robot apply |
| `clear-core-dev.sh` | Remove the marker, drop-in, and dev compose file |
| `install-learned-perception.sh` | D-373 bench install: `../image/learned-perception-requirements.txt` (hash from `inputs.lock.yaml` `learned_perception_runtime`) with `pip --target /opt/rosy/learned-perception/site-packages`, the `tmpfiles-rosy-state.conf` models rule, a line in `/var/log/rosy/bench-installs.log` |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- Do not call `install-pi.sh` from here.
- A device with this overlay stays HOLD until `clear-core-dev.sh`.
- `install-learned-perception.sh` reads pins and directory rules from `../image` and `../native`; never copy a pin, mode, or owner into it.
- `install-learned-perception.sh` never writes `/usr/local` and never touches `python-runtime.sha256`: the payload runtime id stays the flashed one, so every card keeps taking payloads with or without it.

### Testing Requirements

```bash
python -m pytest test/test_core_dev_sync.py test/test_bench_learned_perception.py -q
```

### Common Patterns

The apply script finds `core_dev_overlay.py` next to itself.

## Dependencies

### Internal

- A robot that already has `/opt/rosy/deploy/robot/compose.yaml`

### External

- Docker on a development bench, or systemd on a native bench

<!-- MANUAL: -->
