# Camera Auto Calibration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the camera guide's hand-measured input workflow with automatic stationary camera/LiDAR capture and fitting.

**Architecture:** A developer CLI sends a read-only capture worker through an approved pinned SSH alias. The worker reuses the installed camera fitter, checks stationary odometry and sensor freshness, and returns a candidate with the existing quality verdict. It publishes no command, changes no mode, and does not promote an unobservable candidate into a calibrated runtime.

**Tech Stack:** Python, OpenSSH, ROS 2 Jazzy subscriptions, installed NumPy camera fitter.

## Scope

The user clarified that camera calibration is the target. The generic D-321 calibration-session fence protects other calibration work and is not a separate manual camera-calculation mode. Preserve that fence. Camera numeric measurement instructions are replaced by an automatic command; other sensors and generic manual driving are outside this change.

## Task 1: Automatic capture command

- Create `tools/calibration/camera_auto.py` and its read-only capture worker `tools/calibration/camera_capture.py`.
- Test `tools/calibration/test/test_camera_auto.py`: stale odometry, moving/drifting robot, bad topic identity, weak fit, and no automatic promotion; verify output/exit code and pinned SSH options.
- Read immutable geometry from the installed URDF-derived profile. Report nominal LiDAR mount provenance; do not silently claim it measured.
- Keep import-time dependencies ROS-free so host tests exercise the guards.
- Save evidence under the caller's output directory, which on this Windows workspace must be X:/DevTemp.

## Task 2: Replace camera manual-measurement guide

- Rewrite `middleware/perception/docs/camera-ground-calibration.md` around the automatic command, its quality verdict and repeatable view requirements.
- Do not promise height observability from one image. Report `height_source: base` honestly.
- Explain that a calibration candidate does not remove the NOMINAL driver lease or establish FIELD acceptance.

## Task 3: Verification and real-device receipt

- Run `python -m pytest tools/calibration/test -q -rfE -p no:cacheprovider`, save UTF-8 output and compare with `test/known_failures.py`.
- Run public provenance tests and harness generate/lint.
- Execute stationary capture on 9dfk; leave runtime settings untouched if fit quality rejects it.
- Independently review the command, guards and receipt before committing and landing. Do not claim automatic driving success.

## Observed baseline

042 stationary prototype: 40 scans, 15 frames, 121 odometry samples, no motion/drift/freshness faults. The installed fitter reports five wall returns, `recommended: false`, `height_source: base`, and `too few wall returns in view`. No motion command was published. This is a real automatic calculation, not a validated camera calibration.
