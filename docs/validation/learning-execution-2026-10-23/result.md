# OMX training support and SIM teacher verification

2026-10-23 KST. Worktree `.worktrees/learning-execution`, branch `fix/omx-learning-execution`, base `95d60b4490`. This is an in-progress verification record, not full learning-pipeline or physical-device acceptance.

## Corrected behavior

The bounded ACT trainer now checks all four original future targets against the same original source and the 0.035rad head bound. Original labels and chronology remain intact; missing command coverage is rejected. Bounded synthetic state noise is limited to the feasible source interval and its distribution is recorded in augmentation metadata.

The SIM teacher uses 0.03rad planned/intermediate steps and contact squeeze, with final readback targets within 0.035rad. Grasp closure stops only after the existing contact range, arm target tolerance and fresh held-object receipt are satisfied. Owner command authority, the 0.04rad final admission fence, controller tolerances, object judge and cleanup checks were not relaxed.

## Evidence by revision

All paths below are relative to the external log root `C:/DevTemp/learning-execution-20261023/`. Test results apply to the named source, not to later revisions by implication.

| Source | Verification | Observed result |
|---|---|---|
| `95d60b4490` | `baseline/run-1.txt` | 56 passed, 1 skipped; zero new failures |
| `db63fe7c9b` | `red/run-1.txt` | 7 expected regression failures, 31 passed |
| `04a79d3906` | `green/run-1.txt` | 38 passed |
| `04a79d3906` | `affected/run-1.txt` | 470 passed, 16 skipped, 37 warnings; zero new failures |
| `99a4014c14` | `teacher-red/run-1.txt` | 3 expected teacher-margin failures, 36 passed |
| `f6e88c0bf5` | `teacher-green/run-1.txt` | 77 passed |
| `f6e88c0bf5` | `final-affected/run-1.txt` | 573 passed, 16 skipped, 37 warnings |
| `f6e88c0bf5` | `native-red-with-tools/run.txt` | Actual LeRobot integration: 3 failed, 3 passed; incompatible test fixtures exposed |
| `a3f295e4dd` | `native-green/run.txt` | Actual LeRobot integration: 6 passed; test-tool dependency mismatches observed, superseded by pinned rerun |
| `3e21bb5e5c` | `contact-red/run-1.txt` | 5 expected contact failures, 39 passed |
| `bff46a3f28` | `contact-green/run-1.txt` | 82 passed; zero new failures |
| `bff46a3f28` | `native-green-pinned/run.txt` | Scoped test tools, `pip check` reports no broken requirements; 6 actual integration cases passed without skips |

Native test tools live only in that remote run's separate output directory; the existing model venv was not modified. The final native run still emits NumPy/datasets and torchvision video deprecation warnings. Generic remote pytest skips optional native dependencies; it is not substituted for the actual model-PC run.

The first `native-red/` command exited zero without running pytest because nested shell arguments were not preserved by the runner's command joining. `native-red-actual/` then lacked pytest. Neither is accepted as test evidence.

## Original-data audit and closed-loop limits

The actual selected cohort had 12,444 train examples. At least one future original target exceeded the head support in 3,843 chunks; per-joint counts were 302, 193, 486, 488, 0 and 2,835. A separately seeded NumPy Gaussian-noise probe produced 5,785 unsupported chunks. That probe is not a replay of the optimizer's Torch RNG.

The corrected sampler rejects all 25 original episodes while retaining the requirement to represent every command. In the first episode, 31 of 311 commands have no supported frame. No originals or human labels were changed. Existing offline model results remain preserved; no new accepted policy is claimed.

## Actual isolated SIM teacher

One episode from commit `f6e88c0bf5` ran under the existing approved native simulation helper. Its run suffix `7d0f84ac0395` ended EXITED/1, HOLD, zero successes, cleanup true. It recorded 1,292 frames and 267 commands before `bounded_readback_step_no_progress` during grasp. Physical contact blocked the fixed close target. Evidence is retained under `teacher-probe/`, and that failed episode is excluded from learning.

The contact-gate correction is commit `bff46a3f28`. Its run suffix `4cda0062f7d5`, retained under `teacher-contact-probe/`, ended EXITED/1, HOLD, cleanup true. It passed the contact-limited grasp and transfer but reached the recorder's 3,000-frame limit during release. This failed episode is excluded from learning. Matching the teacher's longer trajectory to the recording budget remains unresolved; neither the frame cap nor acceptance checks were relaxed.

Independent code review found the native fixture issue, which was reproduced and fixed. Follow-up review through `bff46a3f28` reported no remaining Important findings. Review does not establish runtime success.

## Remaining acceptance

Fetch and independently validate the new teacher's source, task truth, every exported frame and bounded command coverage before collecting 25 episodes. Then train/reload/evaluate a new fixed policy and measure fresh independent object trials. Hub synchronization, approved installation/lease execution, failure feedback, two-arm learning and driving acceptance remain separate unfinished parts of the user goal. No GitHub push or physical movement was performed.

## Local landing and recording-budget follow-up

The source fixes and verification record landed on local main at commit `d54c33a8da`. The landing gate ran lint, safety and size checks, 273 architecture/guard cases and 500 affected cases with six optional-dependency skips and zero new failures. The first landing attempt stopped on two documentation revision strings flagged by the secret scanner; separating source revisions and run suffixes fixed the document without weakening the scanner.

The next slice, `fix/omx-teacher-recording-budget`, selects 5fps for the teacher from the unchanged 10Hz camera. It preserves original timestamps, paired state/actions and every command event, while keeping the existing 3,000-frame cap. Default Pilot capture remains 10fps. Selected-stream gaps and clock reversals remain rejected.

At commit `35856eee61`, eight new regressions failed before implementation. At commit `a3a75e6fd2`, all 66 capture/teacher cases passed, with zero new failures. Independent read-only review found no Important findings in that slice. A one-episode native run from that exact source, suffix `3a2891da44b8`, is retained under `teacher-sampled-probe/`; completion and training eligibility are pending.

The same run subsequently exited zero with PASS and cleanup true. Its source recording is complete at 5fps with 1,587 frames and no issues. The independent native object judge measured lift 0.1020m, XY error 0.0000513m, Z error below 0.00000005m and 2.242 simulated seconds stable after release. These are assisted-SIM teacher results, not learned-policy or physical-device acceptance.

Model-PC source verification then rejected that original recording because the fixed SIM truth contract still required 10fps. Logs are under `sampled-teacher-truth-model/`. The rejection is retained; no manifest or timestamps were relabeled. A separate contract slice must permit and validate the selected 5fps stream before this episode can enter learning.

The expanded sampling landing run also exposed two import failures on main: 1,615 cases passed, 20 skipped, two failed. An explicit main run confirmed both. Their isolated repair and signed-payload evidence are recorded in `docs/validation/learning-evidence-imports-2026-10-23/result.md`; the repair landed separately at commit `ab255dabdb`. The sampling slice must rerun its landing gate against that repaired main.
