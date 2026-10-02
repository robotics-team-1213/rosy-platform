# D-395 S2 Gazebo bench — results (4 robots, sim only)

P2-8 of [the fleet-assisted localization plan](2026-10-01-fleet-assisted-localization-plan.md): S2 is S1 plus simultaneous re-arbitration and homing in traffic, with zero collisions. [D-395](../adr/D-395-fleet-assisted-localization.md) rev. 9 closed S1 ([S1 results](2026-10-02-d395-s1-bench-results.md)) and names S2 as the next step.

**Status: bench ready, runs pending** (WSL booked by other sessions until about 21:00 KST).

## Pass bar

Per scenario, judged by `tools/sim/d395_s2_summary.py`:

- zero human input (no `localization.result` with `source: human`);
- every robot LOCALIZED within 5 cm / 5° of the Gazebo truth;
- zero Fleet decisions at a robot's 180° twin;
- zero collisions: the closest pair of robot centres in the truth trail stays at or above 0.22 m (2 × 0.11 m). gz_multi robots have no contact sensor, so there is no contact count;
- (s2c) the target leaves LOCALIZED within 15 sim s of the `initialpose` publish (rev. 6 window), and no other robot leaves LOCALIZED. CORE's `state_stale` rows do not count: they are its wall-time blip (S1 finding 6), not an accusation;
- (s2d) the homer was not yet LOCALIZED when the traffic started, and every leg ended with the truth within 0.25 m of its goal (an arrival at a yield bay does not count);
- (s2b) the drop layout passed its checks, with the stale-anchor trap armed.

## Layout q

Arena: the map_v2_fleet wall faces at x ±1.400, y ±0.625.

| robot | spawn (x, y, yaw) | role |
|---|---|---|
| r1 | (−1.26, 0.49, −90°), square A | slot; s2d driver; s2b lifted |
| r2 | (0.86, −0.52, 180°), square B | slot; s2d driver |
| r3 | (−0.70, −0.20, 180°) | off-slot |
| r4 | (0.20, 0.25, 0°) | off-slot; s2d homer; s2c target; s2b lifted |

`layout_problems` checks every layout the bench uses (spawn, the s2b drop layout, the s2d goals):

