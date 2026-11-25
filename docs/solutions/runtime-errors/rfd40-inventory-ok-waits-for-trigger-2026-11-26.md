---
title: "RFD40 Inventory OK can mean the reader is waiting for the trigger"
date: 2026-11-26
category: runtime-errors
module: Cell PC RFID input
problem_type: runtime_error
component: rfid_reader
symptoms:
  - "Inventory replies OK over USB or Bluetooth but returns no EPC rows for a previously readable UHF tag."
root_cause: reader_trigger_configuration
resolution_type: configuration_change
severity: medium
tags: [rfid, rfd40, inventory, zeti, bluetooth]
---

# RFD40 Inventory OK can mean the reader is waiting for the trigger

## Problem and cause

The Cell PC could open the RFD40 Premium Plus RFID channel over USB and Bluetooth. The reader returned an inventory header with `Status:OK` and no raw EPC rows. The reader was configured to start inventory when the handheld trigger was pressed and stop it on release. Accepting the inventory command armed the operation.

## Diagnostic and recovery

1. Read the current trigger settings with `st .n` and `ot .n` in the ZETI session. Record the start condition, trigger edge, delay, and repeat setting.
2. When using the physical trigger, arm inventory before asking the operator to press it. Look for `Notification:StartOperation`, raw EPC rows, and `Notification:StopOperation`.
3. To isolate trigger configuration, run a short inventory with handheld start temporarily disabled. The tested reader accepted `st .ip .dr .sd 0`. Abort the scan even if it times out. Restore the recorded settings and read them back. The tested reader originally used press, zero delay, and repeat, restored with `st .sp .tt 0 .sd 0 .ro`.
4. Check for raw EPC rows before changing RSSI thresholds or the Gen2 session. Keep the complete hexadecimal EPC when forwarding a selected reading.

## Continuous reading

On the Cell PC, use the paired reader's address and RFID channel:

```sh
python3 rfd40_cell.py "$RFD40_ADDRESS" --channel "$RFD40_RFID_CHANNEL" --listen --beep-on-read
```

The reader waits for successive press and release cycles on one connection. After a Bluetooth error the adapter opens a fresh session, verifies the trigger configuration, and arms the next scan. Retry delays grow from one to 30 seconds and reset after a working scan. Standard output carries one EPC per accepted cycle. A disconnect during the cycle requires a new trigger pull. Use Ctrl+C to stop.

When Fleet intake and Cell observation credentials are configured, give the outbox the same continuous mode:

```sh
python3 rfd40_cell.py "$RFD40_ADDRESS" --channel "$RFD40_RFID_CHANNEL" --listen --beep-on-read |
  python3 port_event_outbox.py rfid --arm "$ROSY_INTAKE_ARM" --listen
```

Each accepted scan is queued on disk. Fleet delivery retries while the reader is idle, using the original observation reference. The confirmation beep indicates a local read. Check Harbor for receipt.

## Verification

- USB immediate inventory reported the same EPC with S1/A and S0/A+B. Both the session and target changed in the comparison.
- Bluetooth immediate inventory reported three rows for the same EPC as USB. The adapter selected one EPC and the reader acknowledged the beeper commands. Trigger configuration was restored and read back.
- This checks the reader and adapter. Operational Harbor receipt still depends on the Fleet intake decision.

[Zebra RFID trigger events](https://techdocs.zebra.com/dcs/rfid/android/2-0-5-275/guide/event-handling/) · [Zebra ZETI command reference](https://prod-www.zebra.com/content/dam/support-dam/en/documentation/unrestricted/guide/software/rfd8500-dg-en.pdf)
