import json, math, sys
from pathlib import Path
import lane_scenarios as s
from lane_sim import CAM_X
from control.sensing.perception.route_camera import RouteCameraFollower

scenario = dict(s.SCENARIOS[11], start=(-1.15, -0.511, 0.0))
rows = []
for offset in (0.0, 0.02, -0.02, 0.04, -0.04, 0.08, -0.08):
    error = s.OdomError(start_offset_lateral_m=offset)
    follower = RouteCameraFollower(s.GRAPH, [scenario["into"], scenario["out"]],
        start_pose=s.believed_start(scenario, error), camera_x_offset_m=CAM_X)
    result = s.run_scenario(scenario, follower, steps=300, odom_error=error)
    track = result["track"]
    distance = sum(math.dist(a, b) for a, b in zip(track, track[1:]))
    rows.append({"offset_m": offset, "start_map_pose": list(s.believed_start(scenario, error)),
        "distance_m": round(distance,4), "max_centre_dev_m": round(float(result["max_centre_dev_m"]),4),
        "reached_end": bool(result["reached_end"]), "branch_ok": bool(result["branch_ok"]),
        "wrong_way": bool(result["wrong_way"]), "reason": result["reason"],
        "final_pose": [round(float(v),4) for v in result["final_pose"]],
        "tiers": {k: result["tiers"].count(k) for k in sorted(set(result["tiers"]))}})
out = Path(sys.argv[1])
out.write_text(json.dumps({"source_sha": sys.argv[2], "rows": rows}, indent=2), encoding="utf-8")
print(json.dumps(rows, indent=2))
