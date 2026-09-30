---
title: A comment edit in device-python-requirements.txt cut every flashed robot off from payload updates
date: 2026-10-01
category: workflow-issues
module: deploy/robot/pinky_pro/image (device-python-requirements.txt, inputs.lock.yaml, native_release.py)
problem_type: integration_issue
component: development_workflow
symptoms:
  - "payload 2026.09.30-004 carried python-runtime.sha256 2b003fd4..., while rosy-pinky-8kcn's image recorded a66f224a..."
  - "native_release.py check_python_runtime refuses a release whose runtime id differs from the image's (D-189)"
  - "the only change to the requirements file since the robot's image was two comment lines rewritten by a folder move (e3b0c95e)"
root_cause: missing_validation
resolution_type: code_fix
severity: high
tags: [payload-release, python-runtime-id, d-189, d-225, folder-move, fleet-compatibility]
---

# A comment edit in device-python-requirements.txt cut every flashed robot off from payload updates

## Problem
The device Python runtime id is the sha256 of the **whole** `deploy/robot/pinky_pro/image/device-python-requirements.txt`. It is not a hash of the pinned packages. `build-native-payload.sh` writes that id into every payload as `python-runtime.sha256`. On the robot, `native_release.py` `check_python_runtime` refuses any release whose id differs from `/usr/local/share/rosy/python-runtime.sha256` in the image.

Commit e3b0c95e (2026-09-28) was a folder move. Its blanket path rewrite changed two path strings inside comments of that file. It also updated `inputs.lock.yaml` to the new hash, so the image build stayed green. No package changed, but the runtime id (a file sha256, not a commit) moved from `sha256:a66f224a...` to `sha256:2b003fd4...`. From then on, **no payload built from main could activate on any robot flashed before the move**. That covered every robot in use.

## How it was caught
It was caught before the push, by comparing the extracted payload's `python-runtime.sha256` with the robot's (`ssh ... cat /usr/local/share/rosy/python-runtime.sha256`). That comparison is not a step in the `rosy-release-push` skill. Without it, the push would have failed at activation, and the reason would not have been obvious.

## Solution (3afb64a6, on local main)
- Restore the file's exact pre-move bytes and set the lock pin back to `sha256:a66f224a...`. The comment paths are stale again, and that is deliberate.
- `test/test_python_runtime_id.py` pins the sha256 of both the file and the lock value. Any byte change, a comment included, now fails the gate with the reason in the docstring. Mutation check: appending `# x` turns it red.

## Prevention
- Treat bytes that feed an identity hash as frozen data, not prose. Exclude them from mechanical rewrites (sed across the tree, path moves, comment cleanups).
- A real runtime bump must ship with a new image. It must also update both pins in `test_python_runtime_id.py`, so the break is deliberate and visible in review.
- Before pushing a payload to a robot, compare its `python-runtime.sha256` with the robot's image record. A mismatch is a stop, not a warning.
- New device-side Python dependencies (for example onnxruntime for D-373) go in a **separate** hash-locked requirements file, the way `camera-python-requirements.txt` does, never in this file.

Related: [folder-move-widens-path-scoped-contract-tests](folder-move-widens-path-scoped-contract-tests-2026-09-25.md), [blanket path rewrite of release-layout paths](blanket-path-rewrite-hits-on-device-release-paths-2026-10-01.md).
