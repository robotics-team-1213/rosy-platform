# OMX release corrector: IK demonstrations → BC → RL (simulation)

**Status (2026-10-30):** BC v0 beats IK when the held-box pose is only an estimate. The RL environment is still being
debugged and has produced no learned improvement yet. This is simulation only (Isaac SDK 6.2.0.0, seed 42, nominal
gapped 3×3×3 geometry of D-929). It is not hardware or field acceptance.

## What the model does

The model replaces only the IK `packing_target` command in release-feedback iterations after the first descent.

- **Input:** 22 state features, no images. These are the held-box pose (as a 2–5 mm estimate), the measured TCP, the
  centre-row face estimate, the target cell and the iteration.
- **Output:** a TCP correction, clipped to 5 mm per axis.
- **Unchanged gates:** clearance, footprint, prior-stack and settle checks run on the measured pose.
- Code: `learning/envs/isaac/release_corrector.py`. Model: `learning/envs/isaac/models/release-corrector-bc-v0.npz`,
  sha256 `85713c8ec54190e53729d6df73d5d59f3e6e7d715058bfb7698b3793042b9294`.

## BC v0

- **Data:** 18 distinct recorded releases and their 72 pre-command snapshots from the gap-v1 reports.
  - The simulation is deterministic per seed, so repeated runs repeat releases. They are counted once.
  - Each snapshot is perturbed within observed ranges (±3 mm shift, ±1 mm slip, ±0.02 rad yaw).
  - The pure IK teacher is recomputed on the true poses, and a 2–5 mm held-box estimate error is added.
- **Model:** a least-squares map plus a residual tanh network.
  - A plain MLP underfit: 1.57 mm, against 0.33 mm for ridge regression.
  - Holdout: each release's last snapshot.
- **Holdout result:** mean absolute error 0.44 mm, against an 8.98 mm mean baseline.
- **Clip:** on a synthetic hold outside the data the model extrapolated about 25 cm. The 5 mm per-axis clip bounds
  any such step.

## Isaac comparison under a 2–5 mm held-box estimate

| Run | Condition | Result |
|---|---|---|
| `74cd7b88d92457fda5ed23c9873f718d` | IK + estimate, 50 µm convergence check | FAILED, 0/9. Final TCP 2.29 mm from the true-pose target. |
| `1196fae28c715ac4ae4361659ba91f93` | BC v0 + estimate, 50 µm convergence check | FAILED, 0/9. Final TCP 1.03 mm from the true-pose target. |
| `b0ccbc4fa2ff5646a7fdec3cf475a73d` | IK + estimate, 1.5 mm convergence (`982242f7f1`) | FAILED, **0/9**. Opening blocked at the first box. |
| `ebdd41d368ee541da43c8400360f5c24` | BC v0 + estimate, 1.5 mm convergence | FAILED, **8/9**. Gaps 3.02–4.20 mm. |

The 50 µm convergence check assumes true-pose feedback, so the estimate cases use the 1.5 mm final position tolerance
instead. Nominal keeps 50 µm.

In ebdd, box 7 was −0.08 mm from its target in x just before opening and landed +1.05 mm off. That is 0.1 mm past the
1 mm envelope tolerance. Other boxes moved 0.1–0.4 mm while the gripper opened. This release drift is not a command
error, so imitation cannot remove it; it needs learning from outcomes.

## RL attempts

The RL setup explores around BC with a pinned linear residual and Gaussian noise. `rl-update` applies REINFORCE
between runs. The reward is settled position error, plus 3× the distance outside the gap band, minus 10 if the box is
unstable. A release that never settles gets −20.

