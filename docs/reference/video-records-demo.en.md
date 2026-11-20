# Real · Sim Demo Video Records (11-07 ~ 11-20)

한국어: [video-records-demo.md](video-records-demo.md)

Purpose: collect in one document the 11-10 real 3-tier stacking real2sim, the two-arm comparison, the presentation GIFs, and the 11-16 real clips.

## Core conclusions

- What is shown: the 11-10 real attempts (Trials 1–12 and autocal), MuJoCo · Isaac paired sims, the two-arm comparison, and the presentation GIFs.
- What is not shown: a successful real 3-tier stacking scene. The unrecorded attempt video shows only up to a stacking scene.
- Next videos: a post-verified real 3-tier placement scene and recovered copies of the 2 broken 11-16 clips.

### 11-10 real 3-tier stacking real2sim

The arm_b cell drove container tier-1 · 2 · 3 stacking as Trials 1–12. The placed · PASS results are the program verdicts of the time and are not real-stacking confirmations (corrected 11-13). The measured snapshot 20261110-1231 was carried into MuJoCo and Isaac to run paired simulations.

### 11-07 · 08 two-arm sims

MuJoCo compared two-arm coordination and one-arm sequencing on the same tasks. Two-arm simultaneous stacking was 9–10% shorter than one-arm sequencing, and outbound was also shorter. The ACT round-1 evaluation failed with 0 of 63 steps passed.

### Presentation GIFs

Highlight GIFs used in the presentation deck were collected. Direct frame inspection classified them as 9 real, 3 sim, and 2 graphic · map kinds. No original attempt or result records exist, and "closest to Trial 7" is recorded as unconfirmed.

### 11-16 real clips

Direct frame inspection confirmed these are real cell-camera videos. The 1280x480 width places the cell top (left) and wrist (right) views side by side. A record naming the moved arm and attempt number is still missing.

### 11-20 excerpts and baselines

On 11-20 the A · B baseline videos and a Trial 9 excerpt were made. One unrecorded real attempt video found that day is also in the table.

## Video table

The top · side · wrist of the same attempt are grouped into one row, and links use file names only.

### 11-10 real attempts (arm_b cell)

<details><summary>11-10 real attempts (arm_b cell)</summary>

| No. | What | When · where | Result | Length · evidence · link |
|---|---|---|---|---|
| 1 | First real drive pallet-l0→pallet-l1 (drive ID 20261110T042820Z-001) | 11-10 13:28 · cell top·wrist·merged | approach downgraded at 0.04, overload-hold, restore_caps bus timeout incident. Not a stacking success | 47.3 s · 640x480 10fps · [real] · `real-20261110-132822-{top,wrist,top-wrist}.mp4` |
| 2 | Trial 3: pick up row 1 Row2 | 11-10 17:04 · cell top·side·wrist | jaws short 5.0 units during park, holding 239 mA. Transfer · stacking not completed | 62.8 s · 640x480 10fps · [real] · `real-20261110-170442-{top,side,wrist}.mp4` |
| 3 | Trial 8: tier-2 verify_placed | 11-10 18:49 · cell top·side·wrist | Program verdict placed (off_mm 7.6) · PASS, not a real-stacking confirmation. A tilted scene exists | top 547.2 s · side 222.1 s · wrist 221.9 s · 640x480 · [real] · `real-20261110-184942-{top,side,wrist}.mp4` |
| 4 | Trial 9: correction of column 3 after tier-2 stacking | 11-10 19:07 · cell top·side·wrist | Program verdict placed, not a real-stacking confirmation. An upright container above column 1 in the photo | 628.7 s · 640x480 10fps · [real] · `real-20261110-190708-{top,side,wrist}.mp4` |
| 5 | Trial 10: column-3 grasp | 11-10 19:23 · cell top·side·wrist | Right edge boundary confirmed, jaw_margin 0.8 mm. Continued by a code fix | 723.3 s · 640x480 10fps · [real] · `real-20261110-192301-{top,side,wrist}.mp4` |
| 6 | Trial 11: tier-2→3 pallet-l1→l2 | 11-10 20:00 · cell top·side·wrist | Arm motion progressed; tier-3 placement and full stacking unverified. The verdict is program-based and not a real confirmation (the 11-19 document is not success evidence either) | 320 s · 640x480 10fps · [real] · `real-20261110-200031-{top,side,wrist}.mp4` |
| 7 | Trial 12: autocal grasp | 11-11 01:33 · cell top·side·wrist | Column-3 grasp_pick 54.36/172 mA, grasp_debate proceed, arm-cal-arm_b.json created | 61.3 s · 640x480 10fps · [real] · `real-autocal-grasp-{top,side,wrist}.mp4` |
| 8 | Trials 1 · 2 · 4–7 | 11-10 16:29–18:33 · cell top·side·wrist | 1 no jaw space, 2 contact_z 0.0173, 4 slip, 5 park after slip, 6 · 7 bias tests (record citation). Trial 7 files match the copies real-omx-{top,side,wrist}.mp4 in the first 16 sha256 characters | 154.7 · 287.2 · 385 · 427.8 · 415.1 · 425.1 s · 640x480 · [real] · `real-20261110-{162917,163649,173931,180705,181816,183300}-{top,side,wrist}.mp4` |

