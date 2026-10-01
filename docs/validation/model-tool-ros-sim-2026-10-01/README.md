# Model tool / OMX ROS-SIM partial evidence · 2026-10-01

## Claim under test

Check whether the existing isolated OMX Pilot path can execute a bounded ROS action and report independent joint-state readback, as one supporting slice for the provider-neutral model-tool plan. This does not connect Gemini ER 2 or a Fleet model-tool call to the device Action API.

## Environment and controls

- Vendor workstation image: `rosy-omx-workstation:native-action-only-local`, `sha256:b47034e436119cea97c2922a1b4af9bd6596975ac8acbb4cece3a19d2fe1e9f0`, Linux/amd64.
- Pilot image: `rosy-omx-pilot:local`, `sha256:e94662607c72a7cea83c9449178099c4c9476afab0519275ce0da82a88f3da9a`, Linux/amd64.
- Run: Docker bridge, `127.0.0.1:8088` only, checkout mounted read-only, ROS domain 75 with `LOCALHOST` discovery, no device grants, no live hardware.
- Container: `1c3883f6ffec`; started from the plan worktree and removed after the probe.
- Probe: `python deploy/robot/omx/probe_pilot_sim_http.py rosy-omx-pilot-sim`.

## Observed result

```text
joint1_submit=LOCAL_ACCEPTED
joint1_goal=SUCCEEDED reason= ros_id_present=True before=0.0000 after=0.0179 owner=ready
gripper_joint_1_submit=LOCAL_ACCEPTED
gripper_joint_1_goal=SUCCEEDED reason= ros_id_present=True before=-0.0001 after=0.0076 owner=ready
cancel_request=CANCEL_REQUESTED
cancel_terminal=CANCELED ros_id_present=True
```

The probe's bounded movement assertions passed for both joints. ROS action terminal status and readback are distinct observations; neither establishes grasp/place success or physical stopping behavior.

## Additional source regression

- Fleet model-tool contract/conformance/ER2/journal/feedback suites: **116 passed**.
- OMX action API/store/PICK_PLACE/pilot-runtime suites: **48 passed**.
- `test_omx_ros_runtime_vendor_sim.py`: **1 passed** in the Pilot image. It started the pinned vendor Gazebo launch and exercised `RosArmCommandRuntime` callbacks for a no-op goal, fresh state readback, rejection of a competing owner, and terminal cancellation. The initial attempt with the thinner base image failed collection because that image does not install Pydantic; the test was rerun successfully in the Pilot image, which supplies that dependency.
- `test_omx_ros_runtime.py`: **2 passed** in the same pinned Jazzy Pilot image without launching the vendor simulator for this isolated in-process ROS action-server test. The added fault injection delays an accepted result past the owner deadline, allows the ROS cancel request, observes cancel ACK and terminal `CANCELED`, and verifies the local owner remains latched in `HOLD` and refuses replay. This validates client/server callback behavior and timeout fencing in ROS 2; it is not a physical stop test.
- `test_fleet_omx_uds_end_to_end.py`: **1 passed** in the pinned Jazzy Pilot image. It admitted a Fleet Mission, submitted its v2 grant over the actual Unix socket, authenticated `SO_PEERCRED`, validated the device receipt, and reconciled the same local journal entry through `GetAction`. The test exposed and fixed a malformed PICK_PLACE `created` field and checks server shutdown. Its phase runner is an approach-only journal fixture: no ROS goal is sent and no grasp/place is inferred.
- Fleet Mission dispatcher, phase contract, and UDS integration regressions: **20 passed**; OMX Action API and ROS callback regressions: **18 passed** in the same pinned Jazzy Pilot image.
- ROS-free OMX action/store/PICK_PLACE regression: **37 passed, 1 skipped** on the Windows host, including restart-to-`UNKNOWN`, generation fencing, late acceptance, and four-phase journal/gates. These remain source-level workflow tests; no camera/contact/grasp evidence exists in the vendor simulator.
- Provider/model egress remained disabled. No Gemini API request, credential injection, Fleet-to-device Action grant, or provider data egress was performed.

The local evidence artifact record is [the simulation-only manifest](../model-tool-artifact-2026-10-01/manifest.json). Its detached SHA-256 is recorded in `manifest.sha256`. It pins the local OCI image IDs, vendor stack lock, model-tool catalog source hash, direct Pilot Python pins, disabled provider state, empty approved data-class list, and data-retention boundary. It is unsigned, has no registry digest, and has only a partial OS/transitive dependency inventory, so ARTIFACT remains HOLD.

## Gate decision and remaining evidence

This advances the ROS action control-path observation and exercises Fleet admission through local UDS grant/receipt reconciliation, plus timeout/cancel callback fencing in a pinned Jazzy ROS process. It does not pass the model-tool plan's full ROS-SIM gate: the Fleet-to-UDS test uses an approach-only accepted-phase fixture, not a vendor ROS goal; there is still no vendor-Gazebo stop-generation/restart scenario and no four-phase PICK_PLACE execution against Gazebo. The four-phase and generation/restart tests are source-level tests only. No Gemini/provider request was made. The local simulation manifest is not a signed/published release artifact. ARTIFACT remains HOLD; DEVICE and FIELD were not run; capability and physical operation remain disabled/held.

Next ROS-SIM closure joins the now-tested Fleet-to-UDS grant/receipt boundary to the vendor Gazebo ROS action callback in one harness; injects a generation change while an actual vendor goal is pending; checks restart recovery with UNKNOWN/HOLD and no replay; and exercises four-phase approach/grasp/transfer/release with fresh state plus independent simulated object/gripper evidence. It must preserve the model's candidate-only boundary and admit any device Action through Fleet's separately authorized Mission path.