| Run | Setup | Result |
|---|---|---|
| `3d52109dacbe5132b2a5328f62d095b7` | Nine-container flow, 0.5 mm noise | Blocked at the first release; no data. Noise lowered to 0.2 mm. |
| `d63edea3d6cf540a9d70a0f43fbc902b` | Nine-container flow, 0.2 mm noise | 1/9 placed, 6 decisions, mean reward −10.5. Too few decisions per 30-minute run. |
| `8e96d62e6c315a0cba14acad00e66f27` | Short episodes (`release_episodes.py`) | Crashed after 3 episodes: `move()` wrote to an undefined trial. Fixed. |
| `e48ad54e227352d8b86623b277d6e93d` | Short episodes | 40/40 failed, 0 settled. Held box started at yaw 0, while the BC data is at yaw π after leveling. Release error 20–26 mm; tracking losses 11; prior stack did not hold 12. Start yaw fixed in `7d4d028071`. |

| `a3b1e094a6bd582d81b00ff8fb0f4382` | Short episodes | Crashed after one episode: a diagnostic sample shadowed the wall-clock origin. Fixed in commit `5ad9fd9b42`. |
| `29b768d927225c6cbb4fd92332d3f15e` | Short episodes | 37 episodes, 8 settled and stable (0.59–1.19 mm). Every arm-1 centre-row episode ended 18–27 mm off: the BC data holds arm-1 boxes at quaternion (0,0,0,−1) and the episodes started at +1. Prior jitter of ±1 mm / ±0.01 rad broke the envelope (12 prior failures). Both fixed in commit `44d0f7ef7b`. |
| `991a5a7a4321561ba33709dbd0f24a2e` | Short episodes | Refused at admission: another job took the GPU between check and start. `run` now retries from the check (commit `4d1f24b1a7`). |
| `1f81cfd4c3395478ab03f15c803b7fa3` | Short episodes, rl0 (BC + zero residual, 0.2 mm noise) | **20 episodes, 16 settled and stable (80%)**, position error 0.24–1.07 mm (median ≈0.55 mm). 2 opening blocked, 2 settle windows not reached. |

The first REINFORCE step on 135 decisions (runs 29b7 and 1f81, mean reward −9.7) gave residual rl1, pinned as
`release-episodes-rl1` (sha256 `cf84c0a0d2a878eb072b37b2f2428a315e54899887db583314fbe878739036ed`, commit `259df0b57b`).
Its episode run uses seed 43, so episode layouts differ from rl0. With 20 episodes per run, small differences in
success rate are not distinguishable from chance; several iterations are needed before claiming an improvement.

| Run | Setup | Result |
|---|---|---|
| `9968d1b9` | Short episodes, rl1, seed 43 | **0/32 settled**; 31 opening blocked. The unbounded REINFORCE step moved the residual output by up to 2.76 mm, past the 1.5 mm convergence check. |

rl1 is kept pinned as a failed step, not used further. `Residual.update` now scales each step so the residual output
changes by at most 0.2 mm on the update data (trust region), with learning rate 2e-5. The same data from rl0 gave
residual rl2 (`release-episodes-rl2`, sha256 `bb424ece0730ab37b16a8e5dcc43febfeb45070fcd5e3f255eb36680f070c935`,
commit `f157285389`, largest output change 0.197 mm). Its episode run uses seed 42, the same layouts as rl0 run 1f81,
so the two runs can be compared episode by episode.

| Run | Setup | Result |
|---|---|---|
| `36f78c79402e5d7f93a907b511b53545` | Short episodes, rl2, seed 42 | 21 episodes, **15 settled and stable**, median position error 0.60 mm. |

Against rl0 run 1f81 on the same 20 layouts: 12 settled in both, and rl2 was closer to the target in only 4 of them
(mean +0.18 mm worse). rl0 alone settled 4 layouts, rl2 alone 2. rl2 is not an improvement. One REINFORCE step on
about 135 noisy decisions does not carry enough signal; BC v0 with a zero residual stays the reference.

More rl0 data before the next update:

| Run | Setup | Result |
|---|---|---|
| `65e5fb1d70395a2d857f5cd04c861b43` | Short episodes, rl0, seed 44 | 22 episodes, **16 settled and stable**, position error 0.24–1.11 mm (median 0.50 mm). 4 opening blocked, 2 settle windows not reached. 66 decisions. |