</details>

### 11-10–11 sim pairs

<details><summary>11-10–11 sim pairs</summary>

| No. | What | When · where | Result | Length · evidence · link |
|---|---|---|---|---|
| 9 | MuJoCo cell-stack t1 · t2 · t3 (based on measured snapshot 20261110-1231) | 11-10 · MuJoCo 4-view sim | Each 3/3 pass, xy_mm 0.2 or less, tilt 0.0, completed true (verdict inside the sim) | 29.3 · 29.3 · 27.3 s · 1280x960 15fps · [sim] · `sim-cell-stack-t{1,2,3}.mp4` |
| 10 | Isaac 3-tier continuous loading | 11-11 · Isaac Sim sim | Attached to team Confluence. Sequential decoding of 13,001 frames confirmed the real length of 1,300 s; verdict numbers unconfirmed | 1300.0 s · 800x600 10fps · [sim] · `omx-20261110-stage2-isaac-3tier-video-d1fae1ff.mp4` |

</details>

### 11-07 · 08 two-arm sims

<details><summary>11-07 · 08 two-arm sims</summary>

| No. | What | When · where | Result | Length · evidence · link |
|---|---|---|---|---|
| 11 | Reference-motion 3x3x3 stacking, 4-camera board | 11-07 · MuJoCo 4 cameras | 4-camera board of the first reference-motion record, numbers unconfirmed (the r08 board is 9/9) | 53.3 s · 1280x960 15fps · [sim] · `stack-four-cameras.mp4` |
| 12 | Temp-slot rehandling, 4-camera board | 11-07 · MuJoCo 4 cameras | Numbers unconfirmed (the r08 board is 12/12) | 79.3 s · 1280x960 15fps · [sim] · `rehandle-four-cameras.mp4` |
| 13 | ACT round-1 evaluation (stacking · rehandling) | 11-07 · MuJoCo learned policy | failed: 0 of 63 steps, 1 lift, 0/6 tasks carried to the end | 18.6 s · 21.5 s · 640x480 · [sim] · `act-round1-stack.mp4` · `act-round1-rehandle.mp4` |
| 14 | r08 rated base stacking · rehandling | 11-08 · MuJoCo 4 cameras | stacking 9/9, rehandling 12/12, 3 seeds passed (layout estimated) | 54.8 s · 78.5 s · 1280x960 · [sim] · `r08-stack-four-cameras.mp4` · `r08-rehandle-four-cameras.mp4` |
| 15 | Coordination stacking comparison: two arms simultaneous vs one arm B sequential | 11-08 · MuJoCo seed 0 | two arms 148.8 s · one arm 163.4 s (9/9), 9–10% shorter | 49.9 s · 54.8 s · 1280x960 · [sim] · `coop-stack-two-arm-conc.mp4` · `coop-stack-one-arm-B-seq.mp4` |
| 16 | Coordination outbound comparison: two arms simultaneous vs one arm B sequential | 11-08 · MuJoCo seed 0 | two arms 165.7 s (10/10), one arm 1 of 2 outbound items. Replay value 177.3 s (10/10) after a map change | 55.5 s · 31.1 s · 1280x960 · [sim] · `coop-outbound-two-arm-conc.mp4` · `coop-outbound-one-arm-B-seq.mp4` |
| 17 | First reference-motion record (short versions of stacking · rehandling) | 11-07 · MuJoCo | The record lists first records only | 160 s · 79.7 s · 1280x480 · [sim] · `stack.mp4` · `rehandle-short.mp4` |
| 18 | arm_b sim teacher · model round 3 | 11-07 · MuJoCo | Result numbers unconfirmed | 28.7 s · 34 s · 640x240 15fps · [sim] · `sim-teacher.mp4` · `sim-model-round3.mp4` |