- **Walls:** 0.10 m on a square (B is 0.105 m from its wall, A 0.135 m) and 0.20 m elsewhere (Nav2's padded radius is 0.115 m).
- **Spacing:** spawn and drop points are at least 0.45 m apart (the untrusted keep-out). Goals keep 0.44 m (2 × 0.22) from the robots that stay put.
- **Anchors:** each off-slot robot has an anchor within `PEER_VIEW_M` 2.0.
- **No twin support:** no robot's 180° twin gets `peers` support from the layout. Placed objects are checked at 0.30 m, twice the arbiter's 0.15 m. A robot standing on another robot's twin is harmless, because no robot is an anchor for itself. The risk is a pair of robots that are each other's mirror, as square A and a robot at (1.20, −0.42) would be.

## Scenarios

- **(s2a) 4-robot power-on.** Every run is one. r1 and r2 localize by `slot`, then r3 and r4 by `peers` from those anchors.
- **(s2d) homing in traffic** (`--traffic`, during the power-on).
  - Trigger: r1 and r2 are LOCALIZED, and r4's ladder mission is `running` (or r4 is already LOCALIZED, which is recorded).
  - The bench then sends r1 and r2 two legs each through the Fleet console, `POST /api/fleet/robots/<id>/goal`:
    - r1: (−0.30, 0.42), then (−1.00, 0.40);
    - r2: (0.20, −0.25), then (0.95, −0.25).
  - Each first leg ends about 0.5 m from r4.
  - Fleet's keep-out, its hold (`hold_for_localization`) and its queue decide what moves. The bench records every reply (`accepted`, or `queued` with a reason) and re-posts only a goal that Fleet does not hold and Nav2 dropped (not `PLANNING`/`NAVIGATING`/`BLOCKED`, 30 s wall and 5 sim s after the post). Legs still open when the traffic times out are cancelled through `POST /api/fleet/robots/<id>/cancel`, so Fleet cannot release them during phases c and b.
- **(s2c) forced mirror** (phase `c`).
  - r4's twin goes straight into its AMCL (`/rosy_04/initialpose`).
  - The bench waits up to 30 sim s for r4 to leave LOCALIZED, then up to 150 sim s for all four robots to be LOCALIZED again.
  - Every other robot's exit from LOCALIZED is recorded as an accusation.
- **(s2b) simultaneous re-arbitration** (phase `b`).
  - `safety/pickup` true goes to r1 and r4 in parallel threads.
  - Both are teleported, held 3 sim s, then set down together. r1 goes to (0.45, −0.10, 90°). r4 goes to the twin of wherever it stands at that moment, (−0.20, −0.25, 180°) from its spawn. The drops, their checks and the trap are recomputed from the truth then, because the traffic phase moves r1 and r2.
  - **Stale-pose trap.** r4 lands on the twin of its own pre-pickup pose. If Fleet kept r4's old pose as an anchor, r1's twin would score `peers` 0.33 against the truth's 0.67 (`stale_trap`), so r1 would be dragged.
  - **"Not dragged":** both lifted robots re-localize at the truth, and r2 and r3 never leave LOCALIZED.

## Bench (tools/sim/d395_s2_bench.py)

- It subclasses the S1 driver (`d395_s1_bench.Bench`, which now takes `SCENARIOS` from the class).
- **Truth:** one `gz topic -e -n 1 -t /world/map_v2_fleet/pose/info` read per second gives all four model poses (`parse_pose_v`). A robot missing from it falls back to `gz model -m <name> -p`. Rows of one round share a time stamp, and `min_pairwise` takes the closest pair per round.
- **Timeouts are sim seconds.** `wait` ends at the sim timeout or at the wall cap `min(timeout / --min-rtf, --max-wall)`, 0.04 and 1500 s by default.
- **Fleet polling:** the bench reads `/api/fleet/state` every second, as the console UI does. Fleet's traffic, trust tracking and queue release run on that read, and S1 never made it.
- **Defaults:** `--partition rosy_d395e --domain 99 --api-port 18940` (CORE 18940–18943) `--fleet-port 18995`.
- `--check` prints the layout checks and the stale trap without ROS.

## Resource plan

- **Expected speed.** S1 run 4 averaged RTF 0.105–0.155 with two robots. Four robots double CORE, loc_assist, Nav2 and the bridges, so expect about 0.05–0.08.
  - At 0.06, the off-slot robots' ~43 sim s to LOCALIZED is about 12 min wall. A run with one phase is therefore 20–30 min.
- **Gazebo is headless** (`headless:=true`, no GUI client).
- **Sensors cannot be slowed without touching the robot.** The camera already renders only with a subscriber (`always_on 0`), and gz_multi bridges no camera. The lidar's 10 Hz and the IMU's 100 Hz are fixed in `rosy_gz.urdf.xacro`, with no launch argument, and lowering them would change the robot's inputs. So no sensor rate is changed.
- **Load gate.** Each run waits for a WSL 1-min load under 15, for at most 5 min. A load sample is taken every 15 s.
- **Run order** (3 h box, s2c and s2d first). Every run is also an s2a sample.

  | run | flags | covers |
  |---|---|---|
  | q1 | `t+c` | s2a, s2d, s2c |
  | q2 | `t+c` | s2a, s2d, s2c |
  | q3 | `b` | s2a, s2b |
  | q4 | `b` | s2a, s2b |
  | q5 | `t+c+b` | all, if time is left |

  Each run is capped at 45 min wall (`timeout 2700`).
- **Isolation and stop.**
  - The bench stops only its own process groups, then any process left carrying `GZ_PARTITION=rosy_d395e`.
  - `leftover.sh` lists such processes and the ports. It never kills anything.

## Commands

```bash
# WSL, after "S2 GO"
bash /mnt/x/DevTemp/rosy-d395-s2/build.sh
DEADLINE=23:40 bash /mnt/x/DevTemp/rosy-d395-s2/run_series.sh q1:t+c q2:t+c q3:b q4:b q5:t+c+b
bash /mnt/x/DevTemp/rosy-d395-s2/leftover.sh
# Windows
python tools/sim/d395_s2_bench.py --check --out unused
python tools/sim/d395_s2_summary.py X:\DevTemp\rosy-d395-s2\q1 ...
```