rl0 settles about 75–80% of episodes across seeds 42 and 44.

| Run | Setup | Result |
|---|---|---|
| `b31ed89c5f625916930d04462b1cfff9` | Short episodes, rl0, seed 45 | 20 episodes, **19 settled and stable**, median position error 0.65 mm. 1 opening blocked. |
| `dbf5fd6bc6a25a6ca01839ef2578bf19` | Short episodes, rl3, seed 44 | 22 episodes, **19 settled and stable**, median position error 0.48 mm. |

rl3 is one trust-region REINFORCE step from rl0 on all 261 decisions of runs 29b7, 1f81, 65e5 and b31e
(`release-episodes-rl3`, sha256 `cde882834ab9f110d954c990eae4795446851924dcbe1a88822560358577febc`, commit
`d2465280d7`). On the same 22 layouts as rl0 run 65e5: rl3 settled 3 layouts that rl0 did not, and lost none; where
both settled (16), position error was about the same (rl3 closer in 7, mean −0.06 mm). Three discordant layouts out of
22 are not yet distinguishable from chance (two-sided sign test p = 0.25). A paired run on seed 42 is the next check.

| Run | Setup | Result |
|---|---|---|
| `99941e72624956f5928f4672ea658312` | Short episodes, rl3, seed 42 | 23 episodes, **19 settled and stable**, median position error 0.59 mm. |

On the 20 layouts shared with rl0 run 1f81: rl3 alone settled 2, rl0 alone 1; where both settled (15), rl3 was closer
in 6 (mean +0.05 mm). Over both seeds rl3 settled 5 layouts that rl0 did not and lost 1 (sign test p = 0.22), with
the same position error. rl3 does not make releases worse and may settle a few more, but the gain is not established.
BC v0 with a zero residual remains the reference; rl3 is a candidate.

| Run | Setup | Result |
|---|---|---|
| `71833be57ef150e98506ea5f2e4f7afa` | Short episodes, rl3, seed 45 | 22 episodes, **20 settled and stable**, median position error 0.63 mm. |

On the 20 layouts shared with rl0 run b31e (19/20): each settled one layout the other did not; where both settled (18),
rl3 was closer in 9 (mean +0.04 mm). Over seeds 42, 44 and 45: rl3 alone 6, rl0 alone 2 (sign test p = 0.29), and the
same position error. Still not established.

| Run | Setup | Result |
|---|---|---|
| `1cb11cf3625a58408fb1e163377d2dee` | Short episodes, rl0, seed 46 | 21 episodes, **16 settled and stable**, median position error 0.59 mm. |
| `a509456b33dd575f8fa8ec7c1e6dd30a` | Short episodes, rl3, seed 46 | 20 episodes, **17 settled and stable**, median position error 0.69 mm. |

On the 20 shared layouts: rl3 alone 2, rl0 alone 1; where both settled (15), the same error (mean −0.003 mm).

**Four seeds (42, 44, 45, 46), 82 paired layouts:** rl3 settled 8 layouts that rl0 did not and lost 3 (two-sided sign
test p = 0.23). Where both settled, position error is the same. rl3 is no worse than rl0 and may settle a few more,
but one REINFORCE step does not give an established gain at this sample size. rl0 stays the reference and rl3 a
candidate. Two seed-46 starts failed on a transient model-PC connection error and were rerun; they are not counted.

## Nine-container flow with rl3

Case `nominal-bc-v0-rl3` runs the accepted nine-container flow with BC v0 plus the rl3 residual and no exploration,
under the same 2–5 mm held-box estimate (commit `2d63c2518a`, seed 42). BC v0 was rerun on the same commit.

| Run | Condition | Result |
|---|---|---|
| `b872ef38379f5a769351a2ee143c0b18` | BC v0 + rl3 | **SUCCEEDED, 9/9.** Row gaps 3.42–4.43 mm, no unstable box. |
| `7f51cec419c75d1080ba866ee5a869e6` | BC v0 | FAILED, 8/9. Box 7 did not settle within ten seconds, as in run ebdd. |

