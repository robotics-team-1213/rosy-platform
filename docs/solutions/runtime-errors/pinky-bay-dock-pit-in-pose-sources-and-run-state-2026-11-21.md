---
title: Pinky bay dock - judge every check on the pose source that is right for it, bind turn zones to absolute geometry, and reset run state per dock
date: 2026-11-21
last_updated: 2026-11-21
category: runtime-errors
module: middleware/drive/behaviors/docking (bay_zone.py, bay_zone_phases.py, bay_centre.py, bay_zone_checks.py, site_pose.py)
problem_type: runtime_error
component: docking_and_navigation
symptoms:
  - "A robot standing straight in its bay lane 0.21 m out was refused: 'the body (with the tray) overlaps a neighbour lane', although its LiDAR pose was 7 mm / 0.4 deg off the axis."
  - "A nose-in robot 0.26 m inside its lane started an in-place turn inside the bay row instead of backing out."
  - "The dock right after a successful pit-in dock skipped the zone check and queued a Nav2 staging goal; no 'bay zone verdict' journal line."
  - "After a correct back-out to the junction the verdict was 'acquire where it stands [scan pose: never requested]' and the dock stopped."
root_cause: logic_error
resolution_type: code_fix
severity: high
tags: [pinky-pro, docking, bay, lidar, pit-in, state-machine, review-process]
---

# Pinky bay dock - pose sources, absolute turn zone, per-dock run state

## Problem

The bay dock has three pose sources that disagree at this site: the camera guide line (lateral good to about 1 cm,
heading wrong by 6 to 25 deg near the bays, cannot tell which bay), the SLAM map (origin resets when CORE restarts,
and `map_epoch` does not notice when the map id is unchanged), and the LiDAR fit against a reference scan taught
with the robot seated (right when it passes its gates, but the bays look alike so the fit weakens with distance:
inliers 0.76 at 0.25 m, 0.70 at 0.32 m, 0.68 at 0.41 m nose-in). On 2026-11-21 one robot in bay C2 showed five
separate failures while the in-bay re-dock was widened to 20 cm and the pit-in (arrival from outside) was built.

## Symptoms

- 20 cm out, straight, refused "overlaps a neighbour lane". The zone verdict had used the LiDAR pose, but the
  acquire window and the footprint check were still computed from the camera lateral and heading.
- Arrival 13.5 deg short of facing the bay: the staging turn turned a fixed 180 deg, ended 13 deg skewed, the
  reverse drifted 4 cm and the lane footprint guard stopped it.
- Nose-in at 0.257 m: an in-place turn started inside the row. The junction rule was `|x - staging_offset_m| <= 0.12`
  and both panels had assumed the staging offset was about 0.40 m. The live dock type had 0.32 m, so 0.20 to 0.44 m
  counted as "the junction". The reviewer had made approval conditional on checking that value and approved
  without checking it.
- The next dock after a pit-in success went straight to Nav2 staging. `_pit_in` set `_zone_checked = True` and
  nothing consumed it, so the following dock's `zone_entry()` cleared it and skipped the zone check.
- After the back-out, a late answer to the last tracked-pose request (dropped by the track gate, so `None`) was
  stored as the zone answer by a bare `else` in `note_scan_match`. The zone wait ended with no pose and
  `classify()` ran on the camera and the map.

## Solution

All in `middleware/drive/behaviors/docking` (PRs #355 and #370):

1. When a LiDAR pose is used for a verdict, every check of that verdict (window, footprint) uses the LiDAR lateral
   and heading. The camera only has to agree within the unchanged gates.
2. The turn amount is the LiDAR bay heading, not a constant; a LiDAR pose is mandatory after a pit-in turn.
3. The zone where an in-place turn is allowed is absolute geometry (`bay_turn_x_min_m` 0.38, target 0.40, max 0.45),
   independent of the dock type's `staging_offset_m`. A nose-in robot below the floor only backs out along its lane,
   on a pose tracked from the accepted start with per-step and cumulative bounds.
4. `new_dock()` resets all bay run state at dock start, and cancel, fail and DOCKED clear it.
5. Only an answer of kind "zone" may become the zone answer; a reference-scan dock issues no verdict before the
   LiDAR pose was asked for; "acquire", "exit" and forward moves are impossible while the last LiDAR heading faces
   the bay.
6. A reference-scan dock never stages on the map unless the site pose is verified by evidence in the request
   (`site_pose_evidence`, judged in `site_pose.py`); otherwise it refuses and raises `docking.person_call`.

Verified on the robot: 5 consecutive DOCKED on the last two heads (1 junction-facing start, 4 nose-in starts at
about 0.25 m; 32 to 37 s; seat within 2 mm), plus the 20 cm and 10 cm in-bay re-docks. One robot, one bay.
Not verified on a robot: skewed or offset arrivals, the centring shuttle and the over-edge reseat allowance (both
shipped default off), occupied-bay refusal, other bays and robots, a real Nav2 arrival.

## Prevention

- **One verdict, one pose source.** If a check sits behind "LiDAR pose used", read every operand from the LiDAR
  pose. A mixed verdict passes the tests that feed consistent values and fails on the robot.
- **Read live configuration before reasoning about geometry.** `GET /docking/types` on the robot, not the code
  default and not a remembered number. A review that is conditional on a value is not an approval until the value
  is read. The reviewer brief now asks for every use of a config value evaluated with the live values.
- **Turn and motion zones are absolute.** A band relative to a per-type offset silently moves when the type changes.
- **Every dock starts from reset state.** When adding a flag to a mixin, add it to `new_dock()` in the same change
  and test "dock, cancel, dock" and "dock, succeed, dock". A first run that passes proves nothing about the second.
- **Asynchronous answers carry their kind.** A handler must ignore kinds it does not own; a bare `else` that stores
  an answer is a race waiting for a late reply.
- **Evaluate with stop bounds.** Every bench run used an evaluator script that cancels on reviewer-given bounds
  (wrong first verdict, a turn below the floor, motion toward the bay, a staging phase, a retry). Three of the
  failures above were stopped by those bounds before anything touched.
- **One success is not a result.** The pit-in docked once and failed on the next identical start twice. Count a
  fix only after consecutive runs from a freshly prepared start.
- Thresholds added here are provisional (junction fit 0.60 / 0.12, front-gap tolerance, tracking bounds, site-pose
  15 s / 0.08 m). The last run had junction margin 0.15 against the 0.12 gate. Measure the C1 / C2 / C3 matrix with
  two robots before trusting them elsewhere.

Related: [pinky-multi-bay-lidar-corridor-and-rail-entry-2026-11-12](pinky-multi-bay-lidar-corridor-and-rail-entry-2026-11-12.md).
