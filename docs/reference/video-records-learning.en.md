# Learning-data Video Records (09-19 ~ 11-20)

한국어: [video-records-learning.md](video-records-learning.md)

Purpose: show in video how learning data travels from teleop recordings through LeRobot export and HF back into cell model verification.

## Core conclusions

- What is shown: 22 teleop originals (front camera, no arms), LeRobot export, an HF round trip, and episode 79 replay.
- What is not shown: the robot names and tasks of the 9 recordings without a sidecar, and per-session success or failure. The export and policy videos are sim renders.
- Next videos: a real 3-tier stacking placement scene and the HF round-trip record for the 11-18–20 bundles.

### 1 Teleop recordings — collection (09-19 ~ 10-05)

There are 22 human teleop learning-recording mp4 originals. That is inventory's 24 rows minus 1 typo row and 1 retired copy. The 13 recordings with a sidecar (8kcn 7 · 9dfk 6) have confirmed tasks: calibration 6, lane driving 2, intersections 2, demos 3. All 22 show the robot front camera, and no arms appear in any of them. The robot names and tasks of the 9 recordings without a sidecar (part ×7 · teleop_201 ×2) are unconfirmed.

### 2 LeRobot export (10-21 ~ 10-22)

The teleop originals were exported to the LeRobot episode format. batches 7 · 9 · 10 · 11 · 12 · 14 · 15 were exported 3 times each, and object · contact-hold once each. The record lists a fixed cohort of 25/25 demonstrations and a full 66,080-frame readback pass. Frame inspection identified the export video scenes as sim renders.

### 3 Learning run (10-23)

The connection that feeds export results into the training tool was tested with a synthetic device. ACT 2-step training and reload in a new process passed. The paired record loop showed that the saved actions match the actually sent actions.

### 4 HF upload and round trip (10-24)

One SIM scripted-teacher episode was uploaded to a private dataset and downloaded again. The SHA verification of 1,613 files · 1,587 frames and the reader verification passed. The dataset is pinned to the `robotteam/rosy-omx-sim@5a7a5952` revision.

### 5 Reuse in cell model verification (11-18 ~ 11-20)

pinky_v1 episode 79, a past human demonstration used for training, was replayed in a cell model verification slot. An Isaac Sim successful episode was also confirmed with position-sample replay. These videos show collected data being read again at the verification stage.

## Video table

Links use file names only. Per the 11-20 frame inspection, covers carry [real] · [sim] · [screen] tags.

