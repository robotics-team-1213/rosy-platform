---
title: LeRobot lives in the Learning center's learner venv, not in the remote test venv
date: 2026-10-25
category: workflow-issues
module: tools/remote/remote_pytest.py, learning/curation/omx, learning/training/omx
problem_type: workflow_issue
component: development_workflow
severity: medium
symptoms:
  - "a LeRobot-dependent test (lerobot==0.4.4 import) skips under remote_pytest on every test host"
  - "an agent searched the test hosts, found no LeRobot, and reported that ROSY has no LeRobot environment"
root_cause: wrong_environment_assumed
resolution_type: procedure
tags: [lerobot, remote-pytest, model-pc, learner-venv, skipped-test, omx, verification]
applies_when:
  - "a test or check needs lerobot, torch or another learner-only package and skips under remote_pytest"
  - "deciding whether a host has a package before proposing to install it"
---

# LeRobot lives in the Learning center's learner venv, not in the remote test venv

## Problem
`remote_pytest.py` runs pytest in each host's test venv (`~/rosy-test/venv`). That venv has no `lerobot`, so tests that import it skip. On 2026-10-25 an agent searched both test hosts for a LeRobot install. It checked `~/rosy-test/venv`, `~/rosy-ml/.venv` and the project `.venv` folders, found nothing, and reported that no ROSY host had LeRobot. It proposed installing a new torch-sized venv. The search skipped hidden folders under `~`.

## What is actually there
On the model PC, the Learning center runs OMX learning with its own pinned CPU learner venv: `~/.local/share/rosy-learning-center/venv-cpu/bin/python`. On 2026-10-25 it had Python 3.12.3, `lerobot 0.4.4` and `torch 2.10.0+cpu`, the same pins as `deploy/robot/omx/requirements-lerobot-export.txt`. The center's OMX config names it for both `python.act` and `python.hilserl`. That venv has no pytest. Do not install anything into it: it is the center's runtime, and any change alters what the center trains with.

## How to run a LeRobot-dependent check
Use the pattern `learning/training/omx/test/test_experiment_tasks_pinned.py` already uses. The pytest test stays in the test venv. It skips unless an explicit flag is set (`ROSY_RUN_PINNED_LEARNING=1`), asserts that the learner Python exists, and runs the LeRobot part as a subprocess with that Python (`-I -B`, a minimal env, `HF_HUB_OFFLINE=1`). Run it through `remote_pytest.py -- ROSY_RUN_PINNED_LEARNING=1 <test>`, pinned to the model PC.

## Rules
- A skip under `remote_pytest` means the test venv lacks the package. It does not mean the host lacks it. Before saying a host lacks a package, check the center's OMX config for its learner Python paths, and include hidden folders (`~/.local/share`) in any search.
- Do not install a new learner venv on a test host before checking for one. The AI PC disk filling up has turned unrelated tests red before.
- A skipped byte-identity or real-LeRobot test is "not verified", never a pass (see `inability-to-check-recorded-as-clean-result.md`).

## Evidence
Model PC, 2026-10-25. The test venvs and `~/rosy-ml/.venv` returned `ModuleNotFoundError: No module named 'lerobot'`. The learner venv imported `lerobot` from `venv-cpu/lib/python3.12/site-packages/lerobot` and reported `0.4.4`, `2.10.0+cpu`, with `No module named pytest`.
