---
title: A two-robot payload update took three releases and most of the time went outside colcon
date: 2026-10-01
category: workflow-issues
module: deploy/robot/pinky_pro (image/build-native-payload.sh, .github/workflows/build-native-payload.yml, rosy-calibration-guard.ps1, release push steps; releases 2026.10.01-019/020/021)
problem_type: performance_issue
component: development_workflow
symptoms:
  - "one deployment to two robots built three payload releases (019, 020, 021) in about two hours"
  - "the runner build took 6.5 min, of which colcon was 40 s; rosdep took ~4.5 min installing ~958 packages through 22 separate apt-get runs"
  - "gh run download took 2 min 12 s for a 48 MB artifact"
  - "a hand-run ABI comparison parsed name=version with split() and compared nothing"
  - "the calibration guard looked for <ip>.credential.xml while the files are named <hostname>.credential.xml, so the safety check was skipped without anyone noticing"
root_cause: missing_tooling
resolution_type: workflow_improvement
severity: medium
tags: [release, payload-build, rosdep, apt, github-actions, artifact-download, abi-check, calibration-guard, cycle-time]
---

# A two-robot payload update took three releases and most of the time went outside colcon

## Problem
The task was "update both robots to current main". It cost three ARM64 builds and about two hours. Rebuilding was the smaller part of that. Most of the time went into decisions made between builds and into manual steps that failed silently.

## Symptoms
- **019.** Built from main. It shipped D-397 geometry defaults that needed the user's approval, and that was only noticed after the build.
- **020.** Built again after the activation defect was fixed (see `docs/solutions/runtime-errors/payload-activation-left-core-on-the-old-release-2026-10-01.md`).
- **021.** Built a third time after a peer pushed a G4 hotfix (10994c84) that 9dfk was already running by hand. Installing 020 there would have removed that hotfix and voided the G4 seal.
- **Runner time** (run 36865620181):

  | Step | Time |
  |---|---|
  | ROS build prerequisites | 75 s |
  | rosdep, as 22 `apt-get install -y <one key>` runs (30 trigger passes) | ~4.5 min |
  | colcon | 40 s |

- **Operator PC.** Download took 2 min 12 s. Extract, sign and pack took 35 s. The push took 49 s.

## What Didn't Work
- Building as soon as one change was ready. Each new fact meant another build: a peer's hotfix, a needed approval, a defect found on the device.
- Hand-written one-off checks. The ABI compare split on whitespace and reported "0 mismatches" without comparing anything. A session that ended mid-extract left a 3-file release directory that looked usable.

## Solution
- **Before building, collect everything the release must carry.**
  - Run `git log` on origin/main.
  - Ask the peers that use the target robots (ListAgents) about unpushed hotfixes on those robots.
  - Check open approvals, for example Proposed ADRs that change device defaults.
  - Then build once.
- **One apt transaction for rosdep** (`perf/payload-build-one-apt-transaction`).
  - `build-native-payload.sh` runs `rosdep install --simulate`.
  - `rosdep_apt_batch.py` parses the plan and refuses anything that is not a package name.
  - All the packages are installed in a single `apt-get install -y` with rosdep's own flags, so the installed set stays the same. rosdep then runs again and must find nothing left to do.
  - The workflow sets dpkg `force-unsafe-io` and removes the man-db auto-update flag, on the throwaway runner only.
  - Measured: run 36867742962 against 36865620181, same source.

    | | Before | After |
    |---|---|---|
    | "Build native payload tree" | 323 s | 172 s (-47%) |
    | Whole job | 429 s | 289 s (-33%) |

    `ros-packages.txt` (342), `deb-packages.txt` (2524), `required-ros-packages.txt`, `rosy-packages.txt` and `python-runtime.sha256` are identical between the two artifacts.
    The dpkg runner settings did not measurably change the 75-78 s prerequisites step. The gain comes from the single transaction.
- **One command from finished run to signed tarball** (pending on branch `feat/release-prepare-one-command`, as `tools/release/prepare_payload_release.py`).
  - Parallel download (`tools/release/download_artifact.py`).
  - Atomic extract that keeps dotfiles.
  - ABI check against each target robot: `name=version` against TAB-separated dpkg output, with an empty version counted as not installed.
  - Sign, pack, and print the push commands.
- **The calibration guard finds the credential by device hostname** (`fix/calibration-guard-credential-by-hostname`). When `<ip>.credential.xml` is missing, it asks the robot for its hostname over SSH. It never tries another robot's token.

## Why This Works
Build minutes were never the main cost. The cost came from rebuilding after facts that could have been gathered beforehand, and from steps that failed silently. Batching apt removes per-transaction overhead and keeps the package set the same. Scripted checks fail loudly when they compare nothing, and they leave no half-finished directories behind.

## Prevention
- Gather the release's contents, peer hotfixes and pending approvals before `gh workflow run`.
- Never hand-roll a release check in a REPL. Use the tool, whose parser is pinned by a test.
- A safety check that "skips with a warning" is a silent pass. Make the skip say what it looked for, and give it a second way to find its input.
