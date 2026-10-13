"""Isolated ROS callback check for same-frame keep debug; sends no motion command."""
import json
import sys
import time
from pathlib import Path

import numpy as np
import rclpy
import yaml
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import String

repo = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(repo / 'middleware/perception'))
sys.path.insert(0, str(repo / 'contracts/foundation'))
from control.line_observer_node import LineObserverNode

profile = repo / 'middleware/apps/device/pinky/profile/config/camera_nominal.yaml'
rclpy.init(args=['--ros-args', '-p', 'camera_lane_mode:=keep',
                 '-p', 'camera_ground_source:=NOMINAL',
                 '-p', 'allow_nominal_ground:=true',
                 '-p', 'require_camera_controls_stable:=false',
                 '-p', 'camera_x_offset_m:=0.03317',
                 '-p', f'nominal_camera_profile_path:={profile}'])
observer = LineObserverNode()
reader = Node('lane_debug_smoke_reader')
received = []
sub = reader.create_subscription(String, 'line/keep_debug',
                                 lambda message: received.append(json.loads(message.data)), 10)
try:
    frame = np.full((240, 320, 3), 100, np.uint8)
    frame[120:220, 65:70] = 220
    frame[120:220, 250:255] = 220
    image = Image()
    image.header.stamp.sec = 100
    image.width, image.height, image.encoding, image.step = 320, 240, 'bgr8', 960
    image.data = frame.tobytes()
    observer._on_camera(image)
    deadline = time.monotonic() + 4
    while not received and time.monotonic() < deadline:
        rclpy.spin_once(reader, timeout_sec=0.2)
    assert received, 'line/keep_debug was not published'
    payload = received[0]
    ground = payload['ground_projection']
    assert payload['stamp'] == 100.0
    assert payload['ground'] == 'NOMINAL'
    nominal = yaml.safe_load(profile.read_text(encoding='utf-8'))
    assert ground == {'height_m': nominal['height_m'], 'pitch_rad': nominal['pitch_rad'],
                      'focal_px': nominal['fx'], 'principal_x': nominal['cx'],
                      'principal_y': nominal['cy'], 'max_range_m': nominal['max_range_m'],
                      'camera_x_offset_m': nominal['x_offset_m']}
    print(json.dumps({'stamp': payload['stamp'], 'ground': payload['ground'],
                      'ground_projection': ground, 'strategy': payload['strategy']}))
finally:
    reader.destroy_subscription(sub)
    reader.destroy_node()
    observer.destroy_node()
    rclpy.shutdown()
