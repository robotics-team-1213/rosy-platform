# Original pack energy implementation — verification pending

Date: 2026-10-17. Latest source revision: `e5f51f5c7bb4cd30e90f2968ad1efb6b75bd6659`; initial implementation: `ba4868ef59d7ee4f36e6b369c0d7dfb3c074979c`. Baseline: `04ffe7aff7a49032bec28289bab80f28f9294c5c`. User scope excludes simulator execution. This record does not establish runtime, device or field acceptance.

## Implemented path

The private native composition now requires an installed original energy source before accepting a parent. The source retains exact provider/profile identity, pack/epoch/capacity revision, original sequence/header/source-now, calibrated remaining usable Wh lower bound, SOC/SOH/temperature/fault and conservative monotonic capture/expiry. It does not infer usable energy from display voltage, SOC or nameplate capacity. Actual vendor/calibration support remains unknown.

CORE serializes ingestion and publishes immutable facts under modes→ledger after releasing source locks. A pending read blocks a new parent. Existing motion can use its prior finite proof while parsing proceeds. Low energy or invalid/fault publication requests and commits STOP for the exact captured parent before replacing the cache. A later higher measurement does not revive that parent. One raw writer already inside the boundary may finish before a waiting publication; this is not cancellation or measured physical stop.

The full-window check covers whole-device power from the original measurement capture to the original parent's fixed end, plus immutable profile reserve. It includes waiting across parents and preserves the original Budget. Both the selected original receipt and latest published receipt must remain sufficient/fresh. Up to eight unexpired published receipt identities are retained; overflow closes instead of evicting a potentially live selection.

Scope changes, expiry, source-clock reversal and insufficient energy cannot reset a consumed parent. Failed initial admission returns no handle while consuming its original attempt. Existing metadata-only Fence tests remain a separate path; an installed native owner cannot choose an energy-free option.

## Static review and local checks

An independent read-only safety reviewer traced source→ingress→publication→native admission→selection/final writer before the first safety source commit. Review first found missing source/Ledger clock-domain binding. Installation, publication and final checks now require the exact same trusted Ledger clock callable. A subsequent source-now reversal check was moved before header validity checks so a future header cannot conceal observed clock reversal. Offset/epoch and both reversal orders have explicit regression oracles.

A subsequent internal `EnergyContext.publish` to `finish` rename avoids the existing event scanner treating a non-event handover as an emit; its sole caller and arguments/ordering are unchanged, with separate independent scoped static PASS. Scanner and allowlists are unchanged.

Final review: **scoped static PASS**. Commit carries the corresponding `Safety-Review:` trailer. This is not an execution-test waiver or a hardware/profile approval.

| Check | Observed result |
|---|---|
| Parse changed Python source and tests with AST | Passed; no source execution |
| `git diff --check` | Passed |
| `rosy_harness.py lint` on committed source | 0 errors, 33 warnings; no gate promotion |
| `safety_review.py 04ffe7aff7a49032bec28289bab80f28f9294c5c e5f51f5c7` | 2 commits checked, exit 0 |
| `size_range.py 04ffe7aff7a49032bec28289bab80f28f9294c5c e5f51f5c7` | 2 commits checked, exit 0 |
| Affected selection | FULL due manifest change; full CI remains unexecuted |

## Execution status

The earlier official non-simulator pytest request on baseline `04ffe7aff` exhausted its default 600-second retry with all three configured hosts unreachable, exit 1. Tests did not run; no `run-1.txt`, collection count, behavioral RED, PASS count or known-failure comparison exists for that invocation.

Source request terminal result: exit 1 after the default 600-second no-host retry. All three configured hosts were unreachable. Tests did NOT RUN: no collected/executed/skipped count, no behavioral RED/GREEN, no run-1.txt or known-failure comparison. The later naming-only source commit also remains unexecuted. All tool jobs are terminal.

The source execution request uses `remote_pytest.py --sha ba4868ef59` and the external log target `C:/DevTemp/station-charge/pack-energy-nosim-source`. It requests 15 explicit targets: original energy, Budget and Ledger units; actual native manager, map, original map/odom/bootstrap and writer Fence integration; safety separation, behavior-test ownership, module structure, C6/event and harness guards. It uses unchanged official placement with the configured hosts, including Fleet/site only if D-568 permits after reserves, busy checks and CPU/memory limits. No forced placement or local pytest is used. That invocation requests the initial implementation SHA and does not cover the later naming-only commit; latest source also remains unexecuted. No additional identical no-host retry was started solely for the rename; execute latest committed HEAD after connectivity is restored.

The new tests are oracles, not proven coverage until execution: changed/replayed/expired originals, clock reversal, unsafe/missing pack facts, whole future window and strict reserve, pending admission, cap overflow, decoder cleanup, selected deadline, low→higher irreversible STOP and publication after an already-entered writer. Prewritten tests were not observed failing before implementation because hosts were unavailable. The user's request to continue the remaining non-simulation work was interpreted to permit reversible implementation with verification pending; fail-first execution compliance is not claimed.

## Remaining acceptance

- Execute the committed regression targets and required FULL CI when an approved test host is reachable; inspect actual failures, skips, logs and known-failure comparison.
- Supply and accept a real BMS/fuel-gauge port, calibrated remaining-energy lower bound, capacity revision and measured whole-device power/reserve/clock/freshness envelope. Check source rate/TTL against the eight-receipt bound. Display battery health is not that adapter.
- Complete actual Fleet work/return-cost, approved map/geometry/native adoption and CORE HTTP/StationOwner factory binding. Existing `build_station_owner` rejects every non-simulation runtime; a hardware composition remains to be implemented and accepted. This change does not open an operational arming route.
- Follow the [attended station runbook](../../deployment/station-charge-attended-runbook.md) for actual camera/pose/charger/contact/stop evidence, three physical return/charge/redeploy cycles and station relocation. Onsite inspection remains deferred by the user. No precision, hardware health or braking bound is inferred from code or old observations.
- Preserve outstanding long-run native-map nonce/parent capacity, StaticLayer failed-config cleanup and branch safety-exception ancestry concerns. These are not discharged by these static checks.

No Gazebo, Isaac, remote simulator, robot movement, service restart, deployment, landing or push was performed. The full station lifecycle goal remains incomplete.
