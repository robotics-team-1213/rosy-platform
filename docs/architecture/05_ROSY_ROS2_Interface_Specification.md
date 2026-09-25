# 05. ROSY ROS 2 Interface Specification

## 1. Namespace Convention

Default namespace:

```text
/rosy/{device_id}/...
```

## 2. Standard Topics

```text
/rosy/{device_id}/state
/rosy/{device_id}/health
/rosy/{device_id}/heartbeat
/rosy/{device_id}/event
```

## 3. Standard Action Interfaces

Use ROS 2 Action for long-running operations.

Examples:

```text
/rosy/{device_id}/action/navigate
/rosy/{device_id}/action/pick
/rosy/{device_id}/action/place
/rosy/{device_id}/action/dock
```

## 4. Service Interfaces

Use ROS 2 Service for short request/response operations.

Examples:

- reset
- enable
- disable
- clear_fault
- get_capabilities

## 5. Topic Interfaces

Use Topic for continuous or event-driven data.

Examples:

- joint state
- pose
- velocity
- battery
- camera
- LiDAR
- RFID events

## 6. Pinky Example

```text
/rosy/pinky01/state
/rosy/pinky01/cmd_vel
/rosy/pinky01/camera/front
/rosy/pinky01/lidar
/rosy/pinky01/battery
```

## 7. OMX Example

```text
/rosy/omx01/state
/rosy/omx01/joint_states
/rosy/omx01/action/trajectory
/rosy/omx01/gripper
```

## 8. Compatibility Principle

Existing ROS 2 vendor drivers should be wrapped whenever possible instead of rewritten.
