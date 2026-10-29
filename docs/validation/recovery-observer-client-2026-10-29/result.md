# Independent recovery observation client — 2026-10-29

The host tool `tools/sim/recovery_observer.py` consumes the existing API v1.327 recovery context and posts independent facts once. It does not request recovery, approve a child, call normal PRE_DISPATCH observations or dispatch. Existing Fleet proof validation and separate named-operator approval remain authoritative. Usage is in the Fleet transfer outcome guide.

## Committed verification

| Revision | Check | Result |
|---|---|---|
| commit 75d7c3652f | Actual-API test before implementation | Remote RED: independent client file missing |
| commit cfeb021799 | Initial client cases | Remote exit 0, 21 pass progress results |
| commit a6dfd92e7f | Client, actual recovery API and authentication tests, including real loopback redirect/proxy and CLI checks | Remote exit 0, 43 pass progress results; classifier exit 0, NEW 0 |
| commit 8673b514a4 | Four optional joint-pair no-POST cases | All four remote RED: old client sent invalid pairs to the existing server, which rejected them; client reported unconfirmed instead of rejecting locally |
| commit afa10f26b278181e6f331dc340baac49cbe567dd | Client, recovery API and authentication suites after local joint checks and hostile-response coverage | Remote exit 0, 53 pass progress results, no skips or failure symbols; classifier exit 0, NEW 0 |

Command: `python tools/remote/remote_pytest.py --log-dir <external-log-directory> -- operations/fleet/test/test_recovery_observer_client.py operations/fleet/test/test_transfer_recovery_api.py operations/fleet/test/test_transfer_recovery_auth.py -q`.

Repeated quiet settings suppress the normal final counts line. Counts above are derived from completed progress symbols; the overlapping runs are not summed. No laptop pytest was used. Transport polling reconnects during execution do not establish a source failure or acceptance.

## What the checks establish

- The real existing API fixture receives the original bound observations and reaches READY_FOR_APPROVAL while the parent remains HOLD, no child is created, and the owner has only the original submission. This fixture uses a fake owner and synthetic World facts.
- Changed request context, action/attempt, producer, policy, owner session, stale/future UTC, outer observation order/separation and optional joint identity/order are rejected before POST. Source timestamps and facts are not refreshed or relabelled. Legacy G2-only objects are rejected unchanged.
- A lost POST reply is unconfirmed after exactly one submission, even when the server recorded the proof. There is no automatic replay or operator approval.
- Real local HTTP checks confirm no redirect credential forwarding or use of environment proxies. Hostile/oversized JSON, CLI secret redaction and exclusive context output are covered. All network peers in these tests are loopback/test applications, not robots.
- Independent read-only contract review of commit afa10f26b2 found no remaining supported material findings. The reviewer traced the observer authentication, proof writer and separate approval path; it did not run the tests.

## Evidence and limits

Raw logs remain in system TEMP, outside the checkout; transport details are not published here.

| TEMP directory (`run-1.txt`) | SHA-256 |
|---|---|
| `rosy-recovery-observer-red` | `f756910873a4f1faed096b4ff5025a6484644395bc4baad413d1812ca598a278` |
| `rosy-recovery-observer-joints-red` | `f2cb31e4e6b9e4fd174067136a48e0fc70ffbbafbea824a04bcbfb4a1be4419e` |
| `rosy-recovery-observer-verified` | `52a4b310fb8b9068b29efbf5351211b667e14c1d430af6c60c1d5a23998ce3b1` |

This is the transport/validation seam. The current G2 observer's pose, gripper position, simulation clock and receive-wall time do not provide all link bounds/velocities or original source UTC capture binding required by Fleet. The client does not manufacture those facts. Authentic source measurements require a separately installed trusted producer; observer credentials and matching metadata alone do not prove physical truth.

No actual Gazebo producer installation/run, real device, human labels, model training, deployment or field acceptance was performed. Local-main landing and workspace return follow separately through the official gateway; their actual outcome belongs in the workspace integration record rather than rewriting this frozen result.

CE: not applicable. Source-clock limitations remain unresolved producer requirements, not a solved lesson; the local joint rejection and transport rules are explicit in the final code, tests and guide.
