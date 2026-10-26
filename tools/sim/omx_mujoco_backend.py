#!/usr/bin/env python3
"""D-866 P2 MuJoCo backend adapter for the OMX-F: physics and top/front cameras on the shared layer's topics.

It reads the URDF that omx_topic_backend.py wrote (vendor joints and meshes), adds position actuators, a floor,
a fixed top camera and a wrist front camera, then publishes /clock, SIM_STATES and the camera images on simulation
time and applies SIM_COMMANDS. It never serves the trajectory Action itself; the shared layer's
joint_trajectory_controller does.

  MUJOCO_GL=egl python3 tools/sim/omx_mujoco_backend.py --urdf DIR/omx_f_topic.urdf --shape 240x320 --camera-hz 5
"""
import argparse
from pathlib import Path
import re
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from omx_topic_backend import SIM_COMMANDS, SIM_STATES  # noqa: E402
from omx_backend_conformance import CAMERAS, JOINTS, OBJECTS  # noqa: E402
from omx_cell_world import boxes, quaternion  # noqa: E402

TIMESTEP_S, STATE_PERIOD_S = .002, .01
KP, DAMPING, ARMATURE = 40.0, .3, .01  # Position servo and joint damping; stable at 2 ms, not tuned to the real arm.
TOP_CAMERA_POS = (.12, 0.0, .65)  # Above the work area, looking down (cell top camera ~650 mm, D-794).


def mjcf_urdf(urdf, mesh_root):
    """The URDF as MuJoCo's parser takes it: no gazebo/ros2_control blocks, meshes from mesh_root."""
    urdf = re.sub(r'<(gazebo|ros2_control)\b.*?</\1>', '', urdf, flags=re.S)
    urdf = re.sub(r'package://open_manipulator_description/meshes/omx_f/', '', urdf)
    head = (f'<mujoco><compiler meshdir="{mesh_root}" strippath="true" balanceinertia="true" '
            'discardvisual="false" fusestatic="false"/></mujoco>')
    return re.sub(r'(<robot\b[^>]*>)', r'\1'+head, urdf, count=1)


def adjacent_links(urdf):
    """URDF joint parent/child link pairs, without the world anchor."""
    pairs = re.findall(r'<joint\s[^>]*>.*?<parent link="([^"]+)"/>\s*<child link="([^"]+)"/>', urdf, flags=re.S)
    return [(parent, child) for parent, child in pairs if 'world' not in (parent, child)]