On this seed rl3 removes the one failure BC v0 had. It is one seed of a deterministic simulation; seed 43 is next.

| Run | Condition | Result |
|---|---|---|
| `d37dbf0849905a1e94ad407f4f52200e` | BC v0, seed 43 | FAILED, 2/9. Box 1 did not settle; first row gap 5.44 mm, outside the 2–5 mm band. |
| `f3eb4b1d19565533aecad14a568166af` | BC v0 + rl3, seed 43 | Stopped by the run supervisor after six placements: a plan-request file being deleted was read as unsafe output. Not a task result. Fixed in `run_worker.py` (see `docs/solutions/runtime-errors/isaac-run-supervisor-flagged-a-file-being-deleted-2026-10-31.md`). |
| `103846424e4b5571888b0f68bf49d936` | BC v0 + rl3, seed 43 (fixed supervisor) | **SUCCEEDED, 9/9.** Row gaps 2.65–4.82 mm, no unstable box. |

**Two seeds:** BC v0 + rl3 placed all nine containers on both seeds; BC v0 alone placed 8 and 2. In the short
episodes rl3 was only a candidate (p = 0.23); in the nine-container flow it is the better model on both seeds tried.
This is still simulation under an assumed 2–5 mm estimate error, not hardware acceptance.

### Why BC v0 failed seed 43

Read from the two seed-43 stack reports (d37d, 1038). The task stops at the first failed placement, so "2/9" means
the run ended at box 1; boxes 2–8 were not tried. Box 1 was perfectly still (100/100 samples failed the window with
zero velocity); it failed only because the row gap was 5.45 mm against the 2–5 mm band. Target y for box 1 is
−33.5 mm (3.5 mm gap).

| Box 1, y in mm | BC v0 (d37d) | BC v0 + rl3 (1038) |
|---|---|---|
| Box 0 after opening (shared start, same layout) | +0.47 | +0.50 |
| Held box after each release iteration | −37.31, −34.74, **−33.83**, −34.40 | −34.95, −34.17, −34.21, −34.25 |
| Box 1 after opening (14.6 mm fall) | −34.98 (moved −0.58) | −34.34 (moved −0.09) |
| Row gap | **5.45** | 4.84 |

Box 0 started both runs 0.5 mm off toward +y, leaving about 1 mm of the band's upper margin. BC v0 reached −33.83
on its third iteration, then its fourth correction moved the box 0.57 mm away from the target, and the box slid
another 0.58 mm when the gripper opened. Either alone would have stayed inside the band. With rl3 the held box
stayed within 0.1 mm over the last three iterations and moved 0.09 mm on opening. One case: it shows the mechanism
on this seed, not that rl3 always reduces drift on opening.

### Seeds 44 and 45 (commit `fa58721ca6`)

| Seed | BC v0 | BC v0 + rl3 |
|---|---|---|
| 44 | `54de45f4ab8658c2978a20db51d2c905` FAILED, 8 placed. Boxes 1, 4, 7 outside the window; first row gap 1.59 mm, below the band. | `c0b16e337f865e55867d267e1c2d54f0` FAILED, 5 placed. Box 4 ended 1.08 mm from its target in y; row gaps 3.85–4.60 mm. |
| 45 | `ffb064aa26f2558eaec45a76dc50f246` FAILED, 1 placed. Box 0 jumped from +1.17 to +8.58 mm in y when the gripper opened. | `8ae2bf099abd5f1596a8accd73552b28` FAILED, 2 placed. Row gap 5.70 mm: box 0 at +1.01, box 1's last correction moved it 0.42 mm away, then 0.27 mm more on opening. |

**Four seeds, placements out of nine:**

| Seed | 42 | 43 | 44 | 45 | Complete |
|---|---|---|---|---|---|
| BC v0 | 8 | 2 | 8 | 1 | 0/4 |
| BC v0 + rl3 | 9 | 9 | 5 | 2 | 2/4 |

