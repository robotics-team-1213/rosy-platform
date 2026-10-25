"""D-866 P1: the Gazebo OMX backend (P0 top/front world) against tools/sim/omx_backend_conformance.py.

remote_sim only: `remote_sim.py --host ai cmd -- "OMX_CELL_OVERLAY=... python3 <this file>"`.
"""
import os
from contextlib import ExitStack
from pathlib import Path
import subprocess
import sys

import policy_chain_vla_gazebo as p0
from policy_chain_gazebo import ROOT, process


def main():
    out = Path(os.environ['OUT']).resolve()
    assert out.is_dir() and os.environ.get('ROS_AUTOMATIC_DISCOVERY_RANGE') == 'LOCALHOST'
    world_file, _ = p0.vla_world(out)
    env = dict(os.environ, OMX_CELL_WORLD=str(world_file.with_suffix('')), OMX_CELL_LOG_DIR=str(out),
               OMX_CELL_DOMAIN_ID=os.environ['ROS_DOMAIN_ID'])
    with ExitStack() as stack:
        stack.enter_context(process(['bash', 'deploy/robot/omx/run_cell_sim.sh'], out, 'vendor', env=env))
        stack.enter_context(process(['ros2', 'run', 'ros_gz_bridge', 'parameter_bridge',
            *[topic+'@sensor_msgs/msg/Image[gz.msgs.Image' for _, topic in p0.CAMERAS]], out, 'camera-bridge'))
        shape = f'{p0.SHAPE[1]}x{p0.SHAPE[2]}'
        result = subprocess.run([sys.executable, str(ROOT/'tools/sim/omx_backend_conformance.py'), '--shape', shape,
                                 '--camera-hz', str(p0.CAMERA_HZ*.9), '--out', str(out/'conformance.json')])
    raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
