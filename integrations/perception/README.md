# perception_runtime

ROS-free lane perception and learned-model runtime, shared by the robot (`control`) and the learning tools.

Split out of `control` (`middleware/perception`) on 2026-11-03. Before, `learning/*/perception` imported `control.sensing.perception.*` and `control.recording` directly, which the layer rules froze as four `learning -> middleware` exceptions. Now both sides import this part, and the rules in `tools/harness/platform_parts.yaml` allow `middleware` and `learning` to import `integrations/perception`.

| Import | Was |
|--------|-----|
| `perception_runtime.recording` | `control.recording` |
| `perception_runtime.keep_odom_veto` | `control.keep_odom_veto` |
| `perception_runtime.perception.<lane, lane_bev, lane_keep*, camera_ground, road_state*, ...>` | `control.sensing.perception.<same>` |
| `perception_runtime.perception.learned.<manifest, runner, detector, lane_mask, signature, ...>` | `control.sensing.perception.learned.<same>` |

Robot nodes, camera workers, drivable steering and the remaining learned helpers (`shadow`, `status`, `paint_worker`, `paint_motion`, `expected_path`) stay in `control`.

On the robot, colcon builds this package beside `control` (`control/package.xml` exec_depends it; the Pinky image lists it in `--packages-select` and `required-ros-packages.txt`).
