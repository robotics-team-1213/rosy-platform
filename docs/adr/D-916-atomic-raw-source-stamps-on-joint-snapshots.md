## D-916 Atomic raw source stamps on validated OMX joint snapshots

**Status:** Accepted for software implementation (2026-10-29, continuation of the user-authorized G1c work; independent architecture and critic plan reviews approved). Contract/Safety source review and committed-source remote verification remain required. No device activation, deployment, landing or publication.

### Problem

JointStateIntake validates original ROS stamp and source-now values, then retains only positions, accepted sequence, age-adjusted owner receive time and calibration revision. Its mutable last_attempt diagnostic is replaced even by rejected input. Joining an earlier snapshot with that later diagnostic mixes different messages.

### Decision

1. Append optional source_stamp_ns and source_now_ns to the existing frozen JointStateSnapshot. Store the exact values used by the successful intake in that same snapshot. Both are absent for legacy/manual snapshots, or both are exact positive integers with stamp ≤ now, matching the existing intake condition without adding an upper-bound policy.
2. Keep the original four positional parameters, sequence advancement, age-adjusted received_at, rejection behavior, calibration and immutable positions. Owner admission, freshness, watchdog, action dispatch, safety limits and cancellation continue to use their existing fields and rules.
3. Runtime publishes an intake-validated snapshot before owner admission and later delivers that same object through the existing owner/policy path. New metadata does not establish that admission has occurred. Do not introduce another diagnostic lookup, mutable sidecar, read timestamp, UUID or device writer.
4. These raw integers do not establish UTC, a verified source clock domain/epoch, publisher identity or source-side capture-after-request. They cannot populate D-915 physical observation UTC fields or a public proof by reinterpretation. Existing HTTP/UDS responses and ExecutionStateSnapshot projections are unchanged; no API reference version bump applies to this internal optional metadata.
5. The next G1c stage must separately establish source-clock profile/identity, durable PRE/POST context anchors, source reset/pause handling and complete participant/link/gripper/held measurements. Missing identity remains missing.

### Verification and recovery

Test original-source preservation after rejection and diagnostic mutation, subsequent accepted sequence/metadata, frozen fields, legacy constructors, malformed/partial metadata, and preservation of the existing source range and freshness behavior. Confirm the actual ROS runtime passes the same snapshot to the owner and replay still reaches the existing stale-state HOLD/cancel path. Remote default pytest skips of ROS are not ROS execution evidence.

The metadata has no authority consumer. Recovery can restore the prior snapshot/intake implementation without journal changes, claim release or command replay. Hardware and field acceptance are separate.
