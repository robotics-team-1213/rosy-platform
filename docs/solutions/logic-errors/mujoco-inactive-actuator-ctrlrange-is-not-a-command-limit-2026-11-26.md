---
title: A force-limited MuJoCo servo can report a zero inactive control range
date: 2026-11-26
category: logic-errors
module: tools/sim/omx_physics.py and OMX ACT evaluation harnesses
problem_type: logic_error
component: simulation
symptoms:
  - "Eight guarded OMX A C2 evaluations ran zero commands and stopped before the preregistered paired state"
  - "The generated six-axis action was finite and inside the intended command envelope"
root_cause: wrong_api
resolution_type: code_fix
severity: medium
tags: [mujoco, omx, actuator, command-admission, simulation]
applies_when:
  - "An experiment adds a command limit in front of a MuJoCo position servo"
---

## Symptom

The original late-handoff evaluation stopped at C2 frame 0 in eight scenarios. Each run recorded an invalid action with zero applied commands. The source gate had admitted the intended named route.

## Root cause

The harness read six `actuator_ctrlrange` arrays containing `[0, 0]` without checking `actuator_ctrllimited`. The position servo in `tools/sim/omx_physics.py` enables a force limit. The inactive control range retains default bounds. Each simulation harness defines the command domain for its joint and jaw units. The experiment therefore rejected a valid command before the controller could reach the paired state.

## Correction and regression

Check the active control-limit flag before treating `actuator_ctrlrange` as authoritative. Where the range is inactive, use the command domain defined by the specific simulation and its units. The corrected A C2 harness uses the compiled position joints for axes 0 through 4 and the modeled gripper command stroke for axis 5. The controller keeps the original force limits and motion guards.

A bound check confirmed all six actuators had `actuator_ctrllimited` false and `actuator_forcelimited` true. The corrected domain accepted all eight falsely rejected frame-0 proposals and 672 recorded native prefix commands. Twelve controls 0.0001 units outside their lower or upper bounds were rejected. The corrected simulation reached the reserved fork in eight new independent scenes across the two start orders. These checks validate simulator command admission.

When interpreting an evaluation failure, record the number of applied commands and the first rejected sample before comparing policies. Treat an invalid frame-0 harness run as unavailable evidence of model behavior.

