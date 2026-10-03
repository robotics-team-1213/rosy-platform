<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-24 -->

# dock

## Purpose

Charging-dock firmware and the ROSY-DOCK-001 agent contract. The microcontroller exists first to **not energise bare floor contacts** without a load; current reporting is secondary. The robot polls `GET /status`; the dock never initiates a connection (local-first, no inbound robot API).

## Key Files

| File | Description |
|------|-------------|
| `README.md` | ROSY-DOCK-001: `/status` schema, electrical/mechanical, firmware rules |
| `progress.md` | Current gate snapshot (SOURCE…FIELD). Overwrite; state of record over this file |
| `logs.md` | Append-only work journal, one entry per change |
| `index.md` | Generated: ADRs, plans, solutions, tests, recent logs. Do not edit |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `firmware/` | ESP32 Arduino sketch (see `firmware/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- Harness (D-61): read `progress.md` and `index.md` first. After a change, append `logs.md`, overwrite `progress.md` if a gate moved, then run `python tools/harness/rosy_harness.py generate` from the repo root.
- Required `/status` fields: `load_present` and `charging`. Missing is an error, not `false`.
- Robot confirmation also requires pack voltage not falling (`docking/charging.py`). Dock `charging: true` alone must not suppress D-27 shutdown.
- Wi-Fi credentials must not appear in sources; `test/test_dock_contract.py` fails the build if they do.
- Read-only HTTP, no command surface. Adding actuation requires revisiting auth.
- Robot docks forwards (IR + ultrasonic face +X).

### Testing Requirements

```bash
python3 -m pytest test/test_dock_contract.py src/runtime/services/test/test_docking.py -v
```

### Common Patterns

Contract in README; implementation in `firmware/rosy_dock/rosy_dock.ino`; client in `core_features.docking.agent`.

## Dependencies

### Internal

- `src/runtime/services/core_features/docking/agent.py`
- Design: `docs/plans/2026-09-02-docking-station-design.md`

### External

- ESP32 Arduino core (WiFi, WebServer, Preferences/NVS)

<!-- MANUAL: -->