| No. | What | When · where | Result | Length · evidence · link |
|---|---|---|---|---|
| 1 | Representative part01 of the 7-view teleop series | 09-19 15:12 UTC · real, robot name unconfirmed | Front-camera driving scene (screen observation), outcome unconfirmed | 100.5 s · 320x240 · [real] · `teleop_20260919_151213_part01.mp4` |
| 2 | Shorter of the 2 teleop_201 upright recordings | 09-28 21:50 UTC · real, robot name unconfirmed | Front-camera driving scene (screen observation), outcome unconfirmed | 250.3 s · 640x480 · [real] · `teleop_201_20260928_215056_upright.mp4` |
| 3 | 8kcn lane-driving session (backfill target) | 09-30 12:47 UTC · real rosy-pinky-8kcn | Lane driving (sidecar), selected for materialization after backfilling all 2,258 shadow frames, outcome unconfirmed | 282.2 s · 320x240 · [real] · `teleop_rosy-pinky-8kcn_20260930T124745Z.mp4` |
| 4 | 8kcn lane-driving session (holds a shadow payload) | 10-01 13:08 UTC · real rosy-pinky-8kcn | The only session with a shadow payload among the surveyed sessions, 14,240 frames, lane driving (sidecar), outcome unconfirmed | 1,787.4 s · 320x240 · [real] · `teleop_rosy-pinky-8kcn_20261001T130842Z.mp4` |
| 5 | 9dfk pilot session | 10-05 13:45 UTC · real rosy-pinky-9dfk | pilot demo (sidecar), intent and outcome unconfirmed, 3 copies exist | 470.9 s · 320x240 · [real] · `teleop_rosy-pinky-9dfk_20261005T134540Z.mp4` |
| 6 | batch 7 export-1 sim scene | 10-21 · sim render (screen observation) | Whole batch passed cohort 25/25 demonstrations · 66,080-frame readback, the 7 samples move a cube onto the blue plate | 264.2 s · 320x240 10fps · [sim] · `file-000.mp4` |
| 7 | Representative of 13 policy-input webms (9447 inputs, other 12) | 10-21 ~ 10-22 · sim render (screen observation) | All 12 show the same sim scene, policy output unconfirmed | 13.2 s · 320x240 8fps · [sim] · `omx-native-9447-inputs.webm` |
| 8 | contact-hold teacher full-rgb | 10-22 · sim render (screen observation) | 3 training · reload completions linked to the contact-hold collection ledger (10-23 record) | 261.9 s · 320x240 10fps · [sim] · `omx-teacher-c7dedb9bfcfd-full-rgb.mp4` |
| 9 | atomic-teacher export opening scene | 10-23 · sim render (screen observation) | Context of the fixed teacher cohort CT20261023a566 (25 planned), a cube moves onto the blue plate | 317.2 s · 320x240 5fps · [sim] · `file-000.mp4` |
| 10 | Two-arm synthetic reader videos ×2 | 10-23 · synthetic device (SDK) | ACT 2-step training · new-process reload passed, synthetic connection only | 0.5 s · 0.1 s · 32x32 30fps · [sim] · `file-000.mp4` ×2 |
| 11 | paired SDK record loop | 10-23 · synthetic device (LeRobot 0.4.4) | 1 episode 9 frames PASS, saved and sent actions match | 0.3 s · 128x128 30fps · [sim] · `file-000.mp4` |
| 12 | HF round-trip payload video | 10-24 · SIM scripted-teacher | Verified after upload by readback: 1,613 files · 1,587 frames | 317.4 s · 320x240 5fps · [sim] · `file-000.mp4` · `robotteam/rosy-omx-sim@5a7a5952` (private) |
| 13 | Isaac round-trip episode path replay | replayed 11-19 · sim, Isaac Sim successful episode | Return to start, final placement XY max deviation 1.859 mm (position-sample replay) | 30.2 s · 960x480 15fps · [sim] · `roundtrip-measured-trace.webm` · [GIF](../assets/video-records/av-learning-roundtrip.gif) |
| 14 | pinky_v1 episode 79 replay | replayed 11-20 · learning-data replay (top · wrist cameras), original capture time unconfirmed | An object moves from Pinky to the belt, PTS to data-row deviation within 1 ms | 18.3 s · 960x384 15fps · [real] · `episode-79.mp4` |
| 15 | Cell S live 8 s recording and a 3 s recorder-tool smoke | 11-19 ~ 11-20 · real Cell S top · wrist | The live 8 s is a static observation, max time gap of 32 pairs 102.11 ms. The smoke confirmed 12-frame decoding | 8.0 s · 3.0 s · 1280x524 4fps · [real] · `cell-s-current-views.webm` ×2 |

## Representative figures

![pinky_v1 episode 79 replay used for training, top and wrist views [real]](../assets/video-records/av-learning-episode79.gif)

![LeRobot export result video, batch 7 export-1 sim scene [sim]](../assets/video-records/av-learning-export.gif)

![Position-sample replay of an Isaac Sim round-trip episode [sim]](../assets/video-records/av-learning-roundtrip.gif)

## What is missing

- The export videos of batch 16 (3 runs) and batch 17 (1 run) demonstrations are not in this list.
- The robot names and tasks of the 9 teleop recordings without a sidecar (part ×7 · teleop_201 ×2) are unconfirmed. Frame samples did not decide session outcomes for the 22.
- 12 of the 13 policy-input webms were inspected; the remaining 1 is absent from the hand-off list.
- The record evidence for the teacher-held-batch-input-proof and sampled-teacher videos is unconfirmed.
- No HF upload record tied to the 11-18–20 bundle videos was found. The revision cell stays unconfirmed.
- The original capture time, HF revision, and which arm was recorded for pinky_v1 episode 79 are unconfirmed.
- The dataset name `robotteam/rosy-omx-data` has no permission record, so this document does not use it.
- The file in the inventory typo row (`…mp414354493`) does not exist. A normal mp4 with the same name is in retired.

## Evidence

- `workspace-records/2026-10-21/pipeline-execution-2026-10-21.md`
- `workspace-records/2026-10-23/learning-pipeline-current-evidence.md`
- `workspace-records/2026-10-24/hf-private-roundtrip-result.md`
- `workspace-records/2026-10-24/hf-readback-recovery-solution.md`
- `workspace-records/2026-10-28/selection-strategy-experiment.md`
- `workspace-records/2026-10-28/recording-lerobot-hf-uiux-review.md`
- `workspace-records/2026-10-29/shadow-evidence-backfill-result.md`
- `workspace-records/2026-10-29/recording-shadow-gate-design.md`
- `workspace-records/2026-11-18/arm-s-model-onboard.md`
- `workspace-records/2026-11-19/omx-cell-s-act-shadow-check.md`

## Read next

Calibration system: [calibration-system.en.md](calibration-system.en.md) · Demo videos: [video-records-demo.en.md](video-records-demo.en.md)

Same article: team Confluence · Notion
