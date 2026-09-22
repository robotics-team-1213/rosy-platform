# map_v2_fleet (260919)

2.81 x 1.26 m road track. White lane paint on a dark floor (confirmed by the user 2026-09-22) plus a 155 mm perimeter wall.

| File | Role |
|---|---|
| `260919 MAP FILE.STL` | CAD source: binary, mm, Y-up. sha256 `cabf17a84175da8be1ef7562054ec598971bbb9378810acb8cee3f686fe1f92b` |
| `scripts/stl_scene.py` | ROS-free parser. Splits the STL into 0.1 mm paint and the 5 mm wall ring (4 boxes). Transform: R_x(+90 deg), mm to m, centred. |
| `scripts/build_world.py` | Writes `worlds/map_v2_fleet.world` and `meshes/road_lines.stl`. Output is byte-deterministic. |
| `maps/map_v2_fleet.{pgm,yaml}` | Nav2 map of the perimeter only, at 5 mm cells (the walls are 5 mm thick). |

## Regenerate

```bash
python src/apps/control/map/map_v2_fleet/scripts/build_world.py
python src/sim/gz_sim/scripts/world_to_map.py src/apps/control/map/map_v2_fleet/worlds/map_v2_fleet.world \
  -o src/apps/control/map/map_v2_fleet/maps/map_v2_fleet --resolution 0.005 --seed -1.26955,0.24255
```

On Windows, `world_to_map.py` writes the yaml with CRLF. Convert it to LF before committing, because `.gitattributes` expects LF.

## Run (ROS-SIM)

```bash
ros2 launch gz_sim map_v2_fleet_lane.launch.py gazebo_gui:=true
curl -X PUT http://127.0.0.1:8080/api/v1/line-follow/mode -H "Authorization: Bearer rosy-dev-operator" \
  -H "Content-Type: application/json" -d '{"mode": "CAMERA_LINE"}'
```

## Limits

- Lane paint is visual-only. Nav2 and LiDAR see only the rectangle, which looks the same after a 180 deg turn, so AMCL is ambiguous here.
- The camera detector follows a single line, not the lane between two lines. See `docs/validation/map-v2-fleet-gazebo-2026-09-22/result.md`.
- Orientation vs the physical mat: the Gazebo top view matches the STL under a proper rotation (no mirror). Not yet compared against a photo of the physical mat.
- The traffic policy is DISABLED in `gz_sim/config/map_v2_fleet_core.yaml` until a road scene for this map exists.
