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
