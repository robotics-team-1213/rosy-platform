# Checkerboard camera pose candidate — 2026-10-05

Actual stationary camera images were captured with the board placed first 10 cm,
then 20 cm in front of the robot. The operator declared 17 mm printed squares,
confirmed a board lying on the floor, and estimated its thickness at approximately
1 mm. Thickness was not measured. The ruler was removed for the second image.

The PC tool detected 20 reference corners directly and 54 validation corners after
rectification. Both poses were fitted and checked against original image pixels:
reference RMS 0.612 px, maximum 1.350 px; validation RMS 0.281 px, maximum 0.782 px.
The heights differ by 0.338 mm, pitch by 0.111 degrees and roll by 1.013 degrees.
The cross-view consistency checks pass.

Mean height above the board is 53.908 mm and downward pitch is 12.117 degrees.
Adding the operator's approximate 1 mm board thickness gives an **estimated** floor
height of 54.908 mm. This is conditional on a flat board and the existing camera
intrinsics: fx=281.6 px and fy assumed equal to fx, at 320 by 240 resolution. These
images do not constitute a new intrinsic or distortion calibration. Pose agreement
does not eliminate shared intrinsic or scale errors.

The result remains `status: candidate`, `applied: false`. No runtime configuration,
calibration-store acceptance, motion mode or safety guard was changed. Camera
capture evidence recorded zero motion commands. Automatic lane driving has not
passed: the separate installed-release trial held at
`nominal_ground_requires_driver` and was returned to OFF.

Local receipts: `X:/DevTemp/line-remote-20261005/camera-board-device.json` (unknown
thickness) and `camera-board-device-1mm.json` (operator-estimated thickness).
These are local evidence, not CI or field acceptance.

Related host verification: 95 tests passed, 0 NEW against `test/known_failures.py`.
Regression cases include upward pitch rejection, invalid intrinsics, bad corners,
unknown thickness and disagreement between independent views. The final receipt
contains input-image/profile SHA256 values and the actual seeded camera matrix.
The earlier camera-auto push failed its normal gate with five NEW failures; this
record does not claim that push succeeded.
