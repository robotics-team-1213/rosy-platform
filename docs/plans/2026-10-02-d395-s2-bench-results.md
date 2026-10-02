# D-395 S2 Gazebo bench — results (4 robots, sim only)

P2-8 of [the fleet-assisted localization plan](2026-10-01-fleet-assisted-localization-plan.md): S2 is S1 plus simultaneous re-arbitration and homing in traffic, with zero collisions. [D-395](../adr/D-395-fleet-assisted-localization.md) rev. 9 closed S1 ([S1 results](2026-10-02-d395-s1-bench-results.md)) and names S2 as the next step.

**Verdict: S2 not completed — the host is too slow.** See "S2 2026-10-02" below. Only s2a (the 4-robot power-on) finished, once, and it passed.

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

## S2 2026-10-02

The slot ran 18:35–21:35 KST, on branch `test/d395-s2-bench`. Isolation was `GZ_PARTITION=rosy_d395e`, `ROS_DOMAIN_ID=99`, CORE on 18940–18943 and Fleet on 18995. Raw logs are in `X:\DevTemp\rosy-d395-s2\<run>\`: `run.json` where the bench saved one, plus `driver.log`, `launch.log`, `fleet.log` and `load.txt` (WSL load every 15 s). The folder also holds the scripts.

**Verdict: S2 not completed — the host is too slow.** Four robots ran Gazebo at an average RTF of about 0.02 (0.0196–0.0259 per window). At that speed one power-on took 28 min wall, so no run reached s2c or s2b. s2d got as far as Fleet's hold and release, and the drivers never translated.

| Scenario | Runs | Result |
|---|---|---|
| (s2a) 4-robot power-on | q1 | **1/1 pass** (details below) |
| (s2d) homing in traffic | q1 (q0) | **not completed**: Fleet held both drivers correctly, released them when every robot was trusted, and they only turned toward their first goal before the stop |
| (s2c) forced mirror | — | not reached |
| (s2b) simultaneous pickup | — | not reached |

**q1 s2a detail:**
- r1 and r2 were LOCALIZED by `slot` at 6.7 sim s; r3 and r4 by `peers` at 38.5–38.7 sim s.
- Errors were ≤ 1.3 cm / 1.0°.
- 4 Fleet decisions, all at the truth: 0 mirror decisions and 0 human decisions.

### Runs

| run | Nav2 | wall | sim reached | avg RTF | WSL 1-min load | outcome |
|---|---|---|---|---|---|---|
| q0_uncomposed | separate processes (default) | 18:41–19:12 | 32.7 s at 1463 s wall | 0.022 | 4.5 → 159 | r1, r2 (`slot`) and r3 (`peers`) LOCALIZED, r4 rotating. Stopped by hand: hopeless speed. The bench was interrupted twice (my stop script's fault), so there is no `run.json`. |
| q0_composed_noload | `nav_composition:=true` (new opt-in) | 19:27–19:58 | 53 s | 0.03 | 27–35 | Nav2 never loaded into the 4 containers: no map, no AMCL, every robot UNKNOWN. Stopped. |
| q1 | separate processes | 20:02–21:01 | 85.1 s at 3483 s wall | 0.024 | 11 → 96–150 | s2a passed. s2d started; drivers held, then released, then rotated in place only. Stopped at 21:00 for the hard stop. |

**Where the CPU went.** Background load was 4.5 at 18:35 and 11–30 between runs. The docker VM shares the kernel, so the WSL load includes non-Rosy containers.

- **q0_uncomposed:** about 70 processes, 32 of them runnable. CPU split 59 % user and 32 % system. Gazebo (`ruby`) got 36 %.
- **q0_composed_noload:** Nav2 never loaded, and still Gazebo used 120–136 % and four CORE processes 27–54 % each. Gazebo alone reached RTF 0.02–0.07. So Gazebo with 4 robots is the limit even before Nav2 runs.

### q1 (s2a + s2d)

Times are wall seconds since launch, with sim seconds in parentheses.

| robot | CANDIDATES | LOCALIZED | cue | error |
|---|---|---|---|---|
| r1 (square A) | 179 (1.6) | 430 (6.7) | slot | 0.6 cm / 0.1° |
| r2 (square B) | 161 (1.4) | 430 (6.7) | slot | 0.8 cm / 0.7° |
| r3 (off-slot) | 180 (1.7) | 1689 (38.7) | peers | 0.4 cm / 1.0° |
| r4 (off-slot) | 181 (1.7) | 1679 (38.5) | peers | 1.3 cm / 0.6° |

**Pass bar:**
- **Human decisions:** 0.
- **Mirror decisions:** 0 of 4. All 4 were at the truth, judged by `d395_s2_summary.py` against the Gazebo trail.
- **Collisions:** none. The closest pair in 572 truth rounds was r1–r3 at 0.889 m. No robot translated, so this proves little.
- **Ladder:** Fleet sent `rotate_in_place` to r3 and r4 ("held []": no Fleet goal existed yet).

**s2d.** The traffic started at 436 s (6.9 sim s). Then:
- r1 and r2 were LOCALIZED, and r4 was in its rotation.
- **Fleet held both goals** as `LOCALIZATION_UNTRUSTED`, `blocked_by rosy_03`. r3 had never been trusted, so it blocks the whole track (`trust.blocks`). Fleet had dispatched each goal, then cancelled it and confirmed the cancel (`dispatch_attempted`, `cancel_confirmed`).
- **Fleet released the queue** at 1734 s, 45–55 s wall after r3 and r4 became anchors. This is the designed order: no Fleet goal moves while an unlocalized robot could be anywhere.
- From release to the stop (about 40 sim s), r1 and r2 turned about 1 rad and 0.4 rad in place toward their first goals and travelled 0.000 m (truth).
- Under this load CORE `/robot/state` reads timed out (20 s curl), and the bench re-posted a goal once while Nav2 was still active (`502 NAVIGATION_ACTIVE`).
- So s2d has no movement and no leg finished. This is not a pass.

### Findings

- **F1. [Safety] Fleet can record a pre-D-395 ("legacy") pose as a robot's last trusted pose at power-on.**
  - In q0, Fleet's first `/api/fleet/state` read came at 26 s, before loc_assist was up. All four robots read `localization: null`, so the badge said `legacy: true, trusted: true`.
  - `FleetConsole._remember` → `trust.trusted_xy` stores the pose of a LEGACY row in `_trusted`. That pose is the odom pose at power-on, not a map pose.
  - Later the same robots went UNKNOWN/CANDIDATES. Fleet then saw an untrusted robot *with* a last trusted pose, so it applied the 0.45 m keep-out around that stale odom point instead of blocking the whole track.
  - **Evidence:** in q0, while r4 was CANDIDATES and rotating and had never been LOCALIZED, Fleet sent r1's and r2's goals to CORE (`POST /api/v1/navigation/goal 200` at 18:45:41 and 18:45:58). The fleet log has no cancel at that time.
  - In q1 Fleet's first read came at 123 s, after loc_assist, so `legacy: false`. There the same goals were held, as designed.
  - **Proposal (separate lane, not fixed here):** `_remember` should not treat a LEGACY row as trusted once the robot has ever reported `localization`. Or it should accept a trusted pose only in the map frame. A CORE that will report `localization` should send `UNKNOWN` (not `null`) from its first state.
- **F2. Composed Nav2 does not start in gz_multi.** With `nav_composition:=true` (new, opt-in, default off), the four `component_container_isolated` processes started, but nothing loaded into them in 30 min: no map server, no AMCL, no lifecycle activation. The launch comment had warned of this race. The device path (`hardware.launch.py`) composes, so the sim path needs its own fix before it can use composition.
- **F3. The bench under load.**
  - CORE state reads time out, so the s2d re-post rule acted on stale navigation states once (`NAVIGATION_ACTIVE`).
  - `stop_q.sh` signalled both the bench and its `timeout` wrapper, and the double SIGINT aborted the bench's own cleanup (q0). This was fixed for q1, which stopped cleanly and saved `run.json`.
  - `kill_partition.sh` stops what is left by `GZ_PARTITION`, my own only.

### Recommendation for running S2

1. **A dedicated or idle host.**
   - S1 two-robot runs reached RTF 0.37–0.64 on an idle host, against 0.1–0.16 when the host was shared.
   - Four robots need roughly twice the CPU, so plan on a machine with ≥ 8 free cores and no other Gazebo or docker load.
   - Expect a full run (power-on, traffic, mirror, pickup) to need about 250–300 sim s. At RTF 0.3 that is about 15 min; at 0.02 it is 4 h.
2. **GPU rendering for `gpu_lidar`.**
   - This host has an AMD Radeon 860M, `/dev/dxg`, WSLg and Mesa's `d3d12_dri.so`.
   - Gazebo loads `gz-rendering-ogre2`. I did not verify whether it used `d3d12` or the `llvmpipe` software renderer. No `glxinfo` is installed.
   - Check: `glxinfo -B` (`mesa-utils`) with `GALLIUM_DRIVER=d3d12`. Then compare Gazebo's CPU with 4 robots at rest.
3. **Sim-only physics step.**
   - The map_v2_fleet world has no `<physics>` block, so Gazebo runs its default 1 ms step.
   - The repo's rig tools already use 5 ms: `src/runtime/sensing/tools/gz/rig_rate.py` sets it through `/world/<w>/set_physics` at run time, and `prepare_track_world.py` writes it into the world.
   - Setting `max_step_size` 0.005 for the bench cuts physics work about 5×. It changes no robot code and no sensor rate. Verify that the diff-drive and Nav2 behave the same, as the rig did.
4. **Lidar.** There is no sim xacro argument for the lidar: 640 samples at 10 Hz are hard-coded in `rosy_gz.urdf.xacro`. Adding a sim-only argument is possible. But loc_assist scores those beams, so fewer samples would change the localization inputs. Do this only with a separate decision.
5. **Composition.** F2 must be fixed (the loading race in `gz_bringup_launch.xml` with a namespaced container) before `nav_composition:=true` can cut the process count by about 40.
6. **Run order on a fast host.** Unchanged: `q1:t+c q2:t+c q3:b q4:b`, then `q5:t+c+b` if time is left.

### Commands (this slot)

```bash
bash /mnt/x/DevTemp/rosy-d395-s2/build.sh
LOAD_GATE=100 RUN_TIMEOUT=4900 BENCH_ARGS="--max-wall 4700 --min-rtf 0.01 --traffic-timeout 60" \
  DEADLINE=20:10 bash /mnt/x/DevTemp/rosy-d395-s2/run_series.sh q1:t+c
