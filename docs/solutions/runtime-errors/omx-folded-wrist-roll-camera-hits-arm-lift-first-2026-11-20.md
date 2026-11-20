---
title: A folded OMX arm cannot turn its wrist roll home; lift the elbow first
date: 2026-11-20
category: runtime-errors
module: deploy/robot/omx (cell_unwedge.return_home, cell_pipeline --stage home, cell_task_worker)
problem_type: runtime_error
component: development_workflow
symptoms:
  - "all three cell arms rested folded, torque off, wrist_roll 60-96 units from home (A -49.3, B -50.5, S +57.5)"
  - "no chunk could start (direct start delta 44-58 > 10) and limit_error refused every return at its first frame"
  - "contact in jog: wrist_roll lag rose to 2.2 units at PWM 51 of 300 (arm_a, roll 18-20, twice)"
  - "human hold latched on every live runner a few seconds after a session started"
root_cause: wrong_assumption
resolution_type: code_fix
severity: high
tags: [omx, arm-a, arm-b, arm-s, wrist-roll, recovery, camera, task-worker]
applies_when: "an arm rests folded with the wrist roll far from home, or any recovery turns the wrist roll in the folded pose"
---

# A folded arm cannot turn its wrist roll home; lift the elbow first

## Symptom
On 2026-11-20 arm_a, arm_b and arm_s all rested torque-off in the folded home pose except the wrist roll (60-96 units off) and closed jaws. Some joints were also past their configured limits (B wrist_flex 55.56 > 55.3; A wrist_flex 57.07 > 56, wrist_roll -49.3 < -31). Every chunk start was 44-58 units away, so the runner refused them, and `limit_error` refused every return at its first frame.

## What did not explain it
- Hand-moving to a chunk start: the 44-unit gap was the shoulder, not the wrist. Chunk starts are extended poses; a torque-off arm left there falls.
- "Cable wrap" on arm_a: wrong. A's settled roll lag was flat (0.5-1.0) from -46 to +16; a wrapped cable shows a rising, spring-like lag.
- The MuJoCo holder clearance (`tools/sim/omx_load.py`, 2.3 mm at roll ~±11) depends only on the roll and is passed by every reviewed cycle. The sim holder has no camera body, so it cannot show the real hit.

## Cause
In the folded pose the long wrist camera body sweeps into the arm when the roll turns (arm_a stalled at roll 18-20; the runner's contact guard caught it twice without harm). arm_b happened to pass.

## Fix
`cell_pipeline --stage home --person-at-switch` (`cell_unwedge.return_home`): out-of-limit joints move inward first; when the four body joints are within 10 units of home and the roll is more than 10 off, it lifts `elbow_flex -10` (holder low point 176 -> 234 mm in sim), turns the roll in 4-unit guarded jogs, then lowers. Strain is checked before settle; a lag that stops changing under the strain ceiling counts as settled (A's P-only roll held 1.75 once). It ends with `stop now` only from a folded rest, never a bare `stop` (fold-on-stop park). Preflight now flags library frames past joint limits and prints the return command when no direct start fits.

Field result 11-20: B (no lift) body gap 0.93; A and S (lift) 1.02 and 0.63; no strain or contact trips.

## A second cause of stopped recoveries
`cell_task_worker` latched human-hold on every live runner when one 0.5 s poll of the Fleet queued-task listing missed. It cut the supervised returns twice. Now only three missed polls in a row latch (about 4.5 s); explicit `active_estop` or human detection still latches at once.

## Next time
- Read the arm's own pose against home before blaming cables: compare per-step settled lag across the travel.
- A torque-off folded arm is a rest; a chunk start is not.
- Clear a human-hold incident on the cell Fleet (8543) with the agent-operator login only on the user's word (memory: cell-fleet-agent-operator-login).
- Unresolved: why all three arms were left with the roll turned. Look for the tool that turned the roll and ended the session.
