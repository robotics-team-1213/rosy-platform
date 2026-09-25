# map_260905_update_v2 Gazebo end-to-end validation

Date: 2026-09-20 KST

## Verdict

The v2 world and static reference map pass their file-level checks, but the
requested end-to-end driving, live SLAM map generation, and Fleet control are
**HOLD**. No navigation goal was issued because the runtime failed the sensor,
collision, and CORE preconditions before motion.

| Gate | Result | Evidence |
|---|---|---|
| Bundle integrity and reference raster | PASS | 16 walls; 600x300 at 0.005 m; regenerated and independent GEOS pixel mismatches 0; expected two free-space components |
| Gazebo SDF parse/load | PASS | Gazebo Harmonic server 8.11.0 accepted the SDF and loaded world `map_260905` with DART |
| Gazebo physics/collision | FAIL | DART reported that mesh construction is unimplemented and could not create the Rosy base and attached mesh collision geometries |
| Gazebo to ROS sensor bridge | FAIL | Gazebo `/clock`, scan, odom existed and sim time advanced, but ROS received zero clock, scan, odom, or map messages |
| SLAM map generation | NOT RUN / BLOCKED | `slam_toolbox` had no usable scan/odom stream; Nav2 rejected malformed/empty map updates |
| Autonomous complete traversal | NOT RUN / BLOCKED | Goals were intentionally withheld after collision and sensor gates failed |
| CORE robot API | FAIL | CORE exited with `AttributeError: 'RosyCoreNode' object has no attribute 'core_common'` before opening port 18080 |
| Fleet server/UI contract | PASS (isolated) | Live Fleet server on 18090 served console/API; focused server + Chromium tests: 10 passed |
| Live Fleet robot monitoring/control | FAIL | `/api/fleet/state` reported `online: 0`, `total: 1`, robot `online: false`, `ConnectError` |
| Physical Device/FIELD acceptance | NOT RUN | Gazebo evidence never substitutes for Pinky Pro device or field evidence |

## Immutable inputs

- Bundle world: `src/core/control/map/map_260905_update_v2/worlds/map_260905.world`
- World SHA-256: `3f2e3a822cbf72223634d173d49bd3626c0281e8f433cd54e766134bffa15528`
- Original/source world SHA-256 recorded by the bundle: `8475464857322d71f6e492171419bf285e7bd034089b90ad59d6f106b0941072`
- Spawn requested: `(-0.20, 0.27, 0)`
- Simulation footprint: square `0.12 m x 0.12 m`; global footprint padding `0.03 m`
- Simulation-only inflation override: `0.12 m`
- ROS domain: first attempt 239 (invalid for DDS port mapping), corrected attempts 219
- Gazebo partition: `rosy_map_v2_260920`

## Static checks

The dependency-complete temporary environment ran:

```text
python scripts/validate_bundle.py
python -m unittest discover -s tests -v
gz sdf -k worlds/map_260905.world
```

Results:

- `PASS_STATIC_CHECKS_ONLY`
- all model semantics unchanged
- 16 walls and matching visual/collision pairs
- map resolution 0.005 m, 600x300 pixels
- regeneration mismatches 0; independent GEOS mismatches 0
- disconnected lower X pocket preserved
- 18 unit tests passed
- Gazebo SDF validation: `Valid.`

## Runtime attempts

### Attempt 1: rejected domain

The first isolated launch used ROS domain 239. DDS rejected the calculated UDP
ports `67160/67161` because the domain exceeds this transport's valid range.
The owned launch was stopped and domain 219 was checked empty before retry.

### Attempt 2: `slam_nav` plus CORE

Gazebo loaded and ran the exact v2 world at approximately 0.66 real-time factor.
Gazebo Transport advertised clock, scan, odom, IMU, TF, and joint-state topics.
ROS nodes and topic endpoints were discovered, but bounded subscriptions
received no clock, scan, odom, map metadata, or map messages.

An explicit absolute-topic diagnostic bridge used the same domain, partition,
and CycloneDDS implementation. It also delivered zero messages. A ROS-only
String probe succeeded across two processes, while a Gazebo Bool probe did not
cross `ros_gz_bridge`. This isolates the observed data failure to the
Gazebo-to-ROS bridge path rather than ROS DDS discovery or the v2 LiDAR topic.

In the same run:

- DART could not construct the robot's mesh collision geometry.
- CORE reached `ros_bridge ready` and then exited at `core/node.py` while
  referencing the nonexistent `self.core_common` attribute.
- Nav2 received malformed/empty map updates and reported the sensor/robot
  outside its default map bounds.

### Attempt 3: localhost Gazebo transport

The archived known runner set `GZ_IP=127.0.0.1`, unlike the current launcher.
A minimal `mode:=slam`, `core:=false` retry added only this variable. Gazebo
publisher/subscriber discovery moved to `127.0.0.1`, but ROS still received zero
clock, scan, odom, or map messages. The hypothesis was rejected and the session
was stopped without motion.

## Fleet evidence

The Fleet console was run separately on `127.0.0.1:18090`, using a manifest for
the failed CORE endpoint `127.0.0.1:18080`. Its live state was:

```json
{
  "fleet": {"name": "rosy-site", "online": 0, "total": 1},
  "robots": [{
    "robot_id": "rosy_01",
    "online": false,
    "error": {"reachable": false, "code": "ConnectError", "message": "All connection attempts failed"}
  }]
}
```

The console HTML returned HTTP 200 with its expected same-origin CSP. Focused
Fleet server and optional Chromium rendering tests passed (`10 passed in
2.28s`). The saved `fleet_console_mock.png` is a mock-API UI contract image,
not live robot proof. The in-app browser runtime had no available browser
backend, so no live console screenshot was captured.

## Required next gates

1. Make the v2 physics engine compatible with the Rosy collision model, or use
   accepted primitive collision geometry; rerun collision loading before motion.
2. Restore Gazebo-to-ROS clock/scan/odom flow and prove fresh messages with one
   isolated robot.
3. Fix and regression-test CORE startup so its API remains reachable.
4. Only then run progressive SLAM coverage, save a fresh map, compare it with
   the oriented 16-wall ground truth, and collect continuous/swept collision
   evidence.
5. Verify the same run ID in CORE and Fleet, then keep physical Pinky Pro
   acceptance as a separate Device/FIELD gate.