This replaces the two-seed reading above: rl3 is not reliably better in the full flow. It completed two of four
seeds and BC v0 none, but BC v0 placed more on seed 44. Neither model passes the nine-container flow under the
2–5 mm estimate.

The failures share a pattern. The last release iteration of both models still moves the held box by 0.4–0.6 mm in y
(seeds 43 BC, 45 rl3), box 0 often ends 0.5–1 mm toward +y, and the box moves again on opening. Together these use
the 1.5 mm margin between the 3.5 mm nominal gap and either edge of the band. Seed 45 BC also shows a 7.4 mm jump on
opening, far beyond the 0.1–0.4 mm (max 1.05 mm) seen before; the release measurement session should measure this
drift on the real arm before more RL on the residual.

### Why box 0 jumped 7.4 mm on seed 45 (run ffb0)

The opening samples of ffb0 and 8ae2 (same seed, same layout) show the same opening up to landing. The fingers
release by raising the command toward the measured finger angle; the box loses grip near command 0.417 rad, with
the fingers still at 0.427. It then falls the 15 mm release clearance (`release_clearance_m`), reaching about
220 mm/s. In both runs the box tilted 0.5–1.1° before it landed.

| Box 0 | ffb0 (BC v0) | 8ae2 (BC v0 + rl3) |
|---|---|---|
| y before falling | +0.92 mm | +0.55 mm |
| Velocity after landing | 175 mm/s in +y | 0 |
| y after landing | +8.58 mm | +1.01 mm |

So the jump is the landing, not the correction: in ffb0 the impact turned the vertical speed into a slide along the
plate. A 14 mm drop onto a hard surface makes this sensitive to small tilt differences, and either model can hit it.
Next check: the same BC v0 flow with an 8 mm clearance (case `nominal-bc-v0-release8`), seeds 42–45. The clearance
was lowered from 35 mm to 15 mm on 2026-10-29 (`docs/validation/omx-cube-stacking-2026-10-29/result.md`); lower values
were not tried.

#### 8 mm release clearance with BC v0 (commit `a66fc77016`)

| Seed | Run | Result |
|---|---|---|
| 42 | `fdb92f74efc55260ade38702d5800bd1` | FAILED, 0 placed: release correction did not converge, opening blocked. |
| 43 | `10b911260a8b5e2397eb25ba3e950d6e` | Same. |
| 44 | `47c471329f965190abb0fdc5eb51afc4` | Same. |
| 45 | `82b197e3cc195ed092a01c1f596b78ae` | No result: the run unit went inactive at SDK import. Not a task outcome; not rerun. |

On seed 42 the first command put the held box at z 96.9 mm, about the 8 mm target. BC v0's next corrections raised it
to 101.4, 103.4 and 103.6 mm, the 15 mm height of its training demonstrations, so the 1.5 mm convergence check never
passed. BC v0, and rl3 on top of it, learned the release height along with the lateral correction. A lower release
cannot be evaluated with these models; it needs IK demonstrations and BC training at the new clearance. The landing
slide hypothesis is therefore untested.

## Current cell versus the simulated scene (2026-10-31 21:03)

Checked on the ceiling camera (Fleet source `ceiling_north`), the side camera and both wrist cameras after the site PC
was rewired from the single-arm S cell back to the two-arm A/B cell. Every result above used the CAD scene in
`container_fixture`; these differences are not in it:

- **Placing surface.** The real stack sits on a navy pentagon pallet with raised white studs on a grid. The simulated
  stack sits on a flat plate. The landing slide (seed 45) and the opening drift both depend on what the box lands on,
  so the drift numbers above are flat-plate numbers.
- **Top camera.** The 2–5 mm estimate error stood for the old Jieli top camera. The top camera is now a RealSense D435
  that serves no frame until its branch lands, and it has to be calibrated again before the estimate error can be
  measured.
