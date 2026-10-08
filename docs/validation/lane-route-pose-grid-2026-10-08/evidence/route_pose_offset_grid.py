import json, math, sys
from pathlib import Path
import lane_scenarios as s
from lane_sim import CAM_X
from control.sensing.perception.route_camera import RouteCameraFollower
scenario = dict(s.SCENARIOS[11], start=(-1.15, -0.511, 0.0))
rows = []
for lateral in (-0.04, -0.02, 0.0, 0.02, 0.04):
    for yaw_deg in (-5, -3, -1, 0, 1, 3, 5):
        error = s.OdomError(start_offset_lateral_m=lateral, start_offset_yaw_rad=math.radians(yaw_deg))
        follower = RouteCameraFollower(s.GRAPH, [scenario['into'], scenario['out']], start_pose=s.believed_start(scenario, error), camera_x_offset_m=CAM_X)
        result = s.run_scenario(scenario, follower, steps=300, odom_error=error)
        track = result['track']
        rows.append({'lateral_mm': round(lateral*1000), 'yaw_deg': yaw_deg, 'distance_m': round(sum(math.dist(a,b) for a,b in zip(track,track[1:])), 4), 'max_centre_dev_mm': round(float(result['max_centre_dev_m'])*1000, 1), 'reached_end': bool(result['reached_end']), 'branch_ok': bool(result['branch_ok']), 'wrong_way': bool(result['wrong_way']), 'reason': result['reason']})
out = Path(sys.argv[1]); out.write_text(json.dumps(rows, indent=2), encoding='utf-8')
print(json.dumps(rows, indent=2))
