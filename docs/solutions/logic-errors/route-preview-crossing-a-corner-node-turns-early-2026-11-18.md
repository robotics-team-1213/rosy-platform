---
title: A route preview that crosses a corner node turns the robot before the corner
date: 2026-11-18
module: operations/fleet routing/direction.py, middleware/perception drivable_steer and route_guard
problem_type: logic_error
component: navigation
severity: high
symptoms:
  - "Fleet stops a lane trip with reason=pose (off_lane about 0.1 m) 0.2 m before a junction, every run on the same path."
  - "keep_debug shows guide_deg jumping to about -90 while the robot is still on the arriving lane, then a pivot or turn toward that side."
  - "At the node itself the steer reads drivable_closed or recentre_alignment_* and stands until the stall stop."
root_cause: wrong_layer_for_the_decision
resolution_type: code_fix
applies_when:
  - "Changing the route guide (heading_here_deg, heading_ahead_deg, ahead_m) or its lookahead."
  - "Changing the camera steer's pivot, recentre_first or _align rules near junctions."
  - "A sim lap or trip stops at a junction and a steer threshold looks like the cause."
tags: [fleet, route-guide, drivable, junction, corner, d-769, sim-lap]
---

# Decide where a corner turn starts in Fleet, not in the camera steer

## What happened
The v2 map lap (map_v2_fleet, learned model a77bce58) stopped at the NE junction on every run. The route bends left and then turns right by about 107 deg at NE.

Fleet's route guide reports the lane heading 0.25 m ahead. That point crossed the NE node while the robot was still 0.23 m short of it. The camera steer saw a strong right turn with no floor straight ahead, pivoted right there, headed for the ring it could see across the island and left the road.

## What did not work
- **A threshold story:** the first reading blamed the 15 deg exit threshold dropping the turn. Joining odom with lane_graph.yaml showed the real path: the robot turned early and arrived 23 deg misaligned.
- **Three steer-side fixes:** holding the turn longer, or blocking turns while the lane "here" bends the other way. They either failed in the sim or broke the recorded-frame tests (test_drivable_exit_openings, test_drivable_local_floor), where turning with here and ahead opposed is correct.
- **Why:** the camera steer gets only two angles and cannot tell how far the corner is. Fleet has the graph and can.
- **Corners inside one arc:** a chord-based detector (45 deg within 0.05 m) caught the west road's 90 deg bends, but it also took east's tight bend before NE as a corner. Laps then stalled twice on the yellow hatch before NE. It was dropped; those bends still rely on the steer.

## Fix
- **`route_direction`:** a node where the selected lanes turn by CORNER_TURN_DEG (45) or more is a corner. (Bends inside one arc are not: a chord-based in-arc detector was tried and dropped, see below.)
  - The preview shows it only within CORNER_PREVIEW_M (0.15 m). Farther out it holds the heading before the corner, and ahead_m stays the full preview so CORE keeps the guide.
  - Inside that distance the preview ends on the heading leaving the corner. A ring that curves back read only -31 deg 0.25 m past the node, too little for the 45 deg pivot rule.
  - Within CORNER_HERE_M (0.05 m) the lane "here" is the corner's mid direction. The leaving lane itself (103-115 deg on this map) read past 90 deg, which the steer takes as facing against the lane (wrong_way_hold).
- **Camera steer, `at_corner`:** a corner node is when Fleet's here and ahead turn the same way, the larger by 45 to 150 deg, and the camera sees no way straight on (under PIVOT_AHEAD_M). Requiring here itself past 45 deg failed once the robot had turned part way (here -27 deg, ahead -83 deg).
  - There the steer does not recentre on the arriving lane it sees, and route_guard drops an earlier recentre episode.
  - The turn in place there goes on while Fleet's here is past 45 deg even when the corner's leaving heading reads less (SE: -40 deg ahead, -55 here, nothing seen; it stood). Just past the node, part way round, the preview already runs along the new lane (-8 deg), so the turn side comes from the lane here (-68 deg).
  - A "here" past 90 deg there is the route's turn, not wrong_way_hold. A brief line-straddle turn once rotated the robot away at NW and held it.
  - The same angles with the way open ahead are still a misaligned robot (realign), and past 150 deg a reversed one (wrong_way_hold).
  - Frames with here and ahead opposed keep their recentring.
- **Contract:** no change.

## How it was verified
- **Sim, same model (a77bce58):**
  - ring_entry (the original NE failure) passes, and ne_corner and east_nw_turn still pass.
  - Full laps went from always stopping at NE (about 3 m) to one full pass (6.94 m, back within 3 mm of its start). The other laps reach NW, SW or SE (6.0-6.2 m).
- **Evidence:** D:/DevTemp/sim-fleet-1118/v4-* to v17-*, and the workspace record 2026-11-18 lane-model-field-test-plan.
- **Regression tests:**
  - test_route_direction: corner preview distance, leaving heading, here at the node.
  - test_drivable_steer: corner node frames, plus the misaligned and reversed robots that must still hold.
  - test_observed_recentre_alignment: a leftover episode at a corner.
- **Not solved:** laps still stall at SE/NW when the corner flag flickers across 45 deg mid-turn, and at NE's yellow hatch, where the model sees no floor. Real Pinky not tested; a sim pass is not a real-robot pass.

## Next time
- **Read the path first:** before blaming a steer threshold for a junction stop, join odom with lane_graph.yaml along the planned arcs. Look at where the robot was relative to the node when guide_deg changed.
- **Where to change it:** decisions that need distance to a graph node belong in Fleet's route guide, not in the camera steer.