- **New views.** A side camera faces the pallet and each arm has a wrist camera. The side view can record the fall
  and landing; a wrist view is a candidate close-range estimate before release.
- **Arm names.** arm_a is now the right follower and arm_b the left. Simulated arm indices are not yet mapped to them.

Until the pallet is measured (outline, stud diameter, height and pitch) and added to the scene, more RL or release
height work on the flat plate would tune for a surface the cell no longer has. The measurement session plan
(`Rosy/docs/superpowers/plans/2026-10-31-omx-release-measurement-session.md`, section 6) now includes these.

## Finger inside a 6 mm row gap, 3 mm release (2026-11-01, commit `45da34bf98`)

Nominal IK with the true pose (no estimate error, no learned model). Two cases in `release_cases.FIXTURE_OVERRIDES`:
`nominal-release3` lowers only the stack release to 3 mm above the target (the leveling set-down keeps 15 mm; lowering
it too stopped all eight first runs at leveling, commit `18f9bb98a4`, runs not counted). `nominal-gap6-release3` also
widens the target row gap to 6 mm (band 4.5–7.5 mm) and lets the neighbour-side finger go down into the gap when the
gap is at least 5 mm (`finger_fits_gap`). Otherwise the finger still has to clear the neighbour top by 2 mm.

**Finger model.** The simulated pads are 3 mm capsules with a 1 mm rest offset on each side, so a pad needs 5 mm of
gap. The real new fingers were estimated at about 3 mm from the side camera. The jaw v2.1 CAD finger plate is
1.1–2.0 mm thick, so this is a conservative proxy: the real finger has more room than the simulated one. The finger
links themselves have no collision in this scene (pads only), and the containers weigh 60 g here against 16 g for the
real 3-cell container.

| Seed | 6 mm gap, finger in gap | 3.5 mm gap (finger cannot enter) |
|---|---|---|
| 42 | `1310913662965131b9dcb563a47007e6` **9/9**, gaps 4.65–6.91 mm | `6b98cae0e603553e87c9ab5f8dde2ad6` 3 placed. Box 2 slid 4.2 mm on opening; gap −0.27 mm (touching) |
| 43 | `cb157b50463f515d9de14ba68c178c37` **9/9**, gaps 4.99–5.93 mm | No result: the remote run failed to start (`Isaac operation failed`); not rerun |
| 44 | `bb5e2d3c29c755b5b08189a97f88fe78` 1 placed: the leveling set-down for box 1 did not converge, before any stack release of that box | `bc06c410f56953309dbdc205bf56510b` 5 placed. Box 4 ended 0.92 mm off |
| 45 | `8279afde212a578f8bf4f18c5b2f204f` **9/9**, gaps 4.92–6.15 mm | `9997689b92c054ec8d5cca6902af833e` 8 placed. Box 7 ended 1.14 mm off |

- **Release height.** With the 6 mm gap every box was released 3.0 mm above its target. With 3.5 mm the outer rows
  still had to stay 13.6 mm up to keep the finger over the neighbour; only the centre rows dropped from 3 mm.
- **Drift on opening.** With the finger in the gap the released box moved 0.1–0.6 mm on opening. With 3.5 mm the
  13.6 mm drops moved it up to 4.2 mm (seed 42, box 2).
- **Contact with the neighbour (new).** With the finger in the gap, opening the gripper pushed the neighbouring centre
  box sideways: 0.7–0.8 mm on the first layer and 2.0–2.5 mm (with 0.4–0.8 mm lift) on layers 2 and 3. The pad swings
  outward as the jaw opens and meets the neighbour. Placing the opposite outer row pushed it back, so the final gaps
  stayed in the band. That is symmetry, not control, and a real finger catching the neighbour would also do this.
  Ways to remove it: open the jaw less on release, or lift slightly while opening.

So with the finger allowed into a 6 mm gap the nominal flow places all nine on three of four seeds, and the release
drop and drift mostly disappear. The remaining risk is the opening finger pushing the neighbour. This is true-pose IK
in simulation, not the learned models and not hardware.