bash /mnt/x/DevTemp/rosy-d395-s2/stop_q.sh q1          # at 21:00 for the 21:35 hard stop
bash /mnt/x/DevTemp/rosy-d395-s2/kill_partition.sh     # "left: 0", ports free
python tools/sim/d395_s2_summary.py X:\DevTemp\rosy-d395-s2\q1
```

## S2 rerun attempt 2026-10-02 22:21–22:52 KST (aborted)

- New sim-only, opt-in launch args on `gz_multi.launch.py` (defaults unchanged): `physics_step:=<s>` (≤ 0.01, launches a world copy with that `<physics><max_step_size>`), `real_time_factor:=<x>`, `gpu:=true` (sets `GALLIUM_DRIVER=d3d12`).
- GPU: WSL on this host renders OpenGL with `llvmpipe` (Mesa 25.2.8, software), so `gpu:=true` changes nothing here.
- With `physics_step:=0.005` and 4 robots: RTF 0.017 after 70 s wall, WSL load 122. Top CPU users were the four `core` processes (~41 % each), Gazebo (`ruby`, ~28 %) and `loc_assist` (~24 %), so the physics step is not the limit; the per-robot stack is.
- WSL restarted at about 22:50 KST, ending the attempt; no scenario ran.
- Verdict: S2 cannot run on this host. It needs a machine with roughly 4× the free CPU, or the robots' CORE/loc_assist stacks spread over hosts. Logs: `X:\DevTemp\rosy-d395-s2b\`.