</details>

### Presentation GIFs

<details><summary>Presentation GIFs</summary>

| No. | What | When · where | Result | Length · evidence · link |
|---|---|---|---|---|
| 19 | Isaac 3-tier highlight | 11-12 · Isaac sim excerpt | Linked in team Confluence; same scene as the opening part of the Isaac 3-tier video (scene observation) | 3.8 s · 800x600 8.3fps · [sim] · `isaac-3tier-highlight.gif` |
| 20 | Real OMX top · side highlights | 11-12 · real OMX | Closest to Trial 7 (183300) (unconfirmed), excerpt range and attempt unconfirmed | 3.8 s · 640x480 · [real] · `real-omx-top-highlight.gif` · `real-omx-side-highlight.gif` |
| 21 | Two excerpt GIFs (stacking attempt side · arm top) | 11-14 · real OMX | Closest to Trial 7 (183300) (unconfirmed), no motion change visible in the sampled range | 14.4 s · 14.6 s · 560x420 · [real] · `omx-stack-attempt-side.gif` · `omx-arm-top.gif` |
| 22 | Two coordination highlights | 11-16 · sim (MuJoCo-like 4-way split screen) | Sim 4-way split screen confirmed; original attempt and final 9/9 state unconfirmed | 10.5 s · 560x420 4fps · [sim] · `coop-one-arm-hold.gif` · `coop-two-arm-done.gif` |
| 23 | Procedure GIFs (plan · transport) | 11-14 · 3D graphic · map screens | step1 is a 3D graphic, step2 a line-and-marker map screen over a photo. Whether it is a real planning · driving record is unconfirmed | 17 s · 16 s · 420–480 width · [screen] · `step1-plan.gif` · `step2-transport.gif` |
| 24 | Procedure GIFs (grasp · unload · stack · check) | 11-14 · real cameras (wrist · top · side) | Real camera views confirmed; which arm and attempt, and whether the grasp held, are unconfirmed | 8–10.2 s · 420–480 width · [real] · `step3-grasp.gif` · `step3-unload.gif` · `step4-stack.gif` · `step5-check.gif` |
| 25 | omx z-sync shuttle video | 11-12 · real (includes a log line overlay) | Shuttle motion (original slot → temp slot → return) and the Elapsed overlay confirmed; attempt number and actual height restoration unconfirmed | 86.8 s · 640x299 4fps · [real] · `omx_z_sync_shuttle_preview.gif` |

</details>

### 11-16 real clips

<details><summary>11-16 real clips</summary>

