# D-395 S1 Gazebo bench — results (2 robots, sim only)

P2-8 of [the fleet-assisted localization plan](2026-10-01-fleet-assisted-localization-plan.md), contract [2026-10-01-d395-phase2-interfaces.md](2026-10-01-d395-phase2-interfaces.md), [D-395](../adr/D-395-fleet-assisted-localization.md) rev. 1–4.

- **Final runs (`p7*`):** local `main` 5b346b2b (Phase 2 integration plus the P2-7 ladder missions, API v1.73) merged into `feat/d395-s1-bench`.
- **Earlier runs:** `a1–a3`, `b1–b6` and `t1–t2` ran on main 148af568, before P2-7, when Fleet only logged the ladder. They still back findings 1–3 and give the forced-mirror result on the b layout. `a1_premerge` and `smoke5` ran on `feat/d395-p2-integration` 67cb5064.
- **Raw logs:** `X:\DevTemp\rosy-d395-s1\<run>\` holds `run.json`, `driver.log`, `launch.log`, `fleet.log` and `cpu_120s.txt`.

**Verdict: S1 not passed.**

| Scenario | Result | Notes |
|---|---|---|
| (b) both robots on squares | **9/9 pass** | zero human input, errors ≤ 1.6 cm / 0.2° |
| (a) one robot off-slot | 2/3 | |
| (d) pickup | **3/3** | needed the P2-7 rotation; it was 1/3 before P2-7 |
| (c) forced mirror | not detected, 0/5 | |
| (l) lone robot off-slot | 0/3, as expected | reaches `needs_human` |

The system never sent a mirror decision and never locked a robot into a mirror pose itself. The only locks are the injected test faults. After such a fault, though, the locked robot gives its peer a *positive* `peers` cue for the peer's twin. Only the 1.0 margin stopped the lock from spreading (finding 3). The other blockers are in the robot node and the Fleet cues, not in the bench (findings 1, 2, 4 and 6).

## Setup

- **Environment:** WSL Ubuntu, ROS 2 Jazzy, Gazebo Harmonic 8.11.
  - Workspace: `/rosy_d395_ws`, a tar copy of the worktree, built with `colcon build --symlink-install --packages-up-to gz_sim core control fleet navigation description`.
  - Isolation: `GZ_PARTITION=rosy_d395`, `ROS_DOMAIN_ID=93`, CORE APIs on 18930/18931, Fleet console on 18990.
- **World:** `map_v2_fleet.world`, the catalogued one.
  - The `_real` variant is not in the gz_multi catalogue, and gz_multi does not bridge a camera. So the `square` and `paint` cues are absent in every run, and `lane_to_stopline` has no lane to follow.
  - The Nav2 map is only the outer wall rectangle. It is 180° symmetric, so every search returns exactly the true pose and its twin.
- **Launch:** `gz_multi` with `mode:=nav core:=true headless:=true loc_assist:=true seed_initialpose:=false` and per-robot `spawn_poses` (both arguments are new, see below). AMCL is not seeded, so power-on is UNKNOWN as D-395 §2 requires.
- **Fleet:** `fleet console --robots <gz_multi robots.yaml>`.
  - The localization service is on (default) and the overhead cue is off (default).
  - `--localization-lane-rules` points to the map_v2_fleet `lane_rules.yaml`, which gives squares A and B as slots.
- **Ground truth:** `gz model -m rosy_0N -p`, judged by `tools/sim/d395_truth.py`.
  - Pass: within 5 cm and 5°.
  - Mirror lock: within 25 cm / 60° of the truth's 180° twin.
- **Spawn poses (x, y, yaw):**
  - (a) r1 (−1.26, 0.49, −90°) on square A along its axis; r2 (−0.70, 0.15, 180°) off-slot, 0.66 m away.
  - (b) r1 (0.86, −0.52, 180°) on square B facing −x; r2 (−1.26, 0.49, 90°) on square A. The robots are 2.35 m apart, outside `PEER_VIEW_M` 2.0.
  - (l) r1 alone at (−0.70, 0.15, 180°).
  - (d) r1 is teleported to (−0.75, 0.30, 0°), 0.54 m from r2. Its twin is 2.08 m from r2.
- **Host load:** the WSL VM shares the PC with other sessions, and Windows CPU was 88–99 % busy.
  - WSL 1-min load during runs: 13–53.
  - My stack alone uses about 4 cores: gz 73 %, each CORE 35 %, each loc_assist 25 %, each joint_state_publisher 20 %.
  - Gazebo RTF median: 0.13–0.30 for the earlier runs, 0.33–0.54 for the final runs, and 1.0 for the lone runs.
  - Times below are wall seconds since launch, with sim seconds in parentheses. Use the sim seconds to compare runs.

## Results (final, main 5b346b2b)

### (a) r1 on square A, r2 off-slot, simultaneous power-on

| run | load 1-min | RTF med | r1 CANDIDATES → LOCALIZED | r1 error | r2 CANDIDATES → LOCALIZED | r2 error | rejects | mirror locks |
|---|---|---|---|---|---|---|---|---|
| p7a1 | 5 → 34 | 0.33 | 31 (8.9) → 56 (17.0), slot | 0.3 cm / 0.0° | 33 (9.5) → 153 (48.5), peers, after a 360° rotate | 0.8 cm / 0.1° | r1 1×, r2 2× | 0 |
| p7a2 | 23 → 31 | 0.41 | 27 (10.2) → 50 (19.2), slot | 0.4 cm / 0.0° | never: after the rotate, no object seen; `needs_human` at 120 s | AMCL 20 cm / 84° off | r1 1×, r2 1× | 0 |
| p7a3 | 21 → 35 | 0.38 | 28 (10.5) → 51 (20.0), slot | 0.3 cm / 0.0° | 29 (11.0) → 136 (54.2), peers, after a 360° rotate | 0.8 cm / 0.4° | r1 1×, r2 2× | 0 |

- r2 has only the `peers` cue: it is off-slot and has no camera.
- Its first decision is always rejected (finding 1).
- In p7a1 and p7a3 the P2-7 `rotate_in_place` made it search again, the new report saw r1, and a later decision passed.
- In p7a2 the re-search saw no object (finding 2). With the true pose scoring peers −1 and the twin 0, the twin led by 2.0 and nothing could be sent (finding 3).
- Before P2-7 the same layout was 0/3 (`a1–a3`), because nothing made the robot search again.

### (b) r1 on square B facing −x, r2 on square A

| run | load 1-min | RTF med | r1 CANDIDATES → LOCALIZED | r2 CANDIDATES → LOCALIZED | errors r1 / r2 | rejects | mirror locks |
|---|---|---|---|---|---|---|---|
| p7b1 | 23 → 25 | 0.54 | 25 (11.1) → 43 (19.7) | 26 (11.8) → 48 (21.8) | 0.3 cm 0.2° / 0.3 cm 0.1° | 1× each | 0 |
| p7b2 | 22 → 27 | 0.35 | 25 (11.0) → 44 (20.0) | 26 (11.6) → 46 (20.9) | 0.4 cm 0.1° / 0.3 cm 0.1° | 1× each | 0 |
| p7b3 | 30 → 33 | 0.37 | 25 (11.0) → 47 (20.1) | 27 (11.8) → 50 (21.4) | 0.5 cm 0.1° / 0.3 cm 0.0° | 1× each | 0 |

- Every decision carried `slot`. The gap was 1.48–1.51: the slot weight 1.5 against equal scan fits.
- Each robot needed two decisions because the first is always rejected (finding 1). Without that, LOCALIZED would come about 8 sim s earlier.
- Power-on to LOCALIZED took 19.7–21.8 sim s. The earlier runs `b1–b6` agree: 6/6 pass, 14.2–21.1 sim s, errors ≤ 1.6 cm / 0.1°.

### (d) pickup during a drive (r1, b layout, after power-on)

| run | goal → motion | `safety/pickup` true → SUSPECT | drift while held | set-down → LOCALIZED | end error r1 | rejects | mirror locks |
|---|---|---|---|---|---|---|---|
| p7b1 | accepted, robot did not move (finding 5) | 2.0 s wall | 0.0 m | 161 → 257 (68.0 → 105.8), peers, after a 360° rotate | 0.9 cm / 1.4° | 2× (same pose) | 0 |
| p7b2 | same | 1.9 s | 0.0 m | 157 → 263 (65.9 → 107.7), same | 0.9 cm / 0.5° | 2× | 0 |
| p7b3 | same | 2.3 s | 0.0 m | 162 → 259 (65.2 → 102.5), same | 1.3 cm / 1.4° | 2× | 0 |

- **Halt.** The halt holds every time:
  - SUSPECT comes about 2 s after `ros2 topic pub` returns.
  - Gazebo truth does not move while held.
  - CORE refuses new goals.
- **Re-localization path.** In all three runs it was the same:
  1. The search sees r2 and Fleet decides `peers`.
  2. The 3 s check rejects the decision.
  3. Fleet decides the same pose again, and the check rejects it again.
  4. The ladder rotates the robot through 360°.
  5. The third decision is accepted.
- **Before P2-7 (`b1–b3`): 1/3.** With no rotation, nothing made the robot search again. r1's report had no object in b1 (after one reject) and in b2 (from the start), and r1 then stayed CANDIDATES.

### (c) forced mirror

- **Fault:** with both robots LOCALIZED, r2's 180° twin is published straight to `/rosy_02/initialpose` (covariance 5 cm / 5°). The bench then watches for 60 s wall.
- **Peer report:** next it pulses `safety/pickup` true→false on r1 without moving it. That makes r1 report candidates, so the Fleet monitor gets peer observations of r2.

| run | layout | r2 after the fault | detected (robot or Fleet) | r1 after its pulse | end state |
|---|---|---|---|---|---|
| p7a1 | a (r2 0.66 m from r1) | LOCALIZED at the twin, 1.43 m / 179.9° off | no; 12 r1 reports placed r2 at its true position (the twin of what r2 reported), no SUSPECT | the twin led with **+1 peers** by 0.5, then r1 lost the object, the truth led by 3.5, and r1 re-localized correctly (slot) at 311 (108.1) | r1 ok, r2 locked |
| p7a3 | a | same, 1.43 m / 179.9° | no | the twin led with **+1 peers** by 0.48–0.50 to the end | r1 CANDIDATES, r2 locked |
| b4–b6 (before P2-7) | b (2.35 m apart) | same, 2.70 m / 179.8–179.9° | no; r1's reports had no objects | the twin led by 0.5 (the truth had peers −1); r1 stayed CANDIDATES | r1 CANDIDATES, r2 locked |

p7a2 never had both robots LOCALIZED, so its (c) phase did not run.

As rev. 4 §5 predicts, nothing notices a LOCALIZED robot at its twin. The scan fit at the twin is as good as at the truth, so the robot keeps LOCALIZED. The Fleet monitor sees peers only through a CANDIDATES robot's report. In the a layout it *had* that evidence and still did not act (finding 7). Meanwhile the locked robot poisons its peer: r1 is pushed toward its own twin (finding 3).

### (l) one robot off-slot, no asymmetric cue (P2-7 ladder)

| run | RTF med | ladder | motion (Gazebo truth) | end |
|---|---|---|---|---|
| p7l1 | 0.99 | `rotate_in_place` sent at 10 s, done; `to_square` refused (unsupported); `lane_to_stopline` sent, aborted `lane_lost` after ~5 s; `needs_human` at 120 s | full 360° in place (turned 6.05 rad, 0.0 m travelled, xy within 0.1 mm); `lane_to_stopline` 0 m | CANDIDATES, truth and twin tied (gap 0.0) |
| p7l2 | 0.99 | same | 6.14 rad, 0 m | same |
| p7l3 | 1.00 | same | 6.07 rad, 0 m | same |

**First sim evidence of P2-7 mission motion.**

- `rotate_in_place` turns the robot through one full revolution in place at about 0.25 rad/s:
  - 360° in 24 sim s at RTF 0.33.
  - 32–33 s wall at RTF 1.
- `rotate_in_place` is refused with `path_not_clear` for a robot on square A: there is a return at 0.07–0.08 m, the wall 0.14 m away. It is accepted elsewhere.
- `lane_to_stopline` aborts `lane_lost` within 5–10 s wall and travels 0.00 m (turned ≤ 0.03 rad), because gz_multi has no camera.
- While `rotate_in_place` still runs, Fleet alternates `to_square` (refused `unsupported`) and `lane_to_stopline` (refused `busy`) every ~2.4 s: 13–20 `to_square` refusals per two-robot run, 1 per lone run.
- A lone robot with no cue cannot be resolved by the ladder that exists today. Nothing breaks the tie, and it reaches `needs_human` at 120 s, which is the intended last rung.

## Findings

1. **An injection passes the 3 s check only once AMCL already sits at that pose.**
   - **Data:**
     - Every first decision for a pose was rejected `inject_rejected`, with the scan fit at 0.01–0.02 (it should be 0.97–0.99): 15/15 in the final runs, 18/18 earlier, 4/4 pre-merge.
     - Repeats of the same pose: 15 accepted and 5 rejected in the final runs; 16/16 and 4/4 accepted before.
     - After a pickup the same pose was rejected twice, and the decision after the ladder's 360° rotation was accepted (p7b1–b3).
   - **Cost:** one extra search and hold at power-on, about 8 sim s. After a pickup the robot needs the ladder's rotation.
   - **Hypothesis:** the check scores scans through a map→odom transform that does not carry the injected pose yet. Scans queued from before the injection are scored after `settle_s`. And AMCL republishes its correction only after its own update, which D-393's `update_min_d/a` gates.
   - **Proposal (code, not a default):**
     - Score the check at the injected pose composed with the odom delta since injection, or start `settle_s` at the first AMCL update stamped after the injection.
     - Drop scans stamped before the injection.
     - Report the check's own reason (`fit_low`, `stale_scan`); today it is only `inject_rejected`.
2. **Peer detection is marginal at 0.6 m.**
   - `unmapped_objects` runs on the strided scan: `scan_stride` 4, so 160 of 640 beams, 2.25° apart.
   - A Pinky 0.6 m away covers about 4.5°, which is 2 strided beams, exactly `MIN_POINTS` 2. At 2.35 m it is one beam, and it was reported 1/36 times.
   - A live scan in `a2` shows r1 at 0.64–0.67 m in 146–150°, against the wall at 0.79–0.85 m behind it.
   - At stride 4 the peer at about 0.6 m was in 38 of 45 reports (84 %). One miss is enough for finding 3:
     - r1 on square A seeing r2: 14/16;
     - r2 seeing r1, which is 0.14 m from the top wall: 12/16;
     - r1 after a pickup seeing r2: 12/14;
     - r1 after a pickup in the a layout (`a1_premerge`): 0/1.
   - **Tuning runs `t1`, `t2`** set `scan_stride` 2 through `ros2 param set` after launch. The peer was in 8/8 reports and both robots localized in both runs. The first searches may still have started at stride 4, so this is suggestive, not proof.
   - **Proposal:** compute `unmapped_objects` on the full-resolution scan, which is one pose and cheap, and keep the stride for the global search.
3. **Safety: the `peers` cue can favour a robot's twin.** Two cases:
   - **Missed peer.** `peers_cue` gives −1 for a peer in view that is not seen. With the peer more than 2 m from the twin, the twin led by 2.0, twice the margin. This happened in 6 requests: a1/a2/a3/p7a2 for r2, and b1/b2 (before P2-7) for r1 after a pickup. Nothing was sent only because the twin's `peers` was 0, not positive (rev. 3).
   - **Mirror-locked peer.** In p7a1 and p7a3, r1 saw the real r2, and its twin placed that object exactly on r2's mirror-locked reported pose. So the twin got `peers` **+1**, a positive asymmetric cue that would be carried, and led by 0.48–0.50. Only the margin 1.0 against the slot weight 1.5 stopped a mirror decision. With the slot weight below 1.0, or an off-slot observer, the lock would spread to r1, and r1's 3 s check cannot reject a mirror (rev. 3).
   - **Proposals:**
     - An observer that reports no objects gives no peer evidence: peers 0 for every candidate instead of −1.
     - Don't let `peers` decide while any LOCALIZED peer is itself unconfirmed, or require `peers` to agree with a second cue.
     - Rev. 4 §5's follow-up, LOCALIZED-to-LOCALIZED observations, is what would catch the locked peer.
4. **Without P2-7, a tie or a missed cue is permanent.**
   - In CANDIDATES the robot searches again only after it moves 5 cm / 10° (`search_due`).
   - P2-7's `rotate_in_place` supplies that motion and turned a1–a3 (0/3) into p7a1–a3 (2/3), and pickup from 1/3 into 3/3.
   - A robot on square A gets no rotation (`path_not_clear`).
   - **Proposal:** while CANDIDATES, also re-search every `retry_s` when stationary. It is cheap, and it re-rolls finding 2 without motion.
5. **The pickup "drive" never moved in any run.**
   - The goal was accepted (`200`, `NAVIGATING`), but RPP logged "detected collision ahead!" from the start.
   - Square B is 0.105 m from the bottom wall. The sim costmaps use the padded circumscribed radius 0.115 m (`gz_multi._nav_config`), so a robot on square B already sits in the footprint's collision band. Square A is 0.14 m from its wall.
   - The pickup chain (halt, SUSPECT, re-localization) was exercised from an active goal, not from motion.
   - Using the squares as start slots conflicts with Nav2's conservative sim footprint. A drive from a square needs a first move of at least 0.12 m, or a review of the sim padding.
6. **CORE's `state_stale` uses wall time, while the robot's state cadence uses ROS time.**
   - CORE marks the status UNKNOWN after 3 s wall without `localization/state`. loc_assist publishes every 0.5 s of its node clock, which is sim time.
   - Below RTF ≈ 0.17 the state flaps:
     - 0–61 `state_stale` transitions per earlier run (157 over a1–b6), and 0 in the final runs at RTF ≥ 0.33.
     - CORE cancels autonomy on each flap and refuses goals (`409 NOT_LOCALIZED`, 5 of 35 goal posts pre-merge).
     - The Fleet ladder, also wall time, reaches `needs_human` while the robots have lived only a few sim seconds.
   - Today this is sim-only. On a Pi it matters only if the executor stalls for 3 s.
   - **Fix:** run the sensing node's state timer on the wall clock, or make CORE's stale window ROS time under `use_sim_time`.
7. **The Fleet monitor (§9) cannot hold a disagreement across report gaps.**
   - It uses a report only within 1 s of first seeing it, and it forgets a hold after 1.5 s without evidence. So it needs fresh reports no more than 2.5 s apart in wall time.
   - The robot re-reports every 2 s of *ROS* time. In p7a1 r1's reports came 3.8–6.7 s apart at RTF ~0.4. Twelve reports each placed r2 at its true position (the twin of r2's reported pose), and no SUSPECT was posted.
   - At RTF 1 the gap would be 1 s, inside the 1.5 s hold by 0.5 s, so it would work on a real robot, but with little margin.
   - **Proposal:** count disagreeing *reports* (for example 2 distinct report stamps) instead of wall-time continuity.
8. **Search time** was 3.6–71.8 s wall against a 3 s budget, over 110 logged searches:
   - 3.6–4.7 s at RTF 1 (lone runs);
   - 4.5–9.5 s in the final runs;
   - up to 15.8 s in the earlier runs, 24 s pre-merge, and one 71.8 s outlier in `t2`, under the heaviest load.
9. **Bench and test defects fixed here:**
   - The catalogued map_v2_fleet world did not load at all under colcon's isolated install (`model://control/...` unresolved). Fixed in `gz_multi`.
   - Two robots exceed rmw_cyclonedds' localhost participant-index cap: loc_assist, the last node up, died with `failed to create domain`. The bench sets `MaxAutoParticipantIndex` 120 through `CYCLONEDDS_URI`.
   - `test_nav_mode_starts_loc_assist_per_robot_unless_turned_off` failed on the integration branch because `.location` is an object repr before execution. Fixed in the test helper.
   - Fleet logs refusals at INFO only. The bench runs Fleet with `logging.basicConfig(INFO)` to see them.
