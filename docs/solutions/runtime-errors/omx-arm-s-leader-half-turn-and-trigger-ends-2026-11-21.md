---
title: arm_s Leader and Follower disagree by half a turn on pan and roll, and the trigger needs its own ends
date: 2026-11-21
category: runtime-errors
module: deploy/robot/omx (guarded_native.py, guarded_native_cli.py, leader_home.py, bench_record)
problem_type: runtime_error
severity: high
symptoms:
  - "shoulder_pan: difference >=100 degrees; leader=4151, target=55, current=2047 with both arms in the same shape"
  - "leader_home blocked at the cap when driving the Leader pan to the Follower's raw value"
  - "gripper: following error >5 motor degrees; command=1948, current=2005 at teleop start"
  - "chunk sessions and cell_upkeep: wrist.jaw_edge_px: unknown parameter after a bench deploy"
resolution_type: code_fix
status: partly_open
---

# arm_s teleop: half-turn Leader zero, trigger ends, and a shared tools link

## What happened (2026-11-21, first arm_s Leader/Follower teleop on the bench)

1. With the Leader held in the Follower's shape, raw ticks differed by half a turn on shoulder_pan and wrist_roll
   (Leader 3958 / 4166, Follower 2046 / 1949). The guard compares raw ticks and allows whole turns only, so it
   refused. Driving the Leader pan to the Follower's raw value with leader_home pointed it backward and it stalled
   at the cap twice. The first reading (pan 4179) was taken for a hand-turned Leader; it was the Leader's real front.
2. The Leader trigger reads 1906 (squeezed) to 3773 (open). The stock mapping put that on Follower ticks past the
   closed jaws (closed-empty is 2005), so teleop stopped on the gripper following error. A 20 s read window that
   missed the person's motion gave a wrong 77-tick range first: log until the person answers, not for a fixed time.
3. The bench deploy had pointed the shared ~/rosy-test/omx-tools-current link at a bench branch tree that does not
   know wrist.jaw_edge_px. Every chunk session and cell_upkeep failed from 14:21 until the link was restored.
4. cell_task_worker latches human-hold on every arm session when the Fleet safety listing misses its 0.5 s
   deadline three times. R Fleet was at 100 % CPU, so a supervised recover stopped mid-way and opened an incident.

## Fix

- guarded_native.NativeJointMotion takes `mount` (half a turn, body joints) and `grip_map` (trigger ends to jaw
  ends, clamped). guarded_native_cli reads both from `<leader calibration>.mount.json`; a missing file means none,
  anything unreadable stops before torque. The 100 degree guard, the range checks and the 5 degree following error
  are unchanged. Body Homing_Offset stays 0 (connect_passive refuses anything else).
- arm_s file on the cell: pan -2048, roll -2048, trigger 3700/1930 to jaws 2379/2000.
- leader_home: a joint found past its range may only come back, and the deadline follows the distance.
- The bench page runs from its own link (omx-bench-current, systemd drop-in); omx-tools-current is cell tools only.
- Episode 1 of a two-episode session ended on "stale control loop" (age 29 s): lerobot_record runs save_episode (video
  encoding) after the reset loop, so no command reached the guard for 29 s while the arm held its last command.
  run_native marks each record loop start; a pause over 0.5 s before that loop's first command (leader teleop only,
  not teacher) restarts only the clocks and the alignment phase. The last command and offsets stay, so the same tick
  runs the 5 degree following-error, 100 degree, range and effort checks and Goal_Position does not jump; a gap
  inside a loop is still a fault. Accepted limit: a first camera or Leader read that stalls after the loop start
  looks the same as the save wait. The arm is then still holding its last command with torque ON, and the resumed
  tick applies the 5/100 degree checks and the 1 degree/s approach.

## Verified

Cell pytest 252 passed. Real arm: session 23 tracked the Leader for 27 s and a box went from the belt to Pinky.

## Still open

- Session 23 ended on a shoulder_lift overload latch (hw_error 32). Cause confirmed from the log: a Leader resting on
  its stand reads lift 670..704, the Follower's folded home is 862 and it stops mechanically near 713..722. The
  target stayed at 704, the Follower pushed at 713 for 22 s (error 0.8..1.6 degrees, PWM -200 to -502 in a straight
  line, i_gain 50), and the motor latched before the guard's overload hold (error over 2 degrees and |PWM| at 90 %)
  could fire. The box in the gripper was not the load. Action: the optional `follower_floor` key in
  `<leader calibration>.mount.json` ({"shoulder_lift": <tick>}) clips the mapped target to the floor
  (guarded_native.py, checked in guarded_native_mount.py); the clipped target is what the 100 degree and 5 degree
  checks see. Left open (separate safety review): i_gain 50 and the hold thresholds do not catch a slow push of this
  kind. The floor value itself is commissioned on the arm, not derived here.
- No episode was sealed. bench /home does not support arm_s (file names, unfolded Follower, Leader pose).
- The Fleet safety listing deadline against a loaded R (item 4) is unchanged.

## Apply next time

A new Leader/Follower pair gets a same-shape raw read of all six joints before the first session. A half-turn
difference is a mount constant, not a misalignment to drive out.
