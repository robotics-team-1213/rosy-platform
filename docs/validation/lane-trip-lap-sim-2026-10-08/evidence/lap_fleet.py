#!/usr/bin/env python3
"""D-507 B13 lap SIM: the real Fleet server (create_app, TripRunner, HttpLaneJunction) for one SIM robot.

Model PC only. Two SIM stand-ins, nothing else:
1. Map pose: the trip loop's MapPosePort is Gazebo ground truth (d495/gt), LOCALIZED, age = time
   since the last message. Real map-pose error (sighting anchor + odom bridge) is not covered.
2. Plan pose: POST /trip reads ``console.trusted_map_pose`` (the robot snapshot's localization);
   the SIM CORE has no map localization, so the robot client's ``state()`` gets the same ground
   truth as ``pose`` with ``localization {LOCALIZED, map}``. ``line_follow`` and the rest of the
   snapshot are CORE's own.
Site map: lane_graph map_v2_fleet + the SW bend place of the bend-odom SIM (r 0.15 m).
  python3 lap_fleet.py --core http://127.0.0.1:8188 --port 8189 --db runs/fleet.sqlite3
"""
import argparse
import asyncio
import hashlib
import json
import math
import sys
import threading
import time
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
# D-601 B: the shared SIM Fleet site config (lane_camera_check false: no front preview in SIM).
SIM_SITE = REPO/'integrations/simulation/gazebo/config/fleet_sim_camera_site.yaml'
sys.path[:0] = [str(REPO/'operations/fleet'), str(REPO/'contracts/foundation')]
from fleet.localization.map_pose import MapPose  # noqa: E402
from fleet.server.app import create_app  # noqa: E402
from fleet.server.console import FleetConsole  # noqa: E402
from fleet.server.site_map_store import SiteMapStore  # noqa: E402
from fleet.server.task_service import FleetTaskService  # noqa: E402
from fleet.server.trip_ports import HttpLaneJunction, TripConfig  # noqa: E402
from fleet.server.task_store import FleetTaskStore  # noqa: E402
from fleet.site_map import SiteMap, SitePlace, from_lane_graph  # noqa: E402
from fleet.swarm.robots import RobotEndpoint  # noqa: E402
from fleet.swarm.transport import HttpRobotClient  # noqa: E402

MAP_ID = 'map_v2_fleet'
ROBOT = 'rosy_sim'
OPERATOR_TOKEN = 'lap-operator'
#: bend-odom SIM final place (lane-bend-odom-sim-2026-10-08): vertex on lane_graph west, r 0.15.
SW_BEND = dict(id='B_SW', name='SW bend', kind='bend', x=-0.6924, y=-0.5091,
               yaw=math.radians(63.58-180), exit_yaw=math.pi, radius_m=0.15)


class GroundTruth:
    """d495/gt (Pose2D, world = map frame) from an rclpy thread."""

    def __init__(self):
        import rclpy
        from geometry_msgs.msg import Pose2D
        rclpy.init()
        self.node = rclpy.create_node('lap_fleet_gt')
        self.pose, self.at = None, None
        self.node.create_subscription(Pose2D, 'd495/gt', self._on, 10)
        threading.Thread(target=rclpy.spin, args=(self.node,), daemon=True).start()

    def _on(self, m):
        self.pose, self.at = (m.x, m.y, m.theta), time.monotonic()

    def age(self):
        return None if self.at is None else time.monotonic()-self.at

    # MapPosePort
    def arbitrated_pose(self, robot_id):
        if self.pose is None or robot_id != ROBOT:
            return None
        age = self.age()
        x, y, yaw = self.pose
        state = 'LOCALIZED' if age < 1.0 else 'DEGRADED'
        return MapPose(x, y, yaw, state, 'sim_ground_truth', 0.0, age, anchor_age_s=age, map_id=MAP_ID)

    async def refresh(self, robot_id, *, force_rest=False):
        return None


class SimClient(HttpRobotClient):
    """CORE's snapshot with the SIM ground truth as its map pose (plan input only)."""

    def __init__(self, endpoint, gt):
        super().__init__(endpoint)
        self._gt = gt

    async def state(self):
        state = await super().state()
        if self._gt.pose is not None and self._gt.age() < 1.0:
            x, y, yaw = self._gt.pose
            state['pose'] = {'x': x, 'y': y, 'yaw': yaw}
            state['localization'] = {'state': 'LOCALIZED', 'pose_frame': 'map', 'confidence': 1.0}
        return state


class LoggedJunction(HttpLaneJunction):
    """Fleet's own junction port; every instruction and CORE's answer go to sends.jsonl (evidence only)."""

    def __init__(self, clients, gt, path):
        super().__init__(clients)
        self._gt, self._out = gt, open(path, 'a')

    async def send_junction(self, robot_id, action, place_id, stop_after_m, expires_s, **kw):
        row = {'wall': time.time(), 'gt': self._gt.pose, 'action': action, 'place_id': place_id,
               'stop_after_m': stop_after_m, 'expires_s': expires_s, **kw}
        try:
            reply = await super().send_junction(robot_id, action, place_id, stop_after_m, expires_s, **kw)
            row['reply'] = reply
            return reply
        except Exception as exc:
            row['error'] = f'{type(exc).__name__}: {getattr(exc, "code", "")} {exc}'
            raise
        finally:
            self._out.write(json.dumps(row)+'\n')
            self._out.flush()

    async def hold(self, robot_id):
        reply = await super().hold(robot_id)
        self._out.write(json.dumps({'wall': time.time(), 'gt': self._gt.pose, 'action': 'HOLD(mode OFF)'})+'\n')
        self._out.flush()
        return reply


def site_map():
    base = from_lane_graph(REPO/'middleware/perception/map/map_v2_fleet/lane_graph.yaml', map_id=MAP_ID)
    return SiteMap(map_id=MAP_ID, places=[*base.places, SitePlace(**SW_BEND)], edges=base.edges)


def main():
    import uvicorn
    ap = argparse.ArgumentParser()
    ap.add_argument('--core', default='http://127.0.0.1:8188')
    ap.add_argument('--core-token', default='rosy-dev-operator')
    ap.add_argument('--port', type=int, default=8189)
    ap.add_argument('--db', required=True)
    ap.add_argument('--sends', required=True)
    a = ap.parse_args()
    gt = GroundTruth()
    endpoint = RobotEndpoint(ROBOT, a.core, a.core_token)
    console = FleetConsole([endpoint], [SimClient(endpoint, gt)])
    store = SiteMapStore(Path(a.db))
    store.import_if_empty(site_map(), source='lap_fleet.py')
    users = {hashlib.sha256(OPERATOR_TOKEN.encode()).hexdigest(): {'principal_id': 'lapsim', 'role': 'operator'}}
    tasks = FleetTaskService(FleetTaskStore(Path(a.db)), robot_ids={ROBOT})  # site auth needs the audit store
    app = create_app(console, task_service=tasks, site_users=users, site_maps=store, map_pose_port=gt,
                     lane_junction=LoggedJunction(console.clients, gt, a.sends),
                     trip_config=TripConfig.from_mapping(yaml.safe_load(SIM_SITE.read_text())['fleet']['trip']))
    asyncio.run(uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=a.port, log_level='warning')).serve())


if __name__ == '__main__':
    main()
