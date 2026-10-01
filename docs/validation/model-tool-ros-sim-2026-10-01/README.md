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

## Gate decision and remaining evidence

This advances only the supporting OMX ROS action control-path observation. It does not pass the model-tool plan's full ROS-SIM gate. There was no Gemini/provider request, Fleet Mission admission/grant handoff, fault injection for timeout/late result/stop-generation race/restart UNKNOWN, or four-phase PICK_PLACE execution against Gazebo. The four-phase and fence tests are source-level tests only. ARTIFACT, DEVICE, and FIELD were not run; capability and physical operation remain disabled/held.

Next ROS-SIM test must run on the pinned Jazzy/vendor image and record: (1) accepted, rejected, timed-out and late ROS callbacks, (2) dispatch-generation change while a goal is pending, (3) owner restart with ambiguous outcome remaining UNKNOWN/HOLD without replay, and (4) approach/grasp/transfer/release with fresh state/readback gates. It must preserve the model's candidate-only boundary and admit any device Action through Fleet's separately authorized Mission path.
