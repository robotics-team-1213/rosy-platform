# OMX-AI Workcell Deployment Preparation

This directory prepares a separate ROS 2 Jazzy workstation runtime for the
fixed OMX-AI workcell. `stack.lock.yaml` pins the official ROBOTIS source set
to immutable revisions. It is not an enabled runtime, a built OCI image, or a
flashable Raspberry Pi image.

## Current contract

- Target model: OMX-AI.
- Runtime profile: disabled; no joint map, hardware plugin, serial identity,
  camera identity, or motion command is configured.
- Vendor entry point: official ROBOTIS `open_manipulator` ROS 2 packages.
- Candidate deployment: a dedicated workstation OCI image, initially amd64.
  Keep it separate from `deploy/robot`'s Pinky Pro ARM64 product image.
- Camera source: unselected. Choose a camera and driver before adding camera
  packages to the runtime image.

See [the implementation plan](../../docs/plans/2026-09-26-omx-ai-workstation-runtime.md)
for deployment trade-offs, RMW boundaries, and P0-P3 acceptance gates.

No vendor launch file is run by this directory, and the source lock alone does
not prove ROS graph, artifact, device, or field acceptance.
