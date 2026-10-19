# OMX CORE publication verification — 2026-10-19

The origin-based candidate preserves remote physical learned-policy refusal and
the existing action owner. Historical local-main SIM receipts are not evidence
for this publication.

## Executed checks

| Source revision | Execution | Result |
|---|---|---|
| `2b5d3c84d8` | Remote host: arm API, camera, chain, lease, intake, SDK distribution, manifest and release boundary | 179 passed; NEW 0 |
| `42916efbfa` | Remote late-binding regressions before implementation | 5 expected ImportError failures |
| `dcc064c6e1` | Remote arm API, actual native-cleanup AST and chain regressions | 38 passed; NEW 0 |
| `9effd818a4` | AI test PC native Gazebo, 4 CPU / 4 GB, real LeRobot 0.4.4 SDK, authenticated CORE HTTP and Fleet HTTP | Exit 0; GAZEBO_PASS and EXIT_OK |

The native run uses the existing prepared vendor overlay through
`tools/remote/remote_sim.py --sha 9effd818a4 --minutes 12 cmd -- ...`.
The fixed policy proposes +0.01 rad for one SIM joint. No trained model loads.

- Before installation, the listening CORE server returned authenticated 503.
- Original Gazebo RGB bytes reached the SDK; SDK process imported no ROS.
- First target: 0.0100000182 rad; measured: 0.0100000156 rad.
- The same Fleet lease renewed during actual movement.
- Closing the approval window during the second goal produced cancel status 5
  and acknowledged cancellation of that exact journaled goal.
- Approval-window close HTTP response to cancel observation: 0.10080117 s.
  This excludes the close request latency and is not a physical stop guarantee.
- Final 0.3 s readback: 30 samples, spread 1.862645149230957e-08 rad.
- The session latched HOLD, closed its local fence and refused reconnect.
- Probe, executor and pool drained; no primary or teardown errors. No Destroyable
  or unretrieved-Future warning appeared in the complete run log.

## Failures and corrections

The first run at `2b5d3c84d8` failed before controller startup because the vendor
launcher ignored the explicitly selected native overlay. `1bc8d78da0` fixes that
path while retaining the container default.

That run also captured the actual unretrieved task traceback: Jazzy handler
`executors.py:588` called `gc.trigger()` after shutdown destroyed its guard.
The probe now drains the pool while the guard is alive, then shuts down the
executor and destroys entities. Timeout or pool failure retains live entities
and records the original error. The warning disappeared on the subsequent
failing runs as well as on the final successful run.

After startup was fixed, `1bc8d78da0` refused stale observations. CORE construction
and server startup occurred after session activation; they now happen before
lease acquisition. Trusted late installation registers the E-stop listener and
checks current E-stop before publishing the port, serializes installation and
rejects replacement. No new remote binding endpoint exists.

At `dcc064c6e1`, AI and model PC runs still refused stale source input. The old
probe used stock MultiThreadedExecutor, contrary to the current runtime's
documented OwnerMultiThreadedExecutor requirement. `9effd818a4` uses the existing
owner executor with the same four threads. The final run passed without changing
freshness, lease duration, admission or stop limits. These observations do not
isolate every contributor to the earlier scheduling delay.

## Evidence identity and limits

Raw logs remain outside the public repository, in the operator's
`rosy-omx-publication/native-owner-executor` evidence directory.

| Artifact | SHA256 |
|---|---|
| `run.txt` | SHA256 `bbb4eac261f4ab5cf2eba57c31b453d1fb45ca175060bbd272f77d359ab581bb` |
| `out/teardown.json` | SHA256 `e302abe46be929a251c35b6edd89f9ae0e13c0dc8ea540c8d827de56b591d9ef` |
| `out/stop-readback.json` | SHA256 `fe9ccfafa8be8541162a107c0492332f2354ecae4e2c368aff22c2661f6560d8` |
| `out/preparation-timing.json` | SHA256 `bd865dde745fa9a3e867fc60909b725178135e7eb684559b222a9d2190e41f37` |

The diagnostic wrapper records unconsumed Future exceptions directly, then calls
the original destructor; it neither fetches exceptions nor suppresses warnings.
No exception trace artifact was created in the successful run.

No physical learned-policy operation, trained-policy success, Mission admission,
physical calibration or field acceptance was verified. The separate
[asset inventory](asset-inventory.md) records what was found and the preparation
needed. GitHub/pre-push results belong to the final publication head and PR.
