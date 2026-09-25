<!-- Parent: ../../AGENTS.md -->
<!-- Generated: 2026-09-21 | Updated: 2026-09-21 -->

# rosy_signal

## Purpose

Single-file ESP32 sketch: fail-safe mode state machine (failsafe/manual/cycle/hold/all_red/flash_red), heartbeat timeout, conflict guard, token auth, serial provisioning, Wi-Fi STA from NVS, `GET /status` + `POST /command`.

## Key Files

| File | Description |
|------|-------------|
| `rosy_signal.ino` | All firmware: lamp pins 25/26/27 (spare 16/17), `writeLamps`, `enterFailsafe`, `handleCommand` |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- Pins: `PIN_LAMP_RED=25`, `PIN_LAMP_YELLOW=26`, `PIN_LAMP_GREEN=27`, spares 16/17. Relay channels are active-HIGH; module inputs must be biased so boot Hi-Z cannot close a contact (README "Electrical").
- Boot state is `Mode mode = FAILSAFE` — the first statement of `setup()` drives all lamp pins LOW. Do not reorder.
- `writeLamps` is the only place lamp pins switch. `enterFailsafe` sets `mode=FAILSAFE` + fault; the flash pattern emerges from `applyOutputs`.
- `HEARTBEAT_TIMEOUT_MS = 10000` — only token-valid requests (`X-Rosy-Token`) credit `lastContactMs`. An unauthenticated GET is debug-read-only and does not credit the heartbeat.
- `handleCommand`: 403 unauthorized → 400 bad_json/bad_mode/bad_lamps/bad_cycle → 409 stale_seq → 400 conflict (red+green). A fresh accepted command clears faults.
- No lamp state in NVS. NVS holds `ssid`, `key`, `token`, `id` only, provisioned over serial when empty, then restart.
- Explicit prototypes sit above the enum — the .ino auto-prototyper fails on custom enums otherwise. Keep them in sync.
- Do not compile Wi-Fi SSID/key or the command token into the sketch.

### Testing Requirements

`python3 -m pytest test/test_signal_contract.py -v` — host pytest, no hardware.

### Common Patterns

Fail-safe flash at 500 ms (`FLASH_INTERVAL_MS`); 20 ms tick; cycle phases green→yellow→red from `phaseStartMs`.

## Dependencies

### Internal

- Contract `firmware/signal/README.md` (ROSY-SIGNAL-001 Draft)

### External

- Arduino.h, WiFi.h, WebServer.h, Preferences.h, ArduinoJson 6.x

<!-- MANUAL: -->
