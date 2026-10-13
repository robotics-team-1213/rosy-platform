# Same-execution native ROS transport closure

Owner: feat/omx-policy-native-chain. Extend the existing isolated
test_policy_runtime_ros.py fixture; keep domain 199, localhost discovery,
unique namespaces, synthetic controller/model/grants and X-drive outputs.
No production endpoint, operational service, GPU, model or motion is changed.

Create the original grant and attempt in the actual ActionRunner/ActionStore.
Take the session serializer before the runner stop fence. Capture the actual
observation immediately before native submission. Persist the initial parent
receipt as UNKNOWN with no driver goal UUID: submission alone does not prove
server acceptance. Wait for the actual native journal UUID outside both locks,
validate current parent authority, and reconcile that same attempt to its
actual terminal state. Do not synthesize an ACCEPTED transition or resubmit.

Only the final grant validation, driver call and durable submission receipt are
inside the session-to-stop fence. ActionStore preparation remains outside that
serializer, allowing genuine observation and watchdog progress. Host negatives
cover stop, generation/authority loss and expiry during preparation, preserving
the original durable attempt and prohibiting implicit retry. Provider checks
are repeated inside the real fence; clock sampling after callbacks cannot
extend the original grant. Arbitrary impure provider closures do not gain an
atomic-snapshot guarantee from these finite checks.

Use the private preterminal capability to bind the actual native result,
ActionAPI v2 receipt, sealed Episode and offline Fleet export. Verify normal
completion and authority-revoked cancellation independently. Task outcome,
model inference, physical execution and a Fleet receiver remain unverified.

Preserve the original 2-second source/joint freshness, 12-second policy lease,
15-second parent grant and 10-ms poll. Dispatch and runtime watchdog guards
remain in force. A post-ack readback is not a second dispatch admission.
Timeout or expiry remains failure; do not extend these budgets to obtain PASS.

Separate mutually-exclusive watchdog and joint-observation callback groups
remove callback-group exclusion without removing session/owner/fence locks.
The Windows shared-filesystem native chain has recorded stale rejections;
those results stay failures. Root and independent X-backed ext4-fronted
snapshots passed the normal/revocation parent cases with unchanged budgets.
This is a local Linux test-storage scope, not proof of native device storage,
50-ms performance, Windows-path support or deployment. Final helper source and
all four native variants require their own source-pinned verification before
landing; earlier snapshots do not qualify subsequent helper changes.

Validate canonical metadata first, capture each source once, and validate
its size/SHA, containment and complete reference closure from those bytes.
Publication still validates persisted bytes and native correlation, checks
actual final API receipt, and validates authority immediately before the
exclusive manifest link. This removes repeated file I/O without relaxing
approval, reference, freshness or revocation checks.

The installed Jazzy executor shutdown does not itself prove worker completion.
Drain the worker pool with a bounded completion event before destroying ROS
entities. Preserve primary errors and callback diagnostics; cleanup aborts of
isolated server never count as authority-revoked cancellation. The outer
subprocess wall bound includes startup and cleanup, separate from policy TTL.

Report exact source pins, host tests and independently executed native cases
separately. Neither synthetic transport nor offline Fleet sealing establishes
50-ms/500-ms performance, actual model inference, task success, receiver or
device acceptance. The user permits at most one total physical distance of
0.20 m across all robots, attempts and coast; this fixture performs no physical
motion and does not release commissioning or safety holds.
