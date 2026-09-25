# omx_adapter

This package is the ROS-native boundary for a future OMX capability.

It validates a model-neutral profile and emits the standard
`ros2_control`/MoveIt controller contract: a joint-state broadcaster and a
`JointTrajectoryController` action. It does not open a serial port, create a
fake joint state, or advertise an arm capability while the OMX model, driver,
mount, power budget, and payload are unknown.

The current profile is intentionally disabled. Select a measured driver only
after the model is chosen between OMX-F, OMX-AI, and the legacy
OpenMANIPULATOR-X family. The actual vendor transport is a later adapter
implementation and must remain behind this profile boundary.

```bash
python -m omx_adapter.cli src/omx_adapter/config/omx.disabled.yaml
```

The empty JSON contract from the disabled profile is expected. A non-empty
contract is not a physical acceptance result.
