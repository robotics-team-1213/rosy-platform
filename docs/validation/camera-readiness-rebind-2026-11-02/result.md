# Camera readiness rebind — 2026-11-02

## Scope

Recover the existing photometric readiness service after camera-role changes. This recovery sent no arm or Pinky motion commands. The user reported no person at the power switch, so geometric calibration moves, repeated picks and Pinky re-parking were not run.

## Software evidence

The registry accepts persistent USB-port paths for identical-serial cameras; readiness accepted only by-id paths. Regression commit `feae2ac7b3` produced exactly one expected remote failure for `/dev/v4l/by-path` while by-id passed. Fix `bec3bd9547` accepts both persistent roots and retains all runtime identity, owner, distinct-device and exposure checks.

- Focused remote suites: 59 passed, no skips or failures.
- Affected remote selection: 372 passed, 84 warnings, no new/known/flaky failures.
- Independent source review: no findings on `bec3bd954721a0281b64da986853b9c1e506e3b0`.
- At the 05:14 UTC field-recovery checkpoint, official landing had stopped and resume was refused at 13/12 queue capacity. The improvement was pending then and was **not** used for the field recovery below. Subsequent merge follow-up confirmed `bec3bd9547` is included in local main; this does not claim public publication.

Reports are in the operator's external `rosy-camera-path-red-20261102`, `rosy-camera-path-green-20261102` and `rosy-camera-path-affected-20261102` directories. Additional speculative landing checks are separate from this targeted verification; passing them is not a claim that all other queued changes landed.

## Field configuration recovery

Executed with the existing code from local main `cbfb144767f424f9e082c038fad54f94874ed9a3`. The git-archive snapshot is `omx-tools-cbfb144767`; its camera-readiness source SHA-256 is `c0600495e69d283c8e6fbf6c6bf00220851c8ad2aaedd13f2b40fb42ebfc0b78`. The archive includes foundation for a later viewer restart. No release file was patched in place and no global release pointer was changed.

The wrist uses a declared udev alias matched to the existing registry's exact USB path, VID/PID and video index. Before/after checks proved the same character node and `rdev`, the same sole producer and unchanged controls. All four camera roles matched their registry/environment, had sole owners and resolved to distinct devices. Only the selected video node received a udev change event.

The old readiness profile/environment and entire state were preserved. The new profile uses current producer devices and actual supported controls; the existing 80 ms exposure cap, identity, owner and restoration rules remain intact. The engine generated a new baseline. Private backups are `camera-readiness-alias-20261102T051240Z` and `camera-readiness-migration-20261102T051410Z` on the site host; device identities, filled configuration and full receipts are not published here.

## Observed results

| Check | Result |
|---|---|
| Initial start | READY, three fresh advancing top/front observations |
| Stop restoration | top/front both `restored=true`, empty error lists, original controls verified by readback |
| Restart | READY again, three fresh advancing observations |
| Later independent query | service active/running; all three leases unexpired, READY and photometric_ready |
| Later camera samples | top/front fresh/NORMAL; both sequences advanced in every sample |
| Motion authority | `motion_admitted=false` throughout |
| Camera producer restart | None; PID/invocation identities unchanged |
| Arm/Pinky commands | None |
| Top marker detection | Existing `cell_marks.find` detected zero IDs in each of three frames |

The later receipts are retained in operator-private `camera-readiness-rebind-20261102/live-result.json`. This is camera-control/photometric recovery evidence. It does not establish camera-to-arm accuracy, object visibility for a task, payload safety, successful picks or parking repeatability. Reboot persistence and a subsequent updater transition were not exercised.

## Remaining work

Confirm the required D-933/D-954 markers are attached and detectable, identify the currently applied per-arm camera maps, then run the existing calibration sequence with a supervisor. Fixed-position repeated picks precede the paired Pinky re-parking comparison. Preserve all failed/missing observations and actual work times. Do not infer these results from READY.

CE: existing camera-readiness lesson updated with the verified configuration migration and its limits.
