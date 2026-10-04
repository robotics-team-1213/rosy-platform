"""Measure /safety/decision arrival in the isolated rig (domain 227); never publishes.

Writes a running summary to /tmp/pinky-calmap227/decision_probe.json: message
count, inter-arrival gaps (max, count over 0.25 s), decision age on this node's
clock (min, max, count outside the calibration trial's -0.1..0.25 s window),
payloads missing a field the trial reads, and counts per decision reason.
"""
import json
import os
import sys
from pathlib import Path

if os.environ.get('ROS_DOMAIN_ID') != '227':
    raise RuntimeError('Isolated simulation domain required')

import rclpy
from rclpy.parameter import Parameter
from std_msgs.msg import String

OUT = Path('/tmp/pinky-calmap227/decision_probe.json')


def main():
    rclpy.init()
    node = rclpy.create_node('rig_decision_probe')
    node.set_parameters([Parameter('use_sim_time', value=True)])
    state = {'count': 0, 'max_gap': 0.0, 'gaps_over_250ms': 0, 'last': None, 'first': None,
             'worst_at': None, 'reasons': {},
             # Age as the calibration trial measures it: receiver clock - issued_s.
             # It rejects anything outside -0.1 .. 0.25 s, so clock skew alone can
             # starve the trial even when every decision arrives on time.
             'min_age': None, 'max_age': None, 'ages_outside_window': 0, 'missing_fields': 0}

    def on_decision(msg):
        try:
            value = json.loads(msg.data)
            issued = float(value['issued_s'])
        except (ValueError, TypeError, KeyError):
            return
        state['count'] += 1
        received = node.get_clock().now().nanoseconds*1e-9
        age = received - issued
        state['min_age'] = age if state['min_age'] is None else min(state['min_age'], age)
        state['max_age'] = age if state['max_age'] is None else max(state['max_age'], age)
        if not -.1 <= age <= .25:
            state['ages_outside_window'] += 1
        if not all(name in value for name in
                   ('requested_v', 'requested_omega', 'safe_v', 'safe_omega', 'issued_s')):
            state['missing_fields'] += 1
        reason = value.get('reason', '?')
        state['reasons'][reason] = state['reasons'].get(reason, 0) + 1
        if state['first'] is None:
            state['first'] = issued
        if state['last'] is not None:
            gap = issued - state['last']
            if gap > state['max_gap']:
                state['max_gap'], state['worst_at'] = gap, issued
            if gap > .25:
                state['gaps_over_250ms'] += 1
        state['last'] = issued
        OUT.write_text(json.dumps(state))

    node.create_subscription(String, '/safety/decision', on_decision, 10)
    OUT.write_text(json.dumps(state))
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        OUT.write_text(json.dumps(state))
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    sys.exit(main())
