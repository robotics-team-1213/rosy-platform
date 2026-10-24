# LeRobot through CORE

Use `rosy-omx-record` in the dedicated LeRobot 0.4.4 environment. It registers
the `rosy_omx` Robot and invokes the official LeRobot recorder after validating
the policy's action semantics. It does not start CORE, load ROS, or open hardware.
The integration wheel's ordinary imports do not require LeRobot; only this plugin does.

## Installed composition

The existing CORE process receives an explicitly composed port **before** its
app is built:

```python
from rosy.execution.local.core_arm_policy import CoreArmPolicyPort

services.arm_policy = CoreArmPolicyPort(
    session,                         # existing authorized OwnerPolicySession
    capture=trusted_rgb_capture,     # context pins (immutable RGB bytes, CameraSnapshot)
    principal=installed_token_id,    # opaque auth token ID, never a bearer secret
)
app = create_app(config, services)
```

`session.bind_runtime(existing_ros_runtime)` must already have succeeded, with
its original watchdog, journal and steady clock. The installed policy, camera,
stop fence and authority provider remain that session's inputs. CORE E-stop
registers the arm stop listener; an E-stop already active at app creation also
closes the arm fence. CORE release cannot rearm it. No model, lease or hardware
profile can be installed over these HTTP endpoints.

**Current support is SIM only.** This is an integration seam and verified test
composition, not an installed production profile. D-770 G4 and the real Fleet
lease/owner composition remain prerequisites for physical learned motion.

## Recording and inference

In the dedicated LeRobot environment, install the existing OMX integration wheel
and its existing ROSY contract/Skill dependencies. Keep ROS and torch environments
separate. The wheel installs the `rosy-omx-record` entry point; automatic discovery
by the unmodified `lerobot-record` command is not assumed.

Create a private LeRobot RecordConfig using `robot.type: rosy_omx` and:

| Robot field | Value |
|---|---|
| `url` | CORE origin, e.g. `http://127.0.0.1:8080` |
| `token_file` | Private file containing the existing CORE bearer token |
| `policy_revision` | Exact revision authorized in CORE's installed session |
| `joint_names` | Exact installed ordered names; no aliases |
| `camera_name`, `camera_height`, `camera_width` | Exact installed RGB camera |
| `extra_cameras` | D-854: further installed cameras after the first, in installed order: `{name: [height, width]}`. Empty for one camera |

Use a new private dataset path, an explicit task and `push_to_hub: false`.
Recordings from this adapter use **radians**, `*.pos` joint features and an HWC
RGB uint8 camera. Native OMX `-100..100`/gripper `0..100` datasets are different
and cannot be used here without an independently reviewed unit conversion.

```text
rosy-omx-record --config_path=<private-record-config.json>
```

