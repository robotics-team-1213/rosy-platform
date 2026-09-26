# 00. ROSY Platform Vision & Definition

## 1. Product Name

**ROSY Platform** (D-290; 기존 `ROSY OS`는 저장소·문서·배포 이름에 남은 이력 이름)

### 역할 이름 (D-296)

| 이름 | 책임 | 현재 범위 |
|---|---|---|
| `ROSY Platform` | 장치 실행·사이트 조정·관측·화면·AI·데이터·배포를 포괄하는 제품 | 전체 제품명; 단일 실행기 이름이 아님 |
| 장치 미들웨어 | 장치 API와 내부 ROS/드라이버 사이에서 요청 수용, 상태·capability 공개, 안전 중재, 결과·장애 처리를 소유 | Pinky는 CORE가 구현; OMX 로컬 제어기는 장치 수용 전 |
| `Fleet` | 현장 미션 순서·장치 간 인계·작업 원장을 소유하고 장치 API에 작업을 요청 | 사이트 조정 계층; 장치의 최종 물리 명령을 소유하지 않음 |
| `ROSY Runtime` | 장기 목표 문서의 노드별 로컬 실행 역할 | 모든 호스트의 공통 프로세스나 필수 설치 패키지를 뜻하지 않음 |

Pinky 주행의 최종 명령은 CORE, OMX 팔의 최종 명령은 장치 수용을 마친 OMX 로컬
제어기가 소유한다. Pinky에 OMX를 장착해도 이 경계는 유지한다. 공유하는 것은
먼저 계약이며, 공통 실행 코드는 실제 중복과 검증 필요가 확인될 때만 추출한다.

## 2. Technical Definition

ROSY Platform is a:

> **Distributed Robotics & Physical AI Platform**

ROSY Platform is not a replacement for Ubuntu or the Linux kernel.

ROSY Platform is an upper software layer installed on top of:

- Ubuntu
- ROS 2
- device drivers
- hardware interfaces
- AI runtimes

and provides a unified operating model for robots, robot arms, edge computers, sensors, AI compute nodes, and industrial devices.

## 3. Initial Scope

ROSY Platform manages:

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

This list is the target product scope, not a claim that every service is implemented or deployed.
The current site control surface is Fleet's `/console` on the Ubuntu site host,
reached from an operator browser through Caddy HTTPS. The operator PC is a client
and may be the same physical machine as the site host. Pinky CORE retains its
own local screen and final command authority. `ROSY Console` is the product name
for the human interface; natural-language control and OMX remote task APIs are
future gates under D-290, not current capabilities.

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

ROSY Platform must **not** be installed identically on every device.

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

ROSY Platform shall not replace:

- Linux kernel
- Ubuntu package management
- ROS 2 transport
- ros2_control
- vendor hardware drivers

ROSY Platform shall standardize, orchestrate, and manage them.

## 8. Strategic Direction

ROSY Platform should evolve from:

> device middleware (장치 로컬 실행·안전 경계)

to:

> distributed robotics runtime

and ultimately to:

> Physical AI operating platform for heterogeneous industrial devices.
