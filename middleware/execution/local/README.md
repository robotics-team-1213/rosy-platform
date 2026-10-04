# Local execution evidence and policy installation checks

`rosy-execution-local` 0.1.1 depends on the ROS-free skill0.1.0 and learning0.1.6
contracts wheels. It imports no learning registry, inference framework, ROS node,
device driver, or network client.

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

Host tests:

```powershell
python -B -m pytest middleware/execution/local/test/test_policy_install.py -q -p no:cacheprovider --basetemp X:/DevTemp/policy-install-tests
```