10. **Safety in motion:** no collision, no motion while held, and no robot-made mirror lock. The open safety risk is finding 3, together with finding 7.

## Tuning proposal

| item | current | proposal | data |
|---|---|---|---|
| `slot` weight 1.5, margin 1.0 | slot decides alone (gap 1.48–1.51) | keep both; the margin must stay above the `peers` weight minus the slot weight, or the finding-3 lock spreads | 57/57 slot decisions picked the truth; truth and twin scan fits differed by ≤ 0.013 |
| `peers` −1 when the observer reports no objects | −1 | 0 (finding 3) | the twin led by 2.0 in 6 requests |
| unmapped objects on the strided scan | stride 4 | full scan for objects (finding 2) | stride 4: peer in 38/45 reports at 0.6 m and 1/36 at 2.35 m; stride 2 (t1, t2): 8/8 |
| injection check | scores through a stale map→odom | finding 1 | 37/37 first decisions rejected; 5 same-pose repeats rejected in the final runs |
| Fleet monitor hold | 1.5 s of wall-time continuity | N disagreeing reports (finding 7) | 12 disagreeing reports, no SUSPECT |
| ladder `to_square` | retried every 2.4 s for 35 s though unsupported | skip it while CORE says `unsupported` | 13–20 refusals per run |
| hold 2 s, fit 0.85, `PEER_VIEW_M` 2.0 | — | no change from this data | — |

