---
title: A policy's camera names are the recorder's labels, not the cell's camera roles (Purple-SY "top" was the side camera)
date: 2026-11-21
category: logic-errors
module: deploy/robot/omx (cell_lerobot_shadow.py, cell_policy_drive.py), learning datasets and checkpoints, cell-arm-*-policy.json
problem_type: logic_error
component: development_workflow
symptoms:
  - "the arm_b ACT (Purple-SY left-c30-30k) asks for observation.images.top and wrist; the cell config's top is the overhead D435, so the model would have been fed the wrong view"
  - "the arm_a ACT (right-c30-30k) asks for observation.images.rs, a name no cell camera has"
  - "the cell's own record configs disagree too: record-config.json names arm_a's wrist camera 'front', record-config-arm-b.json names arm_b's wrist 'front' and the side camera 'side'"
root_cause: config_error
resolution_type: code_fix
severity: high
tags: [omx, lerobot, act, camera, naming, dataset, sim2real, purple-sy]
applies_when: "before a checkpoint or dataset recorded by anyone (a teammate, HF, a sim export) is fed cell frames, trained on, mixed with another dataset, or evaluated in MuJoCo"
---

# A policy's camera names are the recorder's labels, not the cell's camera roles

## Problem

On 2026-11-21 the Purple-SY ACT checkpoints for arm_a and arm_b were prepared for a shadow run on the cell. The cell config maps camera **roles** to frame URLs: `top` = the overhead RealSense D435, `side` = the horizontal camera facing the ship, `wrist` = the arm's wrist camera. The checkpoints name their inputs `top` + `wrist` (left arm) and `wrist` + `rs` (right arm).

The first preparation matched by name: the left model's `top` got the D435 and the right model's `rs` got the D435 by guess. The user asked why only top and wrist appeared when the cell has a D435, a side camera and wrist cameras.

## Root cause

A LeRobot camera key is whatever the person recording typed in the robot config. Nothing ties it to a physical camera. In the Purple-SY recordings (datasets list: top, wrist, rs, rs_depth):

| dataset key | what the frame shows (checked 2026-11-21) | cell role |
|---|---|---|
| `top` | horizontal view of the ship from the front, both arms visible | `side` |
| `rs` | overhead view of the ship, belt and both arm plates | `top` (D435) |
| `wrist` | the arm's wrist camera | `wrist` |

The 2026-10-31 re-wiring re-used the old overhead USB camera as the side camera and added the D435 on top (see omx-cell-device-identity-after-rewiring-2026-10-31.md); recording configs kept the old role name `top` for the moved camera and called the new one `rs`. The cell's own record configs still call wrist cameras `front`.

A name match therefore fed the left model a top view where it was trained on a side view: no error, plausible-looking output, wrong input.

## Fix

1. **One set of names.** Cell roles are the canon: `top` (overhead D435), `side`, `wrist`. Agreed with the learning session (D:/DevTemp/ab-divergence-panel-1121/DECISIONS-1121.md): new recordings and conversions write these keys.
2. **Rename checkpoints, not the cell.** The checkpoint inputs were renamed in a copy (config.json, train/policy processor JSON and the normalizer safetensors keys; weights untouched): `purple-left-c30-30k-side-wrist` (top→side), `purple-right-c30-30k-top-wrist` (rs→top). The same random frames under old and new names gave the same chunk (max difference 7.6e-6 and 0). The policy config then binds `top`, `side`, `wrist` to the real URLs with no aliasing.
3. **Refuse other names.** `cell_lerobot_shadow.read_features` refuses a checkpoint whose image inputs are not cell roles (`CAMERA_ROLES`), so an `rs` or `front` checkpoint cannot reach the cell or `cell_policy_drive` until it is renamed. Test: `test_checkpoint_camera_names_must_be_cell_roles`.

The name check cannot catch a swap between two valid names (the Purple-SY `top` was valid but meant side). That needs the frame check below.

## How to check a checkpoint or dataset

1. Pull one frame per camera key from the dataset (ffmpeg on `videos/observation.images.<key>/...mp4`, `-ss 1 -frames:v 1`).
2. Look at each next to the live cell frame of each role (`http://127.0.0.1:8767/frame/<role>.jpg` on the cell). Decide the role by what the view shows (overhead / horizontal / wrist), never by the key.
3. Rename keys to roles in a copy, then prove the copy gives the same output for the same frames.
4. Record the mapping in the checkpoint folder (`VIEW_NAMES.json`) and in the dataset card.

## Applies when

Before a checkpoint or dataset from anyone is fed cell frames, mixed into training, or rendered in MuJoCo (the sim cameras are named `top`, `side`, `wrist` too, so correctly named checkpoints need no view map there).
