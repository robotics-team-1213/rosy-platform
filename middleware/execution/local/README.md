# Local execution evidence and policy installation checks

`rosy-execution-local` 0.1.3 depends on the ROS-free skill0.1.0 and learning0.1.6
contracts wheels. The policy installation loader imports no learning registry,
inference framework, ROS node, device driver, or network client.

`policy_install.InstallBinding` captures trusted installation inputs: pinned policy
revision, device/camera profile, camera metadata, normalization hash, owner/controller/
envelope, action order/ranges and timing. Supply these from the accepted installed
release/profile. Deriving them from the policy being inspected provides no assurance.

`load_policy(root, binding)` verifies the canonical artifact and actual referenced
files, exact bindings and period, and that action ranges/stale budgets fit installation.
`InstalledPolicy.recheck()` detects manifest replacement/reseal and referenced file
corruption. Metadata returned to callers is a fresh copy; bool/numeric aliases do not
pass camera equality checks. No inference model or weights are deserialized here.

This is compatibility evidence only. It grants no stage, trust, lease, generation,
execution or recovery authority. It does not make the mutable filesystem immutable;
a later inference loader must preserve/revalidate the exact model bytes it consumes.
An authorized envelope Skill and the existing owner/StopFence must enforce dispatch,
stale/HOLD/reset/stop/rollback. There is no runtime process wiring in this change.

The optional `omx_policy` module uses the installed OMX adapter's ROS-free
`ArmCommandOwner`/`LocalStopController` plus the foundation schema dependencies
(including Pydantic). The adapter is provided by the native product payload; these
imports are lazy with respect to the package and are not additional pip wheels.
Importing the installation loader alone still needs only the contracts wheels.

`OwnerPolicySession` defaults disabled and accepts only a bound SIM identity. It
checks the pinned controller/config, local stop epoch/generation, scoped short lease,
joint sequence/time, camera identity/calibration/shape/frame hashes, action causality,
period and stale budgets. It rechecks time after external providers and immediately
before dispatch through the existing owner. Faults latch HOLD and request cancellation
of its own active command. No automatic recovery/rearm or final publisher is added.

Successfully admitted joint observations are retained in bounded history (64 entries
by default, configurable from 1 to 4096). A candidate may use an older sequence only
when its exact recorded timestamp remains within the installed observation budget
and the current pose remains within the owner's installed start-state tolerances.
The command carries the original inference start pose, never a substituted latest
pose. Source freshness and pose difference are rechecked inside the final fence;
unknown, evicted, stale or moved sources latch HOLD. The owner still enforces source
sequence advancement. Camera frame equality and age checks are unchanged.

Composition must provide authenticated local authority and camera capture providers
and actually schedule `poll()`. DTO metadata/hash checks do not authenticate capture
or prove inference consumed the pixels. This module supplies neither providers nor
an issuer/scheduler/promotion wire API. Host positive tests use synthetic installed
artifacts/authority/capture and fake action transport; cancellation is not independent
stopped proof. Actual research policies remain unqualified and unactivated.

Host tests:

```powershell
python -B -m pytest middleware/execution/local/test/test_policy_install.py -q -p no:cacheprovider --basetemp X:/DevTemp/policy-install-tests
```
