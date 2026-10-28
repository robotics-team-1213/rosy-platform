# CORE-mediated OMX LeRobot bridge

## Approved intent

The user requested the ordinary collect → train → observe → infer → act pipeline,
with CORE responsible for robot execution. LeRobot reads observations and proposes
joint targets through CORE; it must not open the motor bus or publish ROS commands.
The existing OMX owner remains the only joint/action writer (D-773 §1).

## Design

Expose an optional, default-unbound arm-policy port through the existing CORE app.
An installed composition supplies an already-authorized `OwnerPolicySession`, its
trusted RGB capture provider, and the authenticated operator token identity that
may use it. HTTP requests cannot install a model, issue/renew a lease, or rearm.
The existing session currently accepts SIM only; this change does not open physical
learned-policy admission or claim D-770 G4 acceptance.

The observation endpoint preserves the exact guarded joint/RGB snapshot behind a
single-use opaque ID. An action names that ID and the installed policy revision.
CORE reconstructs the candidate from retained source metadata. Its action-age
anchor is the CORE capture time, conservatively including inference and transport;
client clocks cannot freshen it. The session still checks stop, authority, source
age, calibration, camera, envelope and owner binding immediately before submission.
One outstanding observation per bound session is enough for synchronous ACT;
another capture invalidates the prior ID. CORE preserves source metadata; the
supported launcher requires ACT n_action_steps=1 without temporal ensemble.
The authenticated proposal channel is not proof of a remote model's actual inputs.

An explicit stop trips the existing persistent local stop fence, then polls the
session to cancel its exact active command. It returns cancellation/latch evidence,
never physical stopped proof. Runtime watchdog scheduling remains owned by the
existing bound ROS runtime, independent of HTTP clients. CORE E-stop also trips
the arm stop fence, including when already active at app creation.

The optional LeRobot `rosy_omx` Robot implementation uses a standard-library HTTP
client. It pins the policy revision, preserves joint names in radians, decodes the
front RGB camera, and sends absolute targets with the last observation ID. Model
loading, preprocessing, normalization and training remain LeRobot responsibilities.
Existing native normalized OMX datasets are not converted into SIM radians.

## Implementation plan

1. Add failing HTTP-to-real-session tests: dispatch, opaque observation reuse,
   wrong principal/revision, stale input, revoked authority, stop and unbound CORE.
   Commit tests and run through `tools/remote/remote_pytest.py` to establish RED.
2. Implement the optional CORE routes, existing-session bridge, and CORE service
   injection. Add the LeRobot client/plugin using the existing OMX integration
   wheel. No ROS/torch/LeRobot import in CORE's web module.
3. Document API v1.271 and D-800, add adapter tests and optional real SDK checks.
   Run committed remote regressions, compare every report with known_failures,
   and independently review the authority boundaries before completion.

## Acceptance and limits

The host check must reach the real `ArmCommandOwner` through CORE's HTTP app and
reject stale/reused/revoked requests before driver submission. Optional native
ROS evidence must be described separately from fake transport, trained-model
quality, Gazebo task success and physical acceptance. Do not land, push, deploy
or operate hardware as part of this branch.

## Deployment preparation follow-up

The user subsequently authorized deployment/physical-readiness pipeline work and
local commit/merge. They confirmed no target workcell/instance or approved policy
revision exists. Push and live device activation were not requested.

Ruling: prepare a repeatable client-wheel artifact and executable preflight, while
retaining the existing D-793 physical refusal. An invented target, approval, lease
or successful physical test would misrepresent the system's current capabilities.

1. Merge current main into this task worktree, preserving both append-only logs
   and regenerating indexes. Remove ADR gap rows for decisions now present.
2. Add a manual client-wheel workflow with source SHA/checksums and complete
   internal wheel dependency closure. Add preflight with SDK/config/checkpoint
   checks and GET-only CORE inspection. A real target must remain blocked.
3. Verify actual wheel build/offline install and actual SDK command/report behavior
   remotely; independently review the final producer/consumer boundaries. Run
   `tools/land.py --tests auto` for the authorized local merge. Do not push.