def build(urdf, mesh_root, shape):
    import mujoco
    spec = mujoco.MjSpec.from_string(mjcf_urdf(urdf, mesh_root))
    spec.option.timestep = TIMESTEP_S
    spec.visual.global_.offwidth, spec.visual.global_.offheight = shape[1], shape[0]
    world = spec.worldbody
    world.add_geom(type=mujoco.mjtGeom.mjGEOM_PLANE, size=[1, 1, .1], rgba=[.6, .6, .6, 1], pos=[0, 0, -.02])
    for box in boxes():  # The same work scene as Gazebo's omx_cell_workcell.sdf (D-877).
        geom = dict(type=mujoco.mjtGeom.mjGEOM_BOX, size=[s/2 for s in box['size']],
                    friction=[box['friction'], .005, .0001], rgba=[.7, .6, .4, 1])
        if box['static']:
            world.add_geom(name=box['name'], pos=box['pos'], quat=quaternion(box['rpy']), **geom)
        else:
            body = world.add_body(name=box['name'], pos=box['pos'], quat=quaternion(box['rpy']))
            body.add_freejoint()
            body.add_geom(name=box['name'], mass=box['mass'], **geom)
    world.add_light(pos=[0, 0, 1.5], dir=[0, 0, -1], diffuse=[.8, .8, .8])
    world.add_camera(name='top', pos=list(TOP_CAMERA_POS), xyaxes=[0, -1, 0, 1, 0, 0], fovy=60)
    spec.body('link5').add_camera(name='front', pos=[.05, 0, .03], xyaxes=[0, -1, 0, 0, 0, 1], fovy=70)
    for joint in spec.joints:
        joint.damping, joint.armature = DAMPING, ARMATURE
    for name in JOINTS:
        joint = spec.joint(name)
        spec.add_actuator(name=name, target=name, trntype=mujoco.mjtTrn.mjTRN_JOINT,
                          gaintype=mujoco.mjtGain.mjGAIN_FIXED, gainprm=[KP]+[0]*9,
                          biastype=mujoco.mjtBias.mjBIAS_AFFINE, biasprm=[0, -KP, -2*KP**.5*.5]+[0]*7,
                          ctrllimited=True, ctrlrange=list(joint.range))
    # The vendor meshes overlap at each joint (link0/link1 by 8 mm blocked joint1) and between the two fingers;
    # Gazebo does not self-collide them either. Contacts with the world and objects stay.
    for parent, child in adjacent_links(urdf):
        spec.add_exclude(bodyname1=parent, bodyname2=child)
    spec.add_exclude(bodyname1='link6', bodyname2='link7')
    # The URDF mimic (gripper_joint_2 = -gripper_joint_1) as an equality, since MuJoCo ignores <mimic>.
    spec.add_equality(type=mujoco.mjtEq.mjEQ_JOINT, name1='gripper_joint_2', name2='gripper_joint_1',
                      data=[0, -1, 0, 0, 0]+[0]*6)
    return spec.compile()


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--urdf', type=Path, required=True)
    parser.add_argument('--shape', required=True, metavar='HxW')
    parser.add_argument('--camera-hz', type=float, required=True)
    parser.add_argument('--real-time-factor', type=float, default=1.0)
    args = parser.parse_args()
    shape = tuple(int(v) for v in args.shape.lower().split('x'))
    import mujoco
    import rclpy
    from ament_index_python.packages import get_package_share_directory
    from builtin_interfaces.msg import Time
    from rclpy.node import Node
    from rclpy.qos import qos_profile_sensor_data
    from rosgraph_msgs.msg import Clock
    from geometry_msgs.msg import TransformStamped
    from sensor_msgs.msg import Image, JointState
    from tf2_msgs.msg import TFMessage

    mesh_root = Path(get_package_share_directory('open_manipulator_description'))/'meshes/omx_f'
    model = build(args.urdf.read_text(), mesh_root, shape)
    data = mujoco.MjData(model)
    renderers = {name: mujoco.Renderer(model, *shape) for name in CAMERAS}
    # Arm joints only; the movable work-scene boxes have free joints, which are not joint states.
    joints = [model.joint(i).name for i in range(model.njnt) if model.jnt_type[i] != mujoco.mjtJoint.mjJNT_FREE]
    qpos = {name: model.joint(name).qposadr[0] for name in joints}
    qvel = {name: model.joint(name).dofadr[0] for name in joints}
    actuator = {name: model.actuator(name).id for name in JOINTS}
    movable = [box['name'] for box in boxes() if not box['static']]

    rclpy.init()
    node = Node('omx_mujoco_backend')
    clock_pub = node.create_publisher(Clock, '/clock', 10)
    state_pub = node.create_publisher(JointState, SIM_STATES, 10)
    image_pub = {name: node.create_publisher(Image, topic, qos_profile_sensor_data) for name, topic in CAMERAS.items()}
    object_pub = node.create_publisher(TFMessage, OBJECTS, 10)  # Evaluation facts, never a policy input.

    def command(message):
        for name, position in zip(message.name, message.position):
            if name in actuator:
                data.ctrl[actuator[name]] = position
    node.create_subscription(JointState, SIM_COMMANDS, command, 10)

    def stamp():
        ns = int(round(data.time*1e9))
        return Time(sec=ns//1_000_000_000, nanosec=ns % 1_000_000_000)

    print('OMX_MUJOCO_BACKEND_READY', flush=True)
    began, next_state, next_camera = time.monotonic(), 0.0, 0.0
    try:
        while rclpy.ok():
            mujoco.mj_step(model, data)
            if data.time >= next_state:
                next_state += STATE_PERIOD_S
                now = stamp()
                clock_pub.publish(Clock(clock=now))
                state = JointState(name=joints, position=[float(data.qpos[qpos[n]]) for n in joints],
                                   velocity=[float(data.qvel[qvel[n]]) for n in joints])
                state.header.stamp = now
                state_pub.publish(state)
                poses = []
                for name in movable:
                    pose = TransformStamped()
                    pose.header.stamp, pose.header.frame_id, pose.child_frame_id = now, 'world', name
                    (pose.transform.translation.x, pose.transform.translation.y,
                     pose.transform.translation.z) = (float(v) for v in data.body(name).xpos)
                    (pose.transform.rotation.w, pose.transform.rotation.x, pose.transform.rotation.y,
                     pose.transform.rotation.z) = (float(v) for v in data.body(name).xquat)
                    poses.append(pose)
                object_pub.publish(TFMessage(transforms=poses))
                rclpy.spin_once(node, timeout_sec=0)
            if data.time >= next_camera:
                next_camera += 1/args.camera_hz
                for name, renderer in renderers.items():
                    renderer.update_scene(data, name)
                    image = Image(height=shape[0], width=shape[1], encoding='rgb8', step=shape[1]*3,
                                  data=renderer.render().tobytes())
                    image.header.stamp, image.header.frame_id = stamp(), name+'_camera_optical'
                    image_pub[name].publish(image)
            lead = began+data.time/args.real_time_factor-time.monotonic()
            if lead > 0:
                time.sleep(lead)
    finally:
        for renderer in renderers.values():
            renderer.close()
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
