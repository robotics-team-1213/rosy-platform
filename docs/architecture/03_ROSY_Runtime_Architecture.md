# 03. ROSY Runtime Architecture

## 1. Purpose

ROSY Runtime is the common runtime installed on ROSY Nodes.

The runtime itself is modular.

## 2. Minimal Base Package

Package:

`rosy-runtime-base`

Includes:

- node identity
- configuration
- heartbeat
- lifecycle manager
- plugin manager
- state store
- logging
- health reporting
- update agent

## 3. Optional Runtime Modules

Install only when required:

- `rosy-runtime-ros2`
- `rosy-runtime-device`
- `rosy-runtime-compute`
- `rosy-runtime-ai`
- `rosy-runtime-vision`
- `rosy-runtime-control`
- `rosy-runtime-dataset`

## 4. Runtime Startup

```text
BOOT
 -> load node identity
 -> load installed profiles
 -> resolve modules
 -> initialize ROSY base
 -> initialize ROS 2 if required
 -> initialize adapters
 -> initialize capabilities
 -> register node
 -> READY
```

## 5. Local Independence

Every device node must support local degraded behavior.

Examples:

- Pinky: local stop and navigation safety
- OMX: local joint safety
- RFID: local event buffering
- Edge Vision: local detection if model available

## 6. Prohibited Monolithic Behavior

Do not:

- install CUDA on non-GPU nodes
- install navigation stack on GPU-only nodes
- install OMX drivers on Pinky-only nodes
- install global control-plane services on every node

ROSY Runtime must remain composition-based.
