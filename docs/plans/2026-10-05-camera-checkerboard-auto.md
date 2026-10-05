# Checkerboard Camera Auto Calibration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Automatically fit and compare camera geometry from the user's 17mm checkerboard at two positions, without hand-entering camera height or pitch.

**Architecture:** A PC-only image processor finds a contiguous grid, solves both planar poses and rejects ambiguous/high-error results. It rectifies the second image using the first pose to improve corner detection, maps those corners back to the original pixels, and fits again. It retains the provenance of seeded intrinsics and distinguishes height above the board from height above the floor.

**Tech Stack:** Python, NumPy, OpenCV, YAML camera profile; no ROS, motion or runtime writes.

## Steps

1. Add `tools/calibration/camera_board.py` and synthetic projection regression tests in `tools/calibration/test/test_camera_board.py` for metric scale, planar ambiguity, reprojection error, cross-view disagreement, and unknown board thickness.
2. Detect both direct and rectified grids; use original pixel coordinates for the fit. Avoid treating rectified detection alone as validation.
3. Implement a CLI using the existing camera profile and declared printed square size. Output a new candidate JSON under Windows X:/DevTemp; do not overwrite previous evidence.
4. Run the user's actual 10cm and 20cm images, independently review numeric results, and record candidate quality separately from runtime acceptance.
5. Preserve D-47 application and rollback, D-344 NOMINAL lease and CORE stop guards. No automatic promotion from seeded intrinsics or unknown floor height.

## Current observations

10cm view yields 20 corners with about 0.615px RMS; conditional camera-to-board height 53.7mm and pitch 12.2 degrees. Direct 20cm detection is poor. Rectification improves it to 54 corners and about 0.283px RMS, height 54.0mm and pitch 12.1 degrees. The operator estimated board thickness at 1mm: floor height is approximately 54.908mm, explicitly an estimate. No runtime apply. Intrinsic fy is assumed equal to the profile fx; it is not newly calibrated.
