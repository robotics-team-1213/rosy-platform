#!/usr/bin/env python3
"""D-866 §2 OMX simulator backend conformance: the ROS interface every backend (Gazebo, Isaac) must expose.

check() is ROS-free and judges recorded samples; collect() records them from a running backend. Rates are
measured on message stamps (simulation time), so a backend below real-time still conforms; the separate Isaac
switch conditions (10 Hz at 640x480, real-time factor >= 1) are not judged here.

Usage on a sim host with the backend running:
  python3 tools/sim/omx_backend_conformance.py --shape 240x320 --camera-hz 5 --out report.json
"""
import argparse
import json
import time

JOINTS = ('joint1', 'joint2', 'joint3', 'joint4', 'joint5', 'gripper_joint_1')
ACTION = '/arm_controller/follow_joint_trajectory'
CAMERAS = {'top': '/top_camera/image_raw', 'front': '/front_camera/image_raw'}
JOINT_MIN_HZ = 20.0
STOP_TOLERANCE_RAD = .005  # Joint travel allowed after the cancel is acknowledged and the settle window ends.


def _rate(stamps):
    return (len(stamps)-1)/((stamps[-1]-stamps[0])/1e9) if len(stamps) > 1 and stamps[-1] > stamps[0] else 0.0


def _increasing(stamps):
    return all(b > a for a, b in zip(stamps, stamps[1:]))


def check(samples, *, shape, camera_hz, joint_hz=JOINT_MIN_HZ):
    """samples: joint_states [(stamp_ns, names, positions)], cameras {name: [(stamp_ns, encoding, height, width)]},
    clock [ns], stop {accepted, cancel_acknowledged, travel_after_rad}. Returns the list of failures."""
    failures = []
    joints = samples.get('joint_states') or []
    if not joints:
        failures.append('joint_states: no messages')
    else:
        orders = {tuple(names) for _, names, _ in joints}
        if len(orders) != 1:
            failures.append('joint_states: joint order changes between messages')
        names = next(iter(orders))
        if len(set(names)) != len(names) or not set(JOINTS) <= set(names):
            failures.append(f'joint_states: names {list(names)} must contain {list(JOINTS)} once')
        stamps = [stamp for stamp, _, _ in joints]
        if not _increasing(stamps):
            failures.append('joint_states: stamps not strictly increasing')
        if _rate(stamps) < joint_hz:
            failures.append(f'joint_states: {_rate(stamps):.1f} Hz < {joint_hz} Hz')
    for name in CAMERAS:
        frames = (samples.get('cameras') or {}).get(name) or []
        if not frames:
            failures.append(f'camera {name}: no frames')
            continue
        if any((encoding, height, width) != ('rgb8', *shape) for _, encoding, height, width in frames):
            failures.append(f'camera {name}: frames must be rgb8 {shape[0]}x{shape[1]}')
        stamps = [stamp for stamp, *_ in frames]
        if not _increasing(stamps):
            failures.append(f'camera {name}: stamps not strictly increasing')
        if _rate(stamps) < camera_hz:
            failures.append(f'camera {name}: {_rate(stamps):.1f} Hz < {camera_hz} Hz')
    clock = samples.get('clock') or []
    if len(clock) < 2 or clock[-1] <= clock[0] or any(b < a for a, b in zip(clock, clock[1:])):
        failures.append('clock: must advance without going back')
    stop = samples.get('stop') or {}
    if not (stop.get('accepted') and stop.get('cancel_acknowledged')):
        failures.append('stop: trajectory goal must be accepted and its cancel acknowledged')
    elif not stop.get('travel_after_rad', 1.0) <= STOP_TOLERANCE_RAD:
        failures.append(f"stop: {stop.get('travel_after_rad')} rad travel after cancel > {STOP_TOLERANCE_RAD}")
    return failures


