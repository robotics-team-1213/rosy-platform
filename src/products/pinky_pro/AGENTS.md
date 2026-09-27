<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-25 | Updated: 2026-09-25 -->

# pinky_pro

## Purpose

Pinky Pro 전용 소스와 구성. 부모 폴더는 ROS 패키지가 아니며 `profile/`에 ROS 패키지 `pinky_pro`가 있다. CORE의 최종 주행 명령 권한은 이 폴더로 이동하지 않는다.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `profile/` | ROS 패키지 `pinky_pro`; 장치 profile·capabilities (see `profile/AGENTS.md`) |
| `bringup/` | Motors, odometry, LiDAR, battery, deadman (see `bringup/AGENTS.md`) |
| `adc/` | ROS 패키지 `sensor_adc`; I2C ADC (see `adc/AGENTS.md`) |
| `lamp/` | ROS 패키지 `lamp_control`; WS2811 lamp (see `lamp/AGENTS.md`) |
| `led/` | LED service (see `led/AGENTS.md`) |

<!-- MANUAL: -->
