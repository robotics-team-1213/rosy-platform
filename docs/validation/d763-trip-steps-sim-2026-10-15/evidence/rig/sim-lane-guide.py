"""SIM stand-in for the missing line/lane_guide producer (D-511 rev 2 route prior).

Route: the lap's lane-graph arcs in order. Guide: lane direction here and 0.25 m ahead minus the
robot heading (deg, left +), map distance to the route and route progress. Pose: SIM odom (world).
"""
import json, math, sys
import yaml, rclpy
from nav_msgs.msg import Odometry
from std_msgs.msg import String

GRAPH, ROUTE = sys.argv[1], sys.argv[2].split(',')
AHEAD_M, STEP = 0.25, 3
segments = yaml.safe_load(open(GRAPH))['segments']
points = []
for arc in ROUTE:
    name, way = arc.split(':')
    pts = segments[name]['points']
    pts = pts if way == 'fwd' else pts[::-1]
    points += pts if not points else pts[1:]
S = [0.0]
for a, b in zip(points, points[1:]):
    S.append(S[-1] + math.dist(a, b))

def tangent(i):
    a, b = points[max(0, i - STEP)], points[min(len(points) - 1, i + STEP)]
    return math.atan2(b[1] - a[1], b[0] - a[0])

def wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi

rclpy.init()
node = rclpy.create_node('sim_lane_guide')
pub = node.create_publisher(String, 'line/lane_guide', 10)
state = {'i': 0}

def on_odom(msg):
    p, q = msg.pose.pose.position, msg.pose.pose.orientation
    yaw = math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))
    lo = state['i']
    hi = min(len(points), lo + 60)  # 0.6 m of route: progress never jumps to another arc
    i = min(range(lo, hi), key=lambda k: math.dist(points[k], (p.x, p.y)))
    state['i'] = i
    j = i
    while j < len(points) - 1 and S[j] - S[i] < AHEAD_M:
        j += 1
    stamp = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
    pub.publish(String(data=json.dumps(dict(
        heading_ahead_deg=round(math.degrees(wrap(tangent(j) - yaw)), 1),
        heading_here_deg=round(math.degrees(wrap(tangent(i) - yaw)), 1),
        stamp=stamp, pivot_ok=True, off_route_m=round(math.dist(points[i], (p.x, p.y)), 3),
        s=round(S[i], 3)))))

node.create_subscription(Odometry, 'odom', on_odom, 10)
rclpy.spin(node)
