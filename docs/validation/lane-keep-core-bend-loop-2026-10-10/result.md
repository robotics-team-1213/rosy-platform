# Operational keeper to CORE bend handoff in a host closed loop

2026-10-10. Evidence tier: **host kinematic SIM with the actual `LaneKeeper` and `LineFollowManager`**. This is a continuation of the [keeper-only observation gap](../lane-keep-one-side-closed-loop-2026-10-10/result.md). The [replay](evidence/replay.py) runs both decision modules at 0.2 s ticks on the same rendered 65-degree left-bend floor. It feeds synthetic clear calibrated IR, clear LiDAR points and exact simulated odometry into CORE. It integrates CORE's returned linear and angular decisions to generate the next camera frame. No ROS graph, Fleet service, real camera calibration, robot, or motor publisher is present.

The bend instruction uses the D-507 contract: `map_id=lab-a`, `turn_deg=65`, `bend_radius_m=0.15`, `bend_tol_m=0.12`, and `bend_in_m` from a fillet tangent point in the synthetic map. `bend_expected` stays false in `LaneKeeper` for both runs. The only difference is the valid CORE bend instruction.

| Same scene | Without instruction | With CORE bend instruction |
| --- | ---: | ---: |
| First bend handoff | none | x=0.230 m, CORE `junction_bending` |
| End pose `(x,y,yaw)` | `(0.263, 0.005, 8.7 deg)` | `(0.524, 0.117, 61.6 deg)` |
| End state | zero command, `camera_reselection_required` | bend passed through `reacquiring` to `idle` with paired camera lines |
| Maximum centre-line deviation | 4.6 mm | **21.8 mm** |
| Body rectangle outside the painted-lane interior | 0 ticks | **12 ticks**, first at step 69, x=0.454 m |

The no-instruction run stops before the vertex, reproducing the previous diagnostic. The instructed run crosses the camera observation gap under CORE's bounded odometry pass and hands back to camera tracking. This tests the intended D-507 owner split. The camera itself did not decide to follow a lone bend line.

**Acceptance remains HOLD.** The centre-point deviation reaches 21.8 mm, above a conservative 20.0 mm proxy allowance: 92.5 mm lane half-width minus 12.5 mm paint half-width minus the rig's 60 mm body half-width. A stronger raster check samples the 160 x 120 mm declared body rectangle at 1 mm over the painted corridor on every tick. The instructed path has **12 body-paint contact ticks** (at most 195 sampled body cells on one tick); the first is at x=0.454 m, while the centre is only 10.4 mm off the path. The no-instruction STOP path has zero. This is a body-footprint check at sampled poses, not a continuous swept-body proof. The run also uses exact odometry and clear obstacles. The earlier model-PC ROS-SIM bend run covered one mapped bend with a separate source snapshot; this host run does not replace a current-source ROS-SIM replay, independent map-pose error, wall/fork negatives, ARM64 image verification, or device/field acceptance.

[The sensitivity sweep](evidence/sweep.py) ran the same CORE/keeper loop with initial lateral offsets -20/0/+20 mm and headings -2/0/+2 degrees. With the declared 0.15 m radius and nominal tangent entry, **0/9** starts avoided body-paint contact. An exploratory 0.08 m radius with entry 30 mm earlier avoided contact only at the exact-centred, zero-heading start (**1/9**). All 18 runs reached `idle`, which demonstrates why trip completion is an insufficient safety metric. Neither radius/entry change is a calibrated map correction or an acceptable setting; the next algorithm must account for start-pose uncertainty and the entire body path.

Reproduce from the repository root: `python docs/validation/lane-keep-core-bend-loop-2026-10-10/evidence/replay.py` and `python docs/validation/lane-keep-core-bend-loop-2026-10-10/evidence/sweep.py` (both print JSON). The next measurable change is a continuous swept-body check and a calibrated map bend geometry with uncertainty, followed by repeated noisy closed loops and wall/fork negatives. A candidate may advance only if the boundary margin is positive and wrong-turn cases still STOP. D-475 human-reviewed physical boundary identity for October 7 remains unavailable.