def collect(*, seconds=10.0, ready_s=120.0, settle_s=1.0, probe_joint='joint1', probe_delta_rad=.3):
    """Record from the running backend, then send one slow goal and cancel it mid-motion."""
    import rclpy
    from rclpy.action import ActionClient
    from rclpy.executors import SingleThreadedExecutor
    from rclpy.node import Node
    from rclpy.parameter import Parameter
    from rclpy.qos import qos_profile_sensor_data
    from builtin_interfaces.msg import Duration
    from control_msgs.action import FollowJointTrajectory
    from rosgraph_msgs.msg import Clock
    from sensor_msgs.msg import Image, JointState
    from trajectory_msgs.msg import JointTrajectoryPoint

    rclpy.init()
    node = Node('omx_backend_conformance', parameter_overrides=[Parameter('use_sim_time', value=True)])
    samples = dict(joint_states=[], cameras={name: [] for name in CAMERAS}, clock=[])
    stamp = lambda header: header.stamp.sec*1_000_000_000+header.stamp.nanosec
    node.create_subscription(JointState, '/joint_states', lambda m: samples['joint_states'].append(
        (stamp(m.header), list(m.name), list(m.position))), 50)
    for name, topic in CAMERAS.items():
        node.create_subscription(Image, topic, lambda m, name=name: samples['cameras'][name].append(
            (stamp(m.header), m.encoding, m.height, m.width)), qos_profile_sensor_data)
    node.create_subscription(Clock, '/clock', lambda m: samples['clock'].append(
        m.clock.sec*1_000_000_000+m.clock.nanosec), qos_profile_sensor_data)
    client = ActionClient(node, FollowJointTrajectory, ACTION)
    executor = SingleThreadedExecutor()
    executor.add_node(node)

    def spin_for(duration):
        deadline = time.monotonic()+duration
        while time.monotonic() < deadline:
            executor.spin_once(timeout_sec=.05)

    def spin_until(future, duration):
        deadline = time.monotonic()+duration
        while not future.done() and time.monotonic() < deadline:
            executor.spin_once(timeout_sec=.05)
        return future.result() if future.done() else None

    try:
        deadline = time.monotonic()+ready_s  # Backends start slowly; record only once every interface is up.
        while time.monotonic() < deadline and not (samples['joint_states'] and samples['clock']
                and all(samples['cameras'].values()) and client.server_is_ready()):
            executor.spin_once(timeout_sec=.1)
        samples['joint_states'].clear(); samples['clock'].clear()
        for frames in samples['cameras'].values():
            frames.clear()
        spin_for(seconds)
        stop = dict(accepted=False, cancel_acknowledged=False)
        if samples['joint_states'] and client.wait_for_server(timeout_sec=10):
            _, names, positions = samples['joint_states'][-1]
            current = dict(zip(names, positions))
            goal = FollowJointTrajectory.Goal()
            goal.trajectory.joint_names = list(JOINTS)
            point = JointTrajectoryPoint()
            point.positions = [current[j]+(probe_delta_rad if j == probe_joint else 0.0) for j in JOINTS]
            point.time_from_start = Duration(sec=4)
            goal.trajectory.points = [point]
            handle = spin_until(client.send_goal_async(goal), 5)
            stop['accepted'] = bool(handle and handle.accepted)
            if stop['accepted']:
                spin_for(1.0)  # Mid-motion: a quarter of the 4 s trajectory.
                cancel = spin_until(handle.cancel_goal_async(), 5)
                stop['cancel_acknowledged'] = bool(cancel and cancel.goals_canceling)
                spin_for(settle_s)
                index = samples['joint_states'][-1][1].index(probe_joint)
                begin = samples['joint_states'][-1][2][index]
                spin_for(2.0)
                stop['travel_after_rad'] = abs(samples['joint_states'][-1][2][index]-begin)
        samples['stop'] = stop
        return samples
    finally:
        node.destroy_node()
        rclpy.shutdown()


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--shape', required=True, metavar='HxW', help='installed camera size')
    parser.add_argument('--camera-hz', type=float, required=True, help='minimum camera rate on stamps')
    parser.add_argument('--seconds', type=float, default=10.0)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    shape = tuple(int(v) for v in args.shape.lower().split('x'))
    samples = collect(seconds=args.seconds)
    failures = check(samples, shape=shape, camera_hz=args.camera_hz)
    summary = dict(failures=failures, shape=shape, camera_hz=args.camera_hz,
                   joint_messages=len(samples['joint_states']), camera_frames={k: len(v) for k, v in samples['cameras'].items()},
                   clock_messages=len(samples['clock']), stop=samples['stop'])
    with open(args.out, 'x', encoding='utf-8') as stream:
        json.dump(summary, stream, indent=2)
    print('OMX_BACKEND_CONFORMANCE_'+('PASS' if not failures else 'FAIL')+'='+json.dumps(summary), flush=True)
    raise SystemExit(1 if failures else 0)


if __name__ == '__main__':
    main()
