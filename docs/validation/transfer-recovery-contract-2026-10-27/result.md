# Simulation recovery shared contract — 2026-10-27

## Scope

Source `2d932dad6b` registers API v1.327 and thirteen canonical recovery DTOs (D-899).
It adds no HTTP handlers, producer, UI, device activation or model training.
The envelope remains1.0. Official version bump updates only existing live pins.

## Committed-revision evidence

| Revision | Remote selection | Result |
|---|---|---|
| `f5bf86ef2c` | New `test_arm_transfer_recovery_contract.py` | RED:30 failed, all missing shared contract import; expected NEW30, known0/flaky0 |
| `2d932dad6b` | Entire Foundation, gateway protocol schemas and five changed version-pin suites | GREEN:1,583 passed/0 skipped, 12 warnings,10.03s; runner0, classifier NEW0/known0/flaky0 |

Commands from the product worktree:

```powershell
python tools/remote/remote_pytest.py --log-dir "$env:TEMP/rosy-recovery-contract-red" -- contracts/foundation/test/test_arm_transfer_recovery_contract.py
python tools/remote/remote_pytest.py --log-dir "$env:TEMP/rosy-recovery-contract-green" -- contracts/foundation/test middleware/core/gateway/test/test_protocol_schemas.py operations/fleet/test/test_development_session.py operations/fleet/test/test_lane_route.py operations/fleet/test/test_mission_progress.py operations/fleet/test/test_task_contract_docs.py test/test_line_follow_contract_docs.py
python test/known_failures.py "$env:TEMP/rosy-recovery-contract-green/run-1.txt"
```

Logs remain in the named external scratch directories. No baseline or quarantine was changed.
Local checks were AST parsing, harness generation/lint and staged-diff checks; no local pytest ran.
After GREEN, only the test module's redundant docstring was removed; an AST comparison confirmed
identical executable test content. No public protocol or runtime behavior changed in that cleanup.

## Contract boundaries

- Inputs cannot choose an actor or grant. Observation ingress requires RECOVERY_RESET and two typed facts.
- Recovery capture owners have exactly the four fields supported by the retained context; no truth poses.
- Ready approval requires request/proposal/proof/generation bindings. CHILD_CREATED means a distinct
  bounded attempt; it neither declares physical success nor grants another retry.
- Owner-reported execution and task outcome remain separate. Physical failure cause stays null;
  owner reason preserves the existing nullable/empty/max256 contract.
- Capability flags and frozen DTOs are not evidence of an authenticated runtime or real measurements.

This focused GREEN does not discharge the shared-change FULL landing gate. Official landing and
subsequent HTTP/browser integration are separate steps, recorded with their own revisions.
Existing module gates are unchanged. No device, ARM64, Gazebo producer or field acceptance is claimed.
CE: 해당 없음 — new boundary rules are directly expressed in the contract, tests and D-899.
