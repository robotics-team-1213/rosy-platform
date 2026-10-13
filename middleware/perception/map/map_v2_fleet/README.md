# map_v2_fleet (260919)

2.81 x 1.26 m road track. White lane paint on a dark floor (confirmed by the user 2026-09-22) plus a 155 mm perimeter wall.

All generated worlds use a centred 5 x 5 m ground plane, also read by Isaac.
This covers the 3 x 1.5 m floor visuals without changing measured walls or paint.
Native zero-target comparisons found rest-velocity spikes with the previous
100 m ground and none with 5 m at the same starting pose. This is a simulator
ground setting; it does not establish driving, traffic or learning acceptance.

| File | Role |
|---|---|
| `260919 MAP FILE.STL` | CAD source: binary, mm, Y-up. sha256 `cabf17a84175da8be1ef7562054ec598971bbb9378810acb8cee3f686fe1f92b` |
| `scripts/stl_scene.py` | ROS-free parser. Splits the STL into 0.1 mm paint and the 5 mm wall ring (4 boxes). Transform: R_x(+90 deg), mm to m, centred. |
| `scripts/build_world.py` | Writes `worlds/map_v2_fleet.world` and `meshes/road_lines.stl`. Output is byte-deterministic. |
| `maps/map_v2_fleet.{pgm,yaml}` | Nav2 map of the perimeter only, at 5 mm cells (the walls are 5 mm thick). |
| `training-curved/` | Generated training derivative: deeper east S-bend, white 0.30 m wall ring, matching paint mesh and lane graph. |

## Curved training variant

`scripts/build_world.py` also writes `training-curved/`. The east S-bend gets a smooth lateral
offset (up to 39 mm) over x=0.30–1.20 m; the roundabout, junctions, crosswalks, parking,
reference squares and 2.81 x 1.26 m outer rectangle stay in place. The lane graph uses
the same deformation as the paint mesh. Collision and visual wall heights are both 0.30 m.
The existing perimeter occupancy map remains applicable because the wall footprints do not move.

White wall faces and lane paint share the same material brightness. The existing outer paint
is retained, with no artificial dark gap or blue seam tape to make wall/paint separation easier.
The [recorded wall-as-lane failure](../../../../docs/validation/perception-real-video/2026-09-24/p04_0492_wall_ahead_BOTH.jpg)
is a reference for this ambiguity; matching colours alone is not calibrated camera rendering
or proof that perception handles it. The original CAD, measured-map assets and camera profile
remain the physical-map reference. The training derivative is not a replacement for field coordinates.

After building the ROS workspace, select the world and its matching graph together:

```bash
ros2 launch gz_sim map_v2_fleet_real.launch.py map_variant:=training-curved gazebo_gui:=true
```

The normal launch still defaults to the original real-profile map. The variant supplies map assets;
Isaac import, trained policies, signal enforcement and two-robot Fleet completion require separate
integration and runtime validation. The existing simulation CORE overlay has traffic policy disabled.

## Regenerate

```bash
python middleware/perception/map/map_v2_fleet/scripts/build_world.py
python integrations/simulation/gazebo/scripts/world_to_map.py middleware/perception/map/map_v2_fleet/worlds/map_v2_fleet.world \
  -o middleware/perception/map/map_v2_fleet/maps/map_v2_fleet --resolution 0.005 --seed -1.26955,0.24255
```

On Windows, `world_to_map.py` writes the yaml with CRLF. Convert it to LF before committing, because `.gitattributes` expects LF.

## Run (ROS-SIM)

```bash
ros2 launch gz_sim map_v2_fleet_lane.launch.py gazebo_gui:=true
curl -X PUT http://127.0.0.1:8080/api/v1/line-follow/mode -H "Authorization: Bearer rosy-dev-operator" \
  -H "Content-Type: application/json" -d '{"mode": "CAMERA_LINE"}'
```

## Limits

- The four orange/yellow and black diagonal warning patches use the shared
  `caution_markers` definition in `lane_rules.yaml`. `build_world.caution_meshes()`
  supplies the same triangles and colours to all three Gazebo worlds and the
  Isaac native map runner. Generated `meshes/caution_*.stl` are tracked and
  installed with this bundle; regenerate with `scripts/build_world.py`.
  The stronger S-bend remains in `training-curved/` for both simulators.
- Warning positions come from the rectified real overhead recording (D-525
  rev. 5, `paint-7b220d432c2a`), projected onto the CAD spokes by less than
  1.7 cm. Photo centres are retained in the rules. Size is approximately
  15 x 4 cm, position uncertainty +-3 cm; physical measurement is pending.
  They are flat visual fixtures, not physical speed bumps or white stop lines.
  Adding them does not enable a traffic policy or prove a stop/observe action.
  The two white crosswalks and their graph remain unchanged. Actual RGB/mask
  evidence and provenance stay in the ignored `private/isaac` journal.

- Lane paint is visual-only. Nav2 and LiDAR see only the rectangle, which looks the same after a 180 deg turn, so AMCL is ambiguous here. The two floor reference squares (`reference_squares` in `lane_rules.yaml`; red outline, blue fill; A at (-1.26, 0.49), B at (0.86, -0.52)) break that ambiguity once a camera observes one: the rotated layout has no square within 0.4 m of any real one. Coordinates are image-derived, +-3 cm, tape measurement pending (D-395 rev. 1). The sim world draws them as flat visual-only patches.
- The launch uses `edge_left` mode (Gazebo ground only): one full lap around the inner block passes in Gazebo; other routes need junction choices. See `docs/validation/map-v2-fleet-gazebo-2026-09-22/result.md`.
- Orientation vs the physical mat: the Gazebo top view matches the STL under a proper rotation (no mirror). Not yet compared against a photo of the physical mat.
- The traffic policy is DISABLED in `gz_sim/config/map_v2_fleet_core.yaml` until a road scene for this map exists.
