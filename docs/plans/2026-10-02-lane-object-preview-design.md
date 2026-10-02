# Visible lane and object evidence

Scope: explain lane/path following and surrounding camera regions. The operator authorized implementation, commit, merge, and robot release; with the robot powered off, validation proceeds in Gazebo. This extends `follow-road-v2` without changing motion authority or lane selection.

## Camera display

- Selected boundaries are explicitly labelled LEFT LANE and RIGHT LANE. Missing selected boundaries say UNSEEN. A magenta FOLLOW PATH ends at the keeper's selected target; it is a target guide, not a motor trajectory or prediction.
- Only neighbouring boundaries with overlapping observed spans, compatible headings, and 75–125% of configured lane width form visible lane candidates. Fragment/double-edge duplicates are collapsed. The keeper's actual selected pair is highlighted as CURRENT LANE; adjacent candidates remain faint. Candidate count is local to this frame, not the total road lane count. Junctions, occlusion and unseen lanes remain uncertain. Candidates do not initiate lane changes.
- Foreground regions show OBJ plus UNKNOWN/DARK, distance only when measured, and the existing NEAR flag. Numbers are frame-local annotation indices, not tracked identities. ArUco DICT_4X4_50 markers show their actual TAG ID and corners. A tag alone does not establish robot/dock identity or metric pose.
- The existing same-stamp cache and calibrated road-state prediction gates remain. STOP hides prediction. Image dimensions and camera coordinates remain unchanged.

The console camera panel provides 영상 확대 through native fullscreen, keyboard/focus return on exit, and a collapsed 차선·객체 표시 읽는 법 legend. Expansion stays disabled until a frame is available.

## Authority and validation

`line/keep_debug` gains explanatory selected/width/geometry-source metadata. The motion observation serializer's ground enum remains unchanged; GAZEBO provenance is carried only in the debug bundle. Observers publish no motion.

Validate boundary pairing, missing/ambiguous observations, marker pixels, invalid images, same-frame rendering and observer wiring on the host. Validate real browser fullscreen, waiting-state copy, legend and viewport overflow. Exercise a declared wide Gazebo camera with parallel lane paint, an unknown box and a tag. Simulator geometry is not physical camera calibration. Full CI, native artifact build, device installation and field acceptance remain separate gates.
