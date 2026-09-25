# 00. ROSY OS Vision & Definition

## 1. Product Name

**ROSY OS**

## 2. Technical Definition

ROSY OS is a:

> **Distributed Robotics & Physical AI Operating Platform**

ROSY OS is not a replacement for Ubuntu or the Linux kernel.

ROSY OS is an upper software layer installed on top of:

- Ubuntu
- ROS 2
- device drivers
- hardware interfaces
- AI runtimes

and provides a unified operating model for robots, robot arms, edge computers, sensors, AI compute nodes, and industrial devices.

## 3. Initial Scope

ROSY OS manages:

- node identity
- device discovery
- device health
- ROS 2 communication
- device abstraction
- capability exposure
- task execution
- fleet management
- compute orchestration
- AI model execution
- policy deployment
- logging
- update/deployment
- composite robots

## 4. Platform Scope

### Supported in v1

- Ubuntu 24.04 LTS
- ROS 2 Jazzy
- x86_64
- ARM64

### Optional acceleration

- NVIDIA CUDA
- TensorRT
- Intel OpenVINO

### Out of scope for v1

- Windows native ROSY Runtime
- macOS Runtime
- Android Runtime
- embedded RTOS Runtime

These may be supported later through gateways or platform-specific runtimes.

## 5. Modular Installation Principle

ROSY OS must **not** be installed identically on every device.

Each node installs only:

1. ROSY base runtime
2. required device adapters
3. required capability modules
4. required compute backends
5. required AI modules
6. required control-plane services

This architecture is called:

> **ROSY Profile-Based Modular Installation Model**

## 6. Example Profiles

### Pinky

Install:

- ROSY base runtime
- ROS 2 runtime
- Pinky adapter
- drive
- camera
- LiDAR
- battery
- safety
- docking

Do not install:

- CUDA
- VLA training
- global scheduler
- GPU model server

### OMX AI Arm

Install:

- ROSY base runtime
- ROS 2 runtime
- OMX adapter
- ros2_control integration
- DYNAMIXEL integration
- joint control
- gripper
- manipulation
- local safety

### RTX 5080 Node

Install:

- ROSY base runtime
- compute agent
- AI runtime
- CUDA
- TensorRT
- YOLO/DINO/VLM/VLA worker
- model manager

Do not install:

- mobile navigation
- drive controller
- OMX hardware driver

## 7. Product Boundary

ROSY OS shall not replace:

- Linux kernel
- Ubuntu package management
- ROS 2 transport
- ros2_control
- vendor hardware drivers

ROSY OS shall standardize, orchestrate, and manage them.

## 8. Strategic Direction

ROSY OS should evolve from:

> device middleware

to:

> distributed robotics runtime

and ultimately to:

> Physical AI operating platform for heterogeneous industrial devices.
