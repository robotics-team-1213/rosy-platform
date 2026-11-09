---
title: LeRobot lives in the Learning center's learner venv, not in the remote test venv
date: 2026-10-25
updated: 2026-11-09
category: workflow-issues
module: tools/remote/remote_pytest.py, learning/curation/omx, learning/training/omx
problem_type: workflow_issue
component: development_workflow
severity: medium
symptoms:
  - "a LeRobot-dependent test (lerobot==0.4.4 import) skips under remote_pytest on every test host"
  - "an agent searched the test hosts, found no LeRobot, and reported that ROSY has no LeRobot environment"
  - "a landing stops with NEW failure `assert python.is_file(), 'existing pinned learner required...'` for test_learning_workflow_pipeline_browser, only when remote_pytest placed it on the site PC"
root_cause: wrong_environment_assumed
resolution_type: procedure
tags: [host-capability, lerobot, remote-pytest, model-pc, learner-venv, skipped-test, omx, verification]
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


## Update 2026-11-09: the site PC had no learner venv, and placement did not know
**Symptom.** `test/learning/perception/test_learning_workflow_pipeline_browser.py::test_synthetic_task_completes_review_training_evaluation_and_download` asserts `~/.local/share/rosy-learning-center/venv-cpu/bin/python` exists. On the site PC (robttt) it never did, so every landing whose browser tier put that file there stopped with a NEW failure: seven branches in the 11-02..08 window, all on robttt, none caused by the branch.

**Cause.** The model and AI PCs had the venv, the site PC never had it, and no script built it. `remote_pytest` places invocations on any host of `ROSY_TEST_HOSTS` or `private/lab-hosts.json` `test_hosts` that has free cores and memory. Nothing said that this test needs the environment.

**Fix.** Two parts. (1) Environment: `tools/remote/provision_learner_venv.sh` builds the venv with `uv` from `deploy/robot/omx/requirements-lerobot-export.txt` (or a full `pip freeze` of the model PC's venv) and the PyTorch CPU index with `--index-strategy unsafe-best-match`; a second run builds nothing. On 2026-11-09 robttt got it by hand the same way (Python 3.12.15, lerobot 0.4.4, torch 2.10.0+cpu, about 1.9 GB). (2) Routing: the test module declares `HOST_CAPABILITIES = ('learner_venv',)`. The host probe prints a `ROSYCAPS` line, `tools/remote/host_caps.py` maps a capability name to the path that proves it, and `remote_pytest` hands such an invocation only to hosts that have it. When no placed host has it, the run waits like any "no test host reachable" case and then fails as not run, never as a pass. The assertion in the test is unchanged.

**Verification.** On robttt with the new venv, main `e741ce764f`: the test ran `1 passed`. The routing has regression tests in `test/test_host_caps.py` (probe parse, declaration read from the committed file and folder, route filter, stranded work, no capable host). Those ran on a remote test host; they do not prove the real placement on a host without the venv, which the next landing that carries the file shows.

**Recovery.** A host that lacks a capability is not broken: run `tools/remote/provision_learner_venv.sh` on it (no root, `uv` needed), or leave it out of `ROSY_TEST_HOSTS`. Do not install into the center's own venv on the model PC. A new environment-bound test adds its name to `host_caps.CAPABILITIES` and the module constant; it does not get a skip.

**Apply next time** a test asserts a host-local path, GPU, browser or package that some test hosts lack: declare it, do not rely on ROSY_TEST_HOSTS pinning by memory.
