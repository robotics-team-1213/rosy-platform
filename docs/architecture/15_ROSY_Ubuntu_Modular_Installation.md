# 15. ROSY Ubuntu Modular Installation Architecture

## 1. Purpose

ROSY OS v1 targets Ubuntu.

The installation model must ensure that each device installs only the components it needs.

This is a primary architecture requirement.

## 2. Base Platform

Target:

- Ubuntu 24.04 LTS
- ROS 2 Jazzy
- systemd
- apt / dpkg
- Docker optional
- Python / C++ / .NET modules as required

## 3. Package Layers

```text
Layer 0
Ubuntu

Layer 1
rosy-runtime-base

Layer 2
rosy-runtime-ros2
rosy-runtime-device
rosy-runtime-compute
rosy-runtime-ai

Layer 3
Adapters / Backends

Layer 4
Capabilities

Layer 5
Profiles
```

## 4. Minimal Common Package

Every ROSY Node installs:

```text
rosy-runtime-base
```

Includes:

- identity
- node config
- lifecycle
- heartbeat
- health
- logging
- plugin loader
- update agent

It should remain lightweight.

## 5. Optional Packages

Examples:

```text
rosy-runtime-ros2
rosy-runtime-compute
rosy-runtime-ai
rosy-runtime-vision

rosy-adapter-pinky
rosy-adapter-omx
rosy-adapter-rfid
rosy-adapter-camera

rosy-backend-openvino
rosy-backend-cuda
rosy-backend-tensorrt

rosy-capability-navigation
rosy-capability-manipulation
rosy-capability-docking
rosy-capability-vision
rosy-capability-rfid
```

## 6. Profiles

Profiles are meta-packages or manifests.

### Control

```text
rosy-profile-control
```

Installs:

- rosy-runtime-base
- rosy-control
- registry
- task orchestrator
- scheduler
- API
- dashboard backend

### Pinky

```text
rosy-profile-pinky
```

Installs:

- rosy-runtime-base
- rosy-runtime-ros2
- rosy-adapter-pinky
- navigation capability
- camera capability
- lidar capability
- battery capability
- docking capability
- safety capability

### OMX

```text
rosy-profile-omx
```

Installs:

- rosy-runtime-base
- rosy-runtime-ros2
- rosy-adapter-omx
- ros2_control integration
- DYNAMIXEL integration
- manipulation capability
- gripper capability
- local safety

### Edge

```text
rosy-profile-edge
```

Installs:

- rosy-runtime-base
- rosy-runtime-ros2
- rosy-runtime-compute
- OpenVINO optional
- tracking
- video preprocessing

### GPU

```text
rosy-profile-gpu
```

Installs:

- rosy-runtime-base
- rosy-runtime-compute
- rosy-runtime-ai
- CUDA backend
- TensorRT backend
- model manager
- AI worker

### RFID

```text
rosy-profile-rfid
```

Installs:

- rosy-runtime-base
- rosy-adapter-rfid
- RFID capability
- local buffering

## 7. Combined Profiles

A machine can have multiple profiles.

Example:

```yaml
node:
  id: pinky-omx-01

profiles:
  - rosy-profile-pinky
  - rosy-profile-omx
```

Dependency resolver installs only the union of required packages.

## 8. Node Manifest

Recommended file:

```text
/etc/rosy/node.yaml
```

Example:

```yaml
node_id: GPU-01
role: compute

profiles:
  - rosy-profile-gpu

features:
  cuda: true
  tensorrt: true
  ros2: false
```

## 9. Installer

Recommended command:

```bash
sudo rosyctl install profile pinky
```

Other examples:

```bash
sudo rosyctl install profile omx
sudo rosyctl install profile edge
sudo rosyctl install profile gpu
sudo rosyctl install profile control
```

Combined:

```bash
sudo rosyctl install profile pinky omx
```

## 10. Runtime Inspection

```bash
rosyctl node status
rosyctl profile list
rosyctl capability list
rosyctl adapter list
rosyctl health
```

## 11. Package Management Strategy

Recommended v1:

- Debian packages for ROSY core/runtime
- apt repository for distribution
- profile packages as meta-packages
- Docker only for workloads that benefit from container isolation

Do not containerize low-level hardware control merely for consistency.

## 12. Version Management

Track separately:

- ROSY Runtime version
- adapter version
- capability version
- profile version
- ROS 2 version
- Ubuntu version

## 13. Upgrade Policy

Example:

```bash
sudo rosyctl update
```

ROSY should:

1. check compatibility
2. download package metadata
3. determine affected modules
4. stop only required services
5. upgrade modules
6. restart services
7. run health check
8. rollback on failure

## 14. Future OS Support

The architecture shall not hard-code Ubuntu-specific concepts into the domain model.

Separate:

```text
ROSY Core
```

from:

```text
Ubuntu Platform Adapter
```

Future targets may include:

- Debian
- Ubuntu Core
- Jetson Linux
- Windows
- other embedded Linux distributions

but Ubuntu remains the v1 reference platform.
