#!/usr/bin/env python3
import json
import math
import sys
import time
from pathlib import Path
import rclpy
from geometry_msgs.msg import Pose2D
from std_msgs.msg import String
from sensor_msgs.msg import Image

sys.path.insert(0, '/home/rosy/rosy-ml/scratch/lane-route-gap-live-20261009/src/rosy-platform/docs/validation/d495-junction-sim-2026-10-07/evidence')
from d495_sim_probe import gz

rclpy.init()
n = rclpy.create_node('route_offmap_realimage_probe')
latest = {'gt':None, 'frame':None, 'camera':None}
rows=[]

def gt(m): latest['gt']=[m.x,m.y,m.theta]
def frame(m): latest['frame']=[m.header.stamp.sec,m.header.stamp.nanosec,m.width,m.height]
def line(m):
    d=json.loads(m.data)
    if d.get('source')=='CAMERA_LINE':
        latest['camera']=d
        rows.append({'gt':latest['gt'], 'frame':latest['frame'], 'obs':d})

n.create_subscription(Pose2D,'d495/gt',gt,10)
n.create_subscription(Image,'camera/front',frame,10)
n.create_subscription(String,'line/observation',line,50)

def spin(seconds):
    end=time.monotonic()+seconds
    while time.monotonic()<end: rclpy.spin_once(n,timeout_sec=.1)

def move(y):
    yaw=0
    payload=f'name: "rosy", position: {{x: -1.15, y: {y}, z: 0.01}}, orientation: {{z: {math.sin(yaw/2)}, w: {math.cos(yaw/2)}}}'
    reply=gz('set_pose','gz.msgs.Pose',payload)
    if not reply: raise RuntimeError('set_pose failed')

out={}
for name,y in [('on_route',-.511),('off_route_80mm',-.431),('return_to_route',-.511)]:
    move(y)
    rows.clear()
    spin(3.0)
    camera=[r for r in rows if r['gt'] is not None and abs(r['gt'][1]-y)<.012]
    out[name]={'rows':len(camera),'first':camera[0] if camera else None,
               'last':camera[-1] if camera else None}
Path('/home/rosy/rosy-ml/scratch/lane-route-gap-live-20261009/offmap_probe.json').write_text(json.dumps(out,indent=2))
print(json.dumps({name:{'rows':v['rows'],'last_gt':v['last'] and v['last']['gt'],
                         'last_obs':v['last'] and v['last']['obs']} for name,v in out.items()}))
n.destroy_node(); rclpy.shutdown()