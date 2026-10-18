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
    capture=trusted_rgb_capture,     # returns (immutable RGB bytes, CameraSnapshot)
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
recorder records the rollout when `policy.path` is present in its configuration.
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
Neither is Gazebo task-success or physical-robot evidence.
