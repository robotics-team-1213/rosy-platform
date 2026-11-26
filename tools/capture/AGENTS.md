<!-- Parent: ../AGENTS.md -->

# capture

**Parent context:** `../AGENTS.md`

Robot side of the edge-capture loop (D-379, D-465): short supervised drives over the CORE API on the operator PC, operator at the robot, Fleet watching. Data side: `learning/curation/perception/edge_capture_session.py`; run order in `learning/curation/perception/AGENTS.md` ("Edge-capture loop").

## For AI Agents

### Working In This Directory

- The RobotBody check before a nudge is advisory (user decision 2026-10-07): it prints `WARN` and the robot moves anyway. CORE's own stop stays authoritative. Do not turn it into a gate without the user.
- `edge_drive.py nudge` is MANUAL teleop within 0.08 m/s, 0.6 rad/s, 4 s, then IDLE; `drive` holds a 1 s deadman. These drives end with zero teleop + IDLE.
- `drivable_steer.py` (D-592): dry run unless `--drive`; then MANUAL teleop at most 0.03 m/s, |w| 0.4; the RobotBody LiDAR guard is a gate there.
- `cable_twist.py` (D-512/D-1034): turns are measured from LiDAR scans, never odometry; every step is refused unless `RobotBody.rotation_check` is clear; a robot the cable holds ends the run and asks a person.
- The LiDAR forward angle is the URDF nominal (`core_common.robot_body.PINKY_PRO`), refined by the accepted `lidar_mount` record (`--device`), overridden by `--lidar-forward-deg`. No hard-coded per-robot angle.
- `slam_pickup_pipeline.py` (D-986) ends in a deterministic stop; `site.{yaml,pgm}` install is atomic.
- Robot addresses, tokens and CA files go on the command line or in env only; examples use `<robot-ip>`.

### Testing Requirements

```bash
python -m pytest tools/capture/test -q -p no:cacheprovider
```

