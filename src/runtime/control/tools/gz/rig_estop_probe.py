"""E-stop negative case for the isolated calibration rig (D-171 rule d).

Watches /calibration/status and presses /estop/cmd 'stop' the first time the
calibration enters its motion trial. The rig's verdict then requires the
calibration to end failed, never ready. Records what it did in
<out>/estop_probe.json. Simulation domain 227 only; never motor output.
"""
import json
import os
import sys
import time
from pathlib import Path

if os.environ.get('ROS_DOMAIN_ID') != '227':
    raise RuntimeError('Isolated simulation domain required')

import rclpy
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String

TRIAL_PHASES = ('validating_motion', 'validating_rotation')


def main():
    out = Path(sys.argv[1])
    rclpy.init()
    node = rclpy.create_node('rig_estop_probe')
    estop = node.create_publisher(String, 'estop/cmd', 10)
    record = {'pressed': False, 'phase_at_press': None, 'phases_seen': []}
    latched = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                         durability=DurabilityPolicy.TRANSIENT_LOCAL)

    def on_status(msg):
        try:
            phase = json.loads(msg.data).get('phase')
        except (ValueError, AttributeError):
            return
        if not record['phases_seen'] or record['phases_seen'][-1] != phase:
            record['phases_seen'].append(phase)
        if not record['pressed'] and phase in TRIAL_PHASES:
            estop.publish(String(data='stop'))
            record.update(pressed=True, phase_at_press=phase, pressed_wall_s=time.time())
            print(f'estop pressed during {phase}', flush=True)
        (out/'estop_probe.json').write_text(json.dumps(record))

    node.create_subscription(String, '/calibration/status', on_status, latched)
    (out/'estop_probe.json').write_text(json.dumps(record))
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        (out/'estop_probe.json').write_text(json.dumps(record))
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
