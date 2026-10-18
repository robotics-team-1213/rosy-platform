## D-800 CORE-mediated LeRobot observation and action requests for OMX

**Status:** Proposed

## Context

The user requested the ordinary LeRobot record/train/infer/act pipeline through
CORE on 2026-10-18. CORE's public API had no OMX policy observation/action port.
The existing owner session supplies guarded capture, lease checks, watchdog
binding and the final submission fence. D-773 rejects moving the OMX motor writer
into Pinky's CORE process.

## Decision

Add optional `CoreServices.arm_policy`, unbound by default. CORE authenticates
HTTP clients and delegates to an explicitly installed `CoreArmPolicyPort` over
one existing `OwnerPolicySession`. The owner remains the only joint/action writer.
HTTP cannot install weights, create or renew a lease, clear HOLD or rearm a stop.

The port binds one authenticated token ID supplied by trusted composition.
Observations retain guarded RGB bytes, joint order and source times behind a
single-use ID. Targets use radians and name that ID and the installed policy pin.
Capture time anchors action age, including external inference and transport.
A replacement observation invalidates the earlier ID. Capture returns BUSY while
the previous goal remains active. No old source is relabelled as a new observation.

Any authenticated operator can request stop. The persistent local stop fence
latches before cancellation of the session's exact command. The response does
not assert physical standstill. Watchdog polling stays in the bound ROS runtime.

The optional LeRobot `rosy_omx` Robot plugin exchanges only HTTP with CORE. It
opens no serial port, camera device or ROS publisher. The existing OMX integration
wheel carries it; CORE has no LeRobot, torch or model-loading dependency.
The current session is SIM-only. Physical policy admission remains closed until
D-770/D-773/D-793 evidence and authorized composition exist.

## Existing decisions

| Decision | Relationship |
|---|---|
| D-1/D-2 | CORE stays in its process; Base command writer unchanged |
| D-403/D-773 | Preserve OMX owner identity, final joint writer and Fleet authority; add CORE-facing I/O |
| D-427 | Existing middleware/execution and integration roots; no new top-level subsystem |
| D-429 | Routes use an injected port; HTTP client imports no device implementation |
| D-430 | New admission bridge is safety code, requiring independent review |
| D-770/D-793 | No physical enablement, promotion, lease issuer or installed trust |

## Verification

HTTP tests use real session, stop database, runtime binding, journal and owner,
with synthetic model/camera/authority and fake action transport. Native ROS and
actual LeRobot SDK checks are separate evidence. Neither proves trained quality
or physical safety.