**No default is changed in this branch.** Findings 1–4 and 6–7 are code changes in other lanes. The slot and margin defaults behaved correctly, and the margin is what stopped finding 3.

## Commands

```bash
# WSL, once: workspace and build (from the worktree on the Windows side)
tar -cf - src tools | wsl -d Ubuntu -- bash -c 'mkdir -p /rosy_d395_ws && cd /rosy_d395_ws && tar -xf -'
# then in WSL:
cd /rosy_d395_ws && source /opt/ros/jazzy/setup.bash
colcon build --symlink-install --packages-up-to gz_sim core control fleet navigation description

# one power-on (a, b or l) plus phases c (forced mirror) and/or d (pickup during a drive)
source /opt/ros/jazzy/setup.bash && source /rosy_d395_ws/install/setup.bash && cd /rosy_d395_ws
python3 tools/sim/d395_s1_bench.py --scenario a --phases c --out /rosy_d395_runs/p7a1 --localize-timeout 420
python3 tools/sim/d395_s1_bench.py --scenario b --phases d --out /rosy_d395_runs/p7b1 --localize-timeout 420 --drive-timeout 90
python3 tools/sim/d395_s1_bench.py --scenario l --out /rosy_d395_runs/p7l1 --localize-timeout 300
python3 tools/sim/d395_s1_bench.py --scenario b --phases c --out /rosy_d395_runs/b4 --localize-timeout 240
python3 tools/sim/d395_s1_bench.py --scenario a --phases c --out /rosy_d395_runs/t1 --localize-timeout 420 --loc-param scan_stride=2

# Windows: one block of rows per run
python tools/sim/d395_s1_summary.py X:\DevTemp\rosy-d395-s1\p7a1 ...
```

