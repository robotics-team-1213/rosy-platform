---
title: A MuJoCo stack that seats on the laptop (3.17) throws a seated box on the lab PCs (3.3.7), and remote pytest skips the test that shows it
date: 2026-11-04
category: logic-errors
module: tools/sim/ship_v11_scene.py; tools/sim/ship_stack_sequence.py; test/test_ship_stack_sequence.py
problem_type: logic_error
component: simulation
symptoms:
  - "error-free v11 stack: 9/9 seated on the laptop, box 7 (top layer) 11 mm off and 1.6 deg tilted on the AI PC"
  - "the box sat still on the lid below (velocity 0) and was thrown in one step with no jaw contact (angular velocity -11.9 rad/s)"
  - "tools/remote/remote_pytest.py reported exit 0 with the MuJoCo test file skipped (its env has no mujoco)"
root_cause: wrong_api
resolution_type: code_fix
severity: high
framework_version: MuJoCo 3.3.7 (lab sim-mujoco venv) vs 3.17 (laptop)
tags: [mujoco, box-box, version, remote-pytest, sweep, d-947]
applies_when:
  - "a MuJoCo scene rests box geoms flat on other box geoms (stacked containers, slabs on lids)"
  - "a MuJoCo result checked on the laptop is used for a lab-PC sweep"
---

## Symptom

The v11 ship stack (container v2 as a body box plus bottom slab boxes, resting on the lid box of the container below)
seated 9/9 with no release error on the laptop. On the AI PC the same commit lost box 7. It had settled, then
jumped with no contact from the jaw.

## Cause

- Box-on-box face contact in MuJoCo 3.3.7 produced a spurious impulse on a resting box. The laptop's 3.17 did not.
- The test that would show it (`test/test_ship_stack_sequence.py`) does `pytest.importorskip("mujoco")`. The
  remote_pytest environment has no MuJoCo, so it was skipped and the run still exited 0. Only the lab `sim-mujoco` venv
  ran it.

## Fix

- `ship_v11_scene._add_pieces` builds every box piece as an 8-corner convex mesh. Convex-mesh contact keeps the box
  seated at the same speed.
  - Checked on the AI PC: seeds 1 and 2 error-free stacks seated.
  - Half the timestep also worked but doubled the time.
  - impratio 1 did not work.
- The 32 sweep cases computed before the fix were discarded.

## Next time

- Run MuJoCo tests in the lab env, against an uploaded `git archive` of the commit:
  `~/rosy-test/venvs/sim-mujoco/bin/python -m pytest test/test_ship_stack_sequence.py`.
  Include `deploy/robot/omx` in the archive: the fixture reads `deploy/robot/omx/sim/cell_profile.yaml`.
- Read a remote_pytest "exit 0" with `-rs`. A module-level skip is not a pass.
- A laptop MuJoCo result is not evidence for the lab sweep until one case of the sweep is repeated in 3.3.7.
- Recovery: if a sweep ran on the broken scene, discard its rows (they are keyed by commit directory) and rerun with
  `--resume` into a new directory.