For policy rollout, use an independently evaluated ACT checkpoint with
`n_action_steps=1`, no temporal ensemble and matching normalization, joints and
camera. The launcher refuses queued ACT configurations and other policy types;
it does not silently modify or qualify an existing artifact. The same official
recorder records the rollout with a policy configuration and local
`policy.pretrained_path` (or the official launcher's `--policy.path` argument).
For teleoperation, the leader must already emit the same absolute radian targets;
the adapter does not normalize a stock OMX leader's `-100..100` output.

Train the recorded dataset with the ordinary LeRobot trainer in the model
environment. Register/evaluate/install through the existing ROSY policy workflow
before selecting a new pin. Recording or training cannot grant execution authority.
The HTTP pin identifies the authorized proposal channel; it does not independently
prove which model a remote caller loaded or that inference consumed those pixels.

## Runtime behavior

`get_observation()` waits, within a bounded timeout, until the previous goal has
finished. CORE issues a single-use observation ID with original sensor bytes and
timestamps. `send_action()` submits one absolute joint target set against that
ID. CORE's owner rechecks all admission conditions; no target is silently clipped.
Admission is not task success. The next observation comes only after the owner
reports ready. Nominal dataset FPS does not prove measured control cadence.

An uncertain action response triggers a best-effort stop, never a motion retry.
Disconnect requests stop and leaves the persistent arm fence latched. If the
connection is lost, the already-bound owner's watchdog and short lease remain
responsible. A new client connection cannot reset HOLD. An operator must use
the existing independently authorized recovery procedure.

Host tests use synthetic RGB/model/authority and fake action transport. The
native ROS check verifies CORE HTTP admission to real ROS Action acceptance,
terminal result and revocation/cancel against an isolated test action server.
Its socket test runs the actual LeRobot plugin in a separate process against a
loopback uvicorn CORE app, checks exact RGB and joint targets at the ROS server,
then verifies disconnect latches the stop fence. Authentication uses a synthetic
principal override; the target is scripted and does not come from a trained model.
Neither is Gazebo task-success or physical-robot evidence.

## Deployment preparation pipeline

The manual `Build OMX LeRobot client` workflow builds the integration and its
three internal dependency wheels. Its artifact includes the source SHA and
`SHA256SUMS`. It contains client code only; it does not include ROS, torch,
credentials, a model, or an activated robot profile. The workflow neither
publishes a release nor accesses a device. It can run after this workflow is
available on the remote repository; local merge alone does not run GitHub CI.

Install those wheels into the dedicated LeRobot 0.4.4 environment after checking
the artifact checksum and source revision:

```sh
cd <downloaded-client-artifact>
sha256sum -c SHA256SUMS
python -m pip install --no-index --find-links . rosy-integration-robot-omx==0.1.0
```

Copy `core-record.json.example` to approved private storage and replace every
placeholder, joint name and camera size with the installed values. For JSON
files use the full policy configuration, including `policy.pretrained_path`;
`policy.path` is a special official command-line argument, not a JSON field.

```sh
rosy-omx-preflight --target sim --config <private-record-config.json> --out <new-private-report.json>
rosy-omx-preflight --target real --config <private-record-config.json> --out <new-private-report.json>
```

Preflight checks the actual SDK version, synchronous ACT configuration, a local
checkpoint's file hashes, and the installed CORE policy/joints/RGB dimensions.
It performs only `GET /api/v1/arm/policy`; it does not consume an observation,
submit a target, or call disconnect/stop against a shared session. Reports do not
contain bearer tokens or original exception messages and existing reports are
never replaced. Exit 0 means **SIM configuration/I/O readiness**, 3 means blocked,
and 2 means invalid input or a failed report write. Hashing checkpoint bytes does
not qualify its behavior or bind its model to CORE's authorized manifest.

The real target always reports the current closed physical policy runtime,
unconnected Fleet-to-device policy lease, and missing D-793 physical admission.
No CLI switch or copied approval file can open these gates. This is an executable
deployment preparation path, not a working physical policy rollout. With no
assigned workcell/instance or approved policy revision, do not create substitute
identities, enable `learned_policy`, or auto-approve a window. The existing hardware
owner remains `rule_based` only. Completing D-793 C/D, live owner composition,
two-person L3 approval and physical acceptance remains necessary before learned
motion; G4 is additionally required for LIMITED use.

## Explicit SIM Fleet lease composition (D-804)

`rosy.execution.local.policy_lease` consumes the existing Fleet policy-state and
lease HTTP endpoints. `FleetPolicyHttp` uses a fixed authenticated TLS origin;
plain HTTP requires explicit loopback SIM configuration. It disables redirects
and environment proxies. Its token comes from a private file. Enter its explicit
POSIX context before acquiring leases. It prepares one owned stdlib helper with
a two-second READY budget and makes no HTTP request during preparation. Requests
then reuse that helper with the existing total 0.2-second exchange timeout;
timeout, malformed replies and context exit kill/reap it without automatic restart.
Credentials travel through stdin rather than command arguments. Process creation
and OS scheduling are not real-time guarantees. The SDK's HTTP client is separate
and keeps its existing platform support.

```python
with FleetPolicyHttp(origin, private_token_file, loopback_sim=True) as transport:
    consumer = FleetLeaseConsumer(scope, request=transport, monotonic=runtime.monotonic)
    # Enter the explicitly enabled SimPolicyChain inside this transport context.
```

Create `LeaseScope` from the trusted local SIM execution configuration: exact
AttemptIdentity, episode, installed policy revision, owner session, approved window,
rig, calibration and approval scope. The SDK cannot supply these values. The
consumer verifies the window and policy stage before and after issuance, charges
all network time to the local monotonic deadline, and accepts only advancing
renewals of that same lease. Expiry, denial and transport failure permanently
close that consumer. Its authority callback performs no network I/O.
The worker reserves the three HTTP exchanges' maximum timeout budget from the
current lease's remaining time before waiting. Insufficient sustained network
performance still closes authority; scheduling cannot extend the lease.

`SimPolicyChain` takes the already verified `InstalledPolicy`, dedicated ready
steady-clock runtime, stop fence, consumer, execution journal, trusted identity
and RGB providers, CORE principal ID and independently installed rig revision.
It checks the rig and actual owner calibration before requesting a lease.
`enabled` defaults to false. Its context manager starts the bounded renewal worker;
assign `chain.port` to `services.arm_policy` before creating the CORE app. On exit,
it closes authority and persists the existing stop fence before waiting for the
worker. Neither reconnect nor a late HTTP response can rearm the session.

The Fleet response's `device_delivery="not_connected"` remains the server's lack
of a delivery acknowledgement. The separate SIM consumer receipt records local
receipt and execution; it does not change that wire field. Its local SIM attempt
is not Fleet Mission/Action admission and cannot establish task completion.

The committed `middleware/robot_execution/local/test/policy_chain_gazebo.py` probe
runs only through `tools/remote/remote_sim.py`. It uses synthetic SIM approvals and
an explicitly scripted policy, real Fleet and CORE HTTP authentication, the
actual LeRobot plugin process, original Gazebo camera frames, the existing owner
and vendor controller. Fleet runs in a separate process; CORE HTTP and ROS share
the device process. It checks joint movement, same-lease renewal, in-motion
approval withdrawal, CANCELED/HOLD and reconnect refusal. Run results and limits
belong in the dated validation record; the probe's existence is not a passing result.
The probe constructs its installation binding from declared fixture configuration;
it does not validate an externally accepted trained-policy release.

The trusted RGB callback yields its original frame in a context that prevents
replacement until CORE has copied and validated it. Concurrent providers must
expose an immutable `camera_current` snapshot without waiting for that capture
lock, so watchdogs and stop remain available. Static sources can return
`contextlib.nullcontext((rgb_bytes, camera_snapshot))`. Pinning preserves original
timestamps and all existing freshness, authority and exact-frame checks.