**What the driver starts and stops:**

- It launches gz_multi in its own process group:

  ```bash
  ros2 launch gz_sim gz_multi.launch.py robots:=<1|2> world_name:=map_v2_fleet.world mode:=nav \
    core:=true headless:=true loc_assist:=true seed_initialpose:=false api_port_base:=18930 \
    spawn_poses:=<x,y,yaw;...>
  ```

- It launches Fleet in its own process group: `fleet console --robots <robots.yaml> --port 18990 --localization-lane-rules .../map_v2_fleet/lane_rules.yaml`.
- On exit it stops only those two groups and any process still carrying its `GZ_PARTITION`.
- Each run is one long foreground `wsl.exe` call, because WSL stops the distro between calls.

## Not covered

- The `square` and `paint` cues (gz_multi has no camera), the overhead cue (off by design), 4 robots (S2), and real `lane_to_stopline` motion (it needs a camera).
- Motion before the pickup (finding 5).

## Re-run 2026-10-02

Same scenarios and pass bar as above, on branch `fix/d395-s1-rerun` from main cd2309ef. That main has rev. 6 and fixes F1 (the check uses AMCL's latest map→odom; peer objects come from the full scan), F2 (anchored peers, no −1 for an unseen peer, count-based monitor, `unsupported` is final) and F3 (CORE localization timers on the line clock). This branch adds the fix "no decision while a check or homing mission runs" (782014f5 robot, 0666dacc Fleet). Raw logs are in `X:\DevTemp\rosy-d395-s1b\<run>\`, plus `probe_d2.txt` (Nav2 vs final `cmd_vel` during the d2 drive).

**Verdict: S1 passed for (a), (b), (c) under rev. 6, and (l). (d) is not shown: the pickup was taken from an active drive goal, but the robot only turned in place and never travelled (finding R4).**

| Scenario | Runs | Result | Key numbers (sim s) |
|---|---|---|---|
| (a) square A + off-slot | a1–a3, plus d1–d3 power-on | **6/6 pass** | r1 (slot) LOCALIZED at 15.1–17.4. The off-slot robot (peers) took 49.6–53.6 (finding R2). Errors ≤ 1.1 cm / 2.1°. |
| (b) both on squares | b1–b3 | **3/3 pass** | LOCALIZED at 14.6–16.9, each on its **first** decision (first run: 19.7–21.8, always a second decision). Errors ≤ 0.5 cm / 0.8°. |
| (c) forced mirror | b1–b3 | **3/3 as rev. 6 expects**; lock not detected | The locked r2 lost its anchor every time. r1 was not dragged (end 0.3–0.4 cm). No mirror decision. |
| (d) pickup during a drive | d1–d3 (open start), a1–a3 (square A) | re-localization **6/6 pass**; drive motion **0/6** | Halt 6/6 (SUSPECT, 0.0 m drift). Set-down → LOCALIZED in 6.4–7.7 sim s, on the first decision, ≤ 1.5 cm / 0.2° (first run: 37–40 sim s, 2 rejects plus a rotation). |
| (l) lone off-slot, no cue | l1–l3 | **3/3 as expected** | `rotate_in_place` turned in place, `lane_to_stopline` aborted `lane_lost` (gz_multi has no camera, not counted), `needs_human` at 120 s, no decision. |

**Pass bar:**
- **Zero human input:** met in every run.
- **All LOCALIZED within 5 cm / 5°:** met in (a), (b) and (d) re-localization. The worst error was 1.5 cm / 2.1°.
- **Mirror decisions:** **0 of 31** Fleet decisions. All 31 were within the pass box of the truth when they were posted, judged by `d395_s1_summary.py` against the Gazebo trail.
- **Mirror locks made by the system:** none. The only lock is the injected (c) fault.

### Setup differences

- **Isolation:** `GZ_PARTITION=rosy_d395b`, `ROS_DOMAIN_ID=96`, workspace `/rosy_d395b_ws`, CORE APIs on 18960/18961, Fleet on 18996. The bench was driven by `X:\DevTemp\rosy-d395-s1b\run_series.sh`. No other session's process was touched.
- **(d) layout:** new bench scenario `d`.
  - r1 starts off-slot at (−0.70, 0.15, 180°) in the open middle, and r2 sits on square A at 90°.
  - The goal is (−0.70, −0.25, −90°), 0.40 m south. The drop is (−0.75, 0.30, 0°), 0.54 m from r2.
  - Runs a1–a3 used the old `a` goal from square A.
- **Host:** WSL 1-min load 15–36 during runs. Gazebo ran at RTF median 0.37–0.64 with two robots and 0.95–1.0 with one.

### (a) square A + off-slot

| run | load before / after power-on / after phase | RTF med | slot robot CANDIDATES → LOCALIZED | error | off-slot robot CANDIDATES → LOCALIZED | error | rejects | mirror |
|---|---|---|---|---|---|---|---|---|
| a1 | 30.3 / 25.7 / 31.4 | 0.46 | r1: 26 (10.6) → 35 (15.1) | 0.3 cm / 0.7° | r2: 27 (11.1) → 126 (53.6), peers | 0.3 cm / 0.3° | r2 1× `inject_rejected` (R3) | 0 |
| a2 | 29.4 / 29.2 / 27.2 | 0.64 | r1: 24 (12.0) → 34 (17.4) | 0.3 cm / 0.7° | r2: 25 (12.5) → 112 (53.0), peers | 0.3 cm / 0.4° | 0 | 0 |
| a3 | 27.2 / 22.9 / 31.5 | 0.40 | r1: 24 (11.9) → 35 (17.3) | 0.3 cm / 0.8° | r2: 25 (12.3) → 107 (51.0), peers | 0.3 cm / 2.1° | 0 | 0 |
| d1 | 15.9 / 23.0 / 29.2 | 0.38 | r2: 30 (10.7) → 42 (15.5) | 0.2 cm / 0.7° | r1: 29 (10.2) → 135 (51.2), peers | 0.6 cm / 0.2° | r1 1× `inject_rejected` (R3) | 0 |
| d2 | 27.1 / 30.9 / 33.0 | 0.37 | r2: 27 (10.5) → 41 (15.6) | 0.2 cm / 0.8° | r1: 27 (10.5) → 130 (49.6), peers | 1.1 cm / 0.3° | r1 1× `inject_rejected` (R3) | 0 |
| d3 | 33.0 / 31.5 / 34.7 | 0.42 | r2: 28 (11.4) → 40 (16.6) | 0.3 cm / 0.7° | r1: 26 (10.7) → 127 (50.8), peers | 1.1 cm / 0.4° | r1 1× `stale_request` (R5) | 0 |

Times are wall seconds since launch, with sim seconds in parentheses.

- The off-slot robot saw its peer in every report: a base_link object at (0.54, −0.35).
- It still waited for the ladder (finding R2): `rotate_in_place`, then `lane_to_stopline` (aborted, no camera), then a `peers` decision.
- No decision was posted while a mission ran, and none in the second after one. No robot ever rejected `mission_running`, because the Fleet gate held first.

### (b) both on squares

| run | load | RTF med | r1 CANDIDATES → LOCALIZED | r2 CANDIDATES → LOCALIZED | errors r1 / r2 | rejects | mirror |
|---|---|---|---|---|---|---|---|
| b1 | 2.0 / 11.0 / 28.5 | 0.43 | 25 (11.4) → 35 (16.5) | 26 (12.0) → 35 (16.9) | 0.4 cm 0.4° / 0.1 cm 0.8° | 0 | 0 |
| b2 | 19.5 / 22.8 / 29.4 | 0.49 | 26 (10.0) → 37 (14.6) | 28 (10.8) → 39 (15.7) | 0.5 cm 0.3° / 0.2 cm 0.8° | 0 | 0 |
| b3 | 28.3 / 25.5 / 32.9 | 0.44 | 26 (11.5) → 36 (16.3) | 27 (11.9) → 36 (16.3) | 0.3 cm 0.2° / 0.2 cm 0.6° | 0 | 0 |

F1 is confirmed. Every first `slot` decision passed its 3 s check: 6/6, against 0/15 in the first run. Power-on to LOCALIZED fell from 19.7–21.8 to 14.6–16.9 sim s.

### (c) forced mirror (b layout, r2's twin injected, then a pickup pulse on r1)

| run | r2 after the fault | anchor | detected | r1 after its pulse | end |
|---|---|---|---|---|---|
| b1 | LOCALIZED at the twin, 2.70 m / 179.9° | dropped ("pose jumped while LOCALIZED") | no | LOCALIZED 127 (64.1) by `slot`, 0.3 cm / 0.1° | r1 ok, r2 locked |
| b2 | same, 2.70 m / 179.7° | dropped | no | 131 (57.5), 0.4 cm / 0.0° | same |
| b3 | same, 2.70 m / 179.9° | dropped | no | 128 (60.3), 0.4 cm / 0.1° | same |

**Against the rev. 6 expectations:**
- The locked robot stops being an anchor (3/3).
- The peer is not dragged: r1's leader had `peers` 0 for both candidates and was decided by `slot` (3/3).
- Fleet sent no mirror decision (3/3).

**Detection.** r1's single report placed an object exactly at r2's true pose, base (2.11, −1.00), which is world (−1.25, 0.48). That is the mirror signature against r2's reported twin. The monitor needs 2 distinct reports, though, and r1 localized on that one report by `slot` before re-reporting. With both robots LOCALIZED again, nothing observes r2. This is the known rev. 4 limit, made shorter here by the faster `slot` path (finding R1).

### (d) pickup during a drive

| run | start | drive | SUSPECT | drift while held | set-down → LOCALIZED | r1 end | rejects after set-down |
|---|---|---|---|---|---|---|---|
| d1 | off-slot | goal 200; turned 180° → −90°, **0.00 m** | 241 (92.3) | 0.0 m | 248 (95.3) → 264 (102.2), peers | 0.3 cm / 0.1° | 0 |
| d2 | off-slot | same, to −88°, 0.00 m | 235 (89.2) | 0.0 m | 242 (92.2) → 260 (99.9) | 1.2 cm / 0.1° | 0 |
| d3 | off-slot | same, to −87°, 0.00 m | 232 (92.1) | 0.0 m | 239 (94.7) → 256 (102.4) | 1.5 cm / 0.1° | 0 |
| a1 | square A | goal 200, RPP "collision ahead", 0.00 m | 230 (96.4) | 0.0 m | 236 (99.2) → 250 (105.6) | 1.5 cm / 0.2° | 0 |
| a2 | square A | same | 215 (102.5) | 0.0 m | 221 (105.5) → 234 (112.5) | 1.2 cm / 0.2° | 0 |
| a3 | square A | same | 212 (97.9) | 0.0 m | 218 (100.6) → 234 (107.9) | 1.2 cm / 0.2° (from the truth trail; `gz model` timed out at the verdict) | 0 |

- `safety/pickup` true and false were published in every run (`ros_pub ... "ok": true`).
- Re-localization after set-down now takes **one** decision, 6.4–7.7 sim s (first run: two rejects of the same pose, then a 360° rotation, 37–40 sim s).
- In d1–d3 the ladder started `rotate_in_place` while that decision's 3 s check was running. It ended `localized` after 1.6–1.7 s (finding R6).

### (l) lone off-slot

| run | RTF med | load | ladder | end |
|---|---|---|---|---|
| l1 | 0.95 | 32.2 / 18.4 | `rotate_in_place` 33 → 67 done; `to_square` refused once; `lane_to_stopline` aborted `lane_lost` | `needs_human` at 120 s, CANDIDATES, 0 decisions |
| l2 | 1.00 | 17.2 / 20.0 | same | same |
| l3 | 1.00 | 18.4 / 18.7 | same | same |

`to_square` was refused exactly once per run, in all 9 runs with a ladder. The first run had 13–20 refusals per run, so F2 is confirmed. `lane_to_stopline` cannot work in gz_multi (no camera) and is not counted against (l).

### Findings (re-run)

- **R1. The mirror lock in (c) is still undetected.**
  - The observer's mirror evidence (1 report) is below the monitor's 2-report threshold whenever the observer localizes on its first decision. Since F1, that is the normal case.
  - Rev. 6's safety properties hold: no spread, no mirror decision, anchor dropped. The remaining gap is the rev. 4 follow-up, LOCALIZED-to-LOCALIZED observations.
  - Cheap partial step: let a LOCALIZED anchor's scan objects count as observations. The robot reports objects only in CANDIDATES today.
- **R2. A peers-only robot waits for the ladder at low RTF.**
  - The ladder's 10 s rung is Fleet wall time, which is about 3.5 sim s at RTF 0.35. The peer becomes an anchor only at 15–17 sim s.
  - So `rotate_in_place` starts just before the arbiter's 2 s hold completes. When the rotate ends, the busy-retried homing rung starts `lane_to_stopline` at once, and the quiet window delays the decision again.
  - Cost: LOCALIZED at 49.6–53.6 instead of about 20 sim s. Accuracy is unaffected.
  - Proposal: run the ladder on sim time under `use_sim_time`, and hold the next rung while the robot has a fresh report with a carried lead.
- **R3. Candidate yaw resolution.**
  - The 3 rejected decisions after a rotation picked a candidate 2–3° off: yaw 180.0° or 179.0° against truth −177.2° to −178°. Each fit about 0.956, and the check rightly failed them.
  - The next search gave −177.0° or −178.0° and passed.
  - This is the global search's angular step, not timing. Proposal: refine the leading candidate's yaw (±3°, 0.5° steps) before reporting.
- **R4. Nav2 in gz_multi never translates in these layouts.**
  - From a square, RPP reports "collision ahead" (wall 0.13–0.14 m, padded footprint).
  - From the open start, `probe_d2.txt` shows `nav_cmd_vel` with linear 0.000 throughout, while angular swings between −0.33 and +0.31 rad/s. RPP stays in rotate-to-heading (`rotate_to_heading_min_angle` 0.35) and never hands over to tracking, and the progress checker aborts ("Failed to make progress").
  - CORE did not hold the output.
  - So (d) is shown only from an active goal with in-place rotation. A sim Nav2 tuning lane must fix the drive before (d) can be called a moving pickup.
  - **Root cause (fix/gz-multi-nav2-forward, 2026-10-02).** There are two causes, and both are in the sim-only `gz_multi._nav_config`, not in `nav2_params.yaml`.
    1. **Rotation only.** Jazzy RPP (1.3.12) rotates to the goal heading with linear 0 whenever its carrot is nearer than the goal checker's `xy_goal_tolerance` (0.25). The sim trial sets `min_lookahead_dist` to 0.15, and the carrot sits about one lookahead ahead, so every goal was "near the goal" from the start. The device values (0.3 > 0.25) do not have this problem. Fix: in sim, `xy_goal_tolerance = min(·, 0.10)`.
    2. **"collision ahead" from a square.** The padded circumscribed radius (0.115 m) went into the local costmap too, which is RPP's collision checker. On 5 cm cells it overlapped the wall 0.14 m from square A. Fix: only the planner's global costmap takes the radius. The local costmap keeps the device footprint.
  - **Evidence.** WSL Jazzy, one robot, `core:=false` with a relay standing in for CORE, GZ_PARTITION rosy_g4, ROS_DOMAIN_ID 97. Raw data is in `X:\DevTemp\rosy-g4\<run>\`.
    - Before the fix, from the open middle: `cmd_vel_nav` had linear 0 in all 1043 samples, the robot moved 0.001 m, and the run ended in "Failed to make progress". The scan had no return under 0.15 m and the costmap around the robot was clean, which rules out self-hits and the peer.
    - With fix 1 only, from square A: 0.013 m and "collision ahead".
    - With both fixes, every run below reached the goal. Nav2 SUCCEEDED in all four, and the end poses are Gazebo truth:

      | Start | Goal | Run | Travel | End (truth) |
      |---|---|---|---|---|
      | Open middle | 1 m | `mid1m_r1` | 0.93 m | 7 cm from goal |
      | Open middle | 1 m | `mid1m_r2` | 0.91 m | 9 cm from goal |
      | Square A | 0.44 m | `fix2_sqA_r2` | 0.28 m | — |
      | Square A | 0.44 m | `sqA_r3` | 0.26 m | — |
      | Square A | 0.44 m | `sqA_r4` | 0.30 m | — |

      A fourth square A run, `fix2_sqA_r1`, drove off and then aborted on a replan with "Start occupied" in the global costmap.
  - **Open points (not fixed here).**
    - AMCL, seeded at square A without loc_assist, sits 7–8 cm off the truth before the robot moves. So square A runs end 14–18 cm short in truth while Nav2 reports SUCCEEDED. The bench localizes with loc_assist instead.
    - The global padded radius can still report "Start occupied" near a wall (1/4 runs). This is `fix2_sqA_r1` above.
- **R5. CORE keeps serving a dropped report.**
  - After a mission start, the robot drops its open request id, so the status says CANDIDATES with `request_id: null`. `LocalizationAssist.candidates()` still returns the cached pre-mission report.
  - Fleet decided once on it after the quiet second (d3) and got `stale_request`. This is harmless, since the robot refuses it, but it costs one Fleet hold.
  - Proposal: CORE returns no report while the status has no request id.
- **R6. The ladder may start a mission during a running 3 s check.**
  - Fleet records the pending decision, but the ladder does not consult it.
  - Here the rotation lasted under 2 s and ended `localized`. A longer one could fail a correct check.
  - Proposal: no ladder mission while a Fleet decision is pending.
- **R7. Bench.**
  - The b3 bench finished in 540 s, but the series step took 74 min wall. The gap came after `stopped`, during save or copy, or because WSL stalled. The results are unaffected.

**Defaults:** none changed. Every `slot` decision chose the truth, and `peers` decided only from anchors.

### Commands (re-run)

```bash
# WSL workspace and build
tar -cf - src tools | wsl -d Ubuntu -- bash -c 'mkdir -p /rosy_d395b_ws && cd /rosy_d395b_ws && tar -xf -'
cd /rosy_d395b_ws && source /opt/ros/jazzy/setup.bash
colcon build --symlink-install --packages-up-to gz_sim core control fleet navigation description
# the series; run_series.sh calls d395_s1_bench.py with --partition rosy_d395b --domain 96
# --api-port 18960 --fleet-port 18996 --localize-timeout 420 --drive-timeout 90
bash /mnt/x/DevTemp/rosy-d395-s1b/run_series.sh b1:b:c b2:b:c b3:b:c a1:a:d a2:a:d a3:a:d l1:l: l2:l: l3:l: d1:d:d d2:d:d d3:d:d
# Windows: rows, including the Fleet decisions judged against the truth trail
python tools/sim/d395_s1_summary.py X:\DevTemp\rosy-d395-s1b\b1 ...
```
