<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-02 -->

# rosy_dock

## Purpose

Single-file ESP32 sketch: load probe, contact enable, current/voltage sense, fault foldback, Wi-Fi STA from NVS, `GET /status`.

## Key Files

| File | Description |
|------|-------------|
| `rosy_dock.ino` | All firmware: pins 25/34/35/32, thresholds, `setOutput`, HTTP `/status` |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- Pins: `PIN_OUTPUT_ENABLE=25`, `PIN_CURRENT_SENSE=34`, `PIN_VOLTAGE_SENSE=35`, `PIN_LOAD_SENSE=32`.
- Thresholds: load probe 0.25 V, charging current 0.05 A, over-current 3.0 A, over-voltage 8.7 V (2S full is 8.4 V).
- `setOutput` is the only place contacts switch. Faults always call `setOutput(false)`.
- Do not compile Wi-Fi SSID/password into the sketch; use Preferences/NVS.
- Endpoint is port 80, one route, no commands.

### Testing Requirements

`python3 -m pytest test/test_dock_contract.py -v`

### Common Patterns

Debounced load (300 ms), 50 ms sample interval.

## Dependencies

### Internal

- Contract `firmware/dock/README.md` (ROSY-DOCK-001, D-28)

### External

- Arduino.h, WiFi.h, WebServer.h, Preferences.h

<!-- MANUAL: -->
