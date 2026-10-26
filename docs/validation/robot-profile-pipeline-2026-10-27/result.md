# Robot profile pipeline verification

Scope: persistent care records and shared load-characteristics validation, source-bound monitor delivery, robot/Cell information before existing actions. No device movement, service activation, external push or physical load acceptance.

## Verified evidence

- Implementation commit `24c1d225b0`: remote core selection passed (129 cases, exit 0; known-failure classifier NEW 0). Included persistent restart, unique source binding, invalid replacement preservation, duplicate/replayed/future/mismatched reports, concurrent replacement locking, named-operator versus viewer writes, original duplicate-key rejection, real LoadMonitor output through the HTTPS request builder into Fleet and SQLite, and existing characteristics/monitor tests. The delivery helper initially imported the camera bridge and failed without `rosy_vision`; it now uses the standard library and has no camera runtime dependency.
- Local Node: device-profiles and robot-profile-view selections passed 4 cases, including capture-age expiry independent of assessment age. The unconfigured whole-directory Node invocation cannot resolve existing browser absolute imports; it is not a passing full Node suite.
- Independent contract review of commit `8979ce1a63`: no remaining supported material finding after fixing transaction atomicity, raw JSON import, draft preservation and browser evidence aging. Review did not execute tests or accept hardware.
- Local harness lint: 0 errors, 36 existing freshness warnings. ADR index duplicates and obsolete declared gaps from the reused branch were reconciled; no ADR meaning or guard was weakened.

## Browser acceptance and integration

Commit `bf3470f9fe`: real Chromium passed all 10 desktop/mobile and Viewer/Operator cases (exit 0, NEW 0). Robot profiles precede the first app/formation action and ordinary robot controls; opened history survives polling; failed refresh is explicit; editing preserves care drafts across metadata saves; viewer writes are blocked; pages fit 1440px and 390px widths. API replies in browser scenarios are stubbed; the separate producer/API/database test supplies the backend evidence. Screenshots were retained outside the worktree for visual inspection.

The first information-order assertion had a Boolean/bit-mask expression error. After correcting it, Chromium exposed the earlier app/formation action row above the new profile. That row was moved after the profile along with the ordinary robot actions. The assertion still checks the first action row, and the corrected scenario now passes.

Visual inspection of desktop and mobile captures also exposed existing zero-basis action buttons compressing into unreadable narrow columns on mobile. The existing wrapping flex row now uses an 8rem basis; the browser case requires action widths of at least 110px while preserving page width. Commit `8ce8e21139` passed all 6 related real Chromium cases after that correction (exit 0).

The size rule found a one-line growth in the frozen app composer. The isolated local implementation commit was corrected before landing, preserving the same arguments within the prior line count. Rewritten tip commit `be54620204` differs from tested commit `24c1d225b0` only in composer formatting; commit `0359b6981a` adds disclosure preservation and its browser assertion. Subsequent main refresh changed only a pre-existing map panel contract test. Final integration verification is enforced by the local landing gateway.

## Limits and recovery

Care data uses the existing task SQLite backup/restore boundary. Rebinding/removing characteristics invalidates the latest report while keeping bounded history. Report duplicates retain source times and cannot renew freshness. UI/API observations never grant execution authority or clear owner faults. Missing storage or observations stay unavailable. Hardware timing of additional motor-health reads and measured load envelopes still require separate device acceptance.

CE: 해당 없음 — the resolved reasoning is directly represented by code, regression tests and this verification record; no separate lesson is needed.