| No. | What | When · where | Result | Length · evidence · link |
|---|---|---|---|---|
| 26 | arm_a live recording | 11-16 01:17 · real cell top · wrist | A cell scene showing 2 arms, plates, and supports; whether the moved arm is arm_a and the grasp result are unconfirmed | 280.9 s · 1280x480 8fps · [real] · `arm_a_live.mp4` |
| 27 | arm_s live recording | 11-16 01:07 · real cell S top · wrist | The arm reaches toward the belt and tilts; container movement unconfirmed | 112.8 s · 1280x480 8fps · [real] · `arm_s_live.mp4` |
| 28 | arm_s pick recording | 11-16 01:08 · real cell S top · wrist | Starts in a tilted arm pose; no successful grasp or object movement visible | 225.4 s · 1280x480 8fps · [real] · `arm_s_live_pick.mp4` |
| 29 | arm_s live recording 2 | 11-16 01:16 · real cell S top · wrist | The wrist view shows a support and a red object; result and moved object unconfirmed | 167 s · 1280x480 8fps · [real] · `arm_s_live2.mp4` |

</details>

### 11-20 excerpts and baselines

| No. | What | When · where | Result | Length · evidence · link |
|---|---|---|---|---|
| 30 | A · B baseline videos top · side | 11-20 01:22 · real cell | 8 s each, arms and worktable confirmed in the middle frame. Motion and layout unmeasured | 8.0 s · 640x480 10fps · [real] · `top.mp4` · `side.mp4` |
| 31 | Trial 9 two-tier 22 s excerpt | excerpted 11-20 (original 11-10) · real cell side | 220 frames, sha256 recorded (first 8 characters: clip 2ed61dc5 · source c61a471a). A tier-2 scene and not a real stacking success (corrected 11-13) | 22 s · 640x480 10fps · [real] · `trial9-two-tier-22s.mp4` |
| 32 | Unrecorded real 3-tier attempt video | found 11-20 · real side view | A gripper lowers containers into a stack. Tier count · arm · attempt unconfirmed, no collapse visible, not a 3-tier success verdict | 18.0 s · 640x480 10fps · [real] · `omx-real-tier3-attempt-18s.mp4` |

## Representative figures

![22 s excerpt of the 11-10 Trial 9 tier-2 scene (11-20). Program verdict placed, not a real-stacking confirmation [real]](../assets/video-records/av-real-trial9-2tier.gif)

![Two-arm simultaneous stacking 9/9, MuJoCo sim 4 cameras [sim]](../assets/video-records/av-real-coop-twoarm.gif)

![3-tier stacking sim 4 views, internal verdict 3/3 [sim]](../assets/video-records/av-real-sim-t3.gif)

## What is missing

- After Trial 11, real 3-tier placement · alignment · post-heights are unverified in the records (corrected 11-13).
- The 2 clips from 11-16 (`arm_s_live_pick2.mp4` · `arm_s_live2_b.mp4`) are broken unfinished recordings (no moov). Recovery was not attempted.
- The original attempts and results of the presentation GIFs remain unconfirmed even after the real · sim classification. The Trial 7 video itself shows little screen change, so its excerpt range is also undetermined.
- The verdict numbers of the Isaac 3-tier video are unconfirmed. The dummy tier count was also not fixed at the sheet resolution.
- The 11-07 first-record step pass numbers are unconfirmed. No numbers json exists in the same folder, and the README lists only r08 numbers.
- The HF dataset · revision of all 11-10 real attempts and the 11-16 clips is not in the records.
- The 11-19 rehearsal and post-11-20 episode videos have no files in this range.
- The Pinky Gazebo lap and world scenario videos (11-16) are outside the OMX scope and were left out of this document.

## Evidence

- `workspace-records/2026-11-10/omx-tier-stack-real2sim/README.md`
- `workspace-records/2026-11-11/publish_d1012_confluence.py`
- `research/omx-two-arm-20261107/README.md`
- `research/omx-sim-reference-20261107/README.md`
- `presentation/assets/README.md`
- Work-folder record `omx-ab-baseline-evidence-01a1f45e/result.md`
- Work-folder record `omx-early-layer-visual-20261120/trial9-two-tier-index.json`

## Read next

Calibration system: [calibration-system.en.md](calibration-system.en.md) · Learning-data videos: [video-records-learning.en.md](video-records-learning.en.md)

Same article: team Confluence · Notion
