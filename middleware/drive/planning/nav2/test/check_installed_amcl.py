"""Exercise the installed standalone binary in the remote runner's isolated domain."""
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import time

import rclpy
from lifecycle_msgs.msg import State
from lifecycle_msgs.srv import GetState


def main():
    executable = Path(sys.argv[1]) / 'lib/navigation/rosy_verified_amcl'
    namespace = '/installed_native_map_' + secrets.token_hex(4)
    child = subprocess.Popen(
        [str(executable), '--ros-args', '-r', '__ns:=' + namespace],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    node = None
    try:
        rclpy.init()
        node = rclpy.create_node('installed_binary_observer', namespace=namespace)
        client = node.create_client(GetState, namespace + '/amcl/get_state')
        deadline = time.monotonic() + 8
        while not client.wait_for_service(timeout_sec=.1):
            if child.poll() is not None or time.monotonic() >= deadline:
                raise RuntimeError('installed AMCL did not expose its actual lifecycle service')
        future = client.call_async(GetState.Request())
        rclpy.spin_until_future_complete(node, future, timeout_sec=8)
        assert future.done() and future.result() is not None
        assert future.result().current_state.id == State.PRIMARY_STATE_UNCONFIGURED
        deadline = time.monotonic() + 8
        while ('amcl', namespace) not in (observed := node.get_node_names_and_namespaces()):
            if child.poll() is not None or time.monotonic() >= deadline:
                raise RuntimeError(f'installed AMCL node was not discovered: {observed}')
            rclpy.spin_once(node, timeout_sec=.1)
        for topic in ('cmd_vel', 'nav_cmd_vel'):
            owned = [info for info in node.get_publishers_info_by_topic(namespace + '/' + topic)
                     if info.node_name == 'amcl' and info.node_namespace == namespace]
            assert not owned, (topic, owned)
        print('native_map_installed_amcl: real standalone lifecycle graph, initially unconfigured')
    finally:
        if child.poll() is None:
            child.send_signal(signal.SIGINT)
        try:
            output, _ = child.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
            child.communicate()
            raise RuntimeError('owned installed AMCL did not stop within 10 seconds')
        finally:
            if node is not None:
                node.destroy_node()
            if rclpy.ok():
                rclpy.shutdown()
        print(output.decode('utf-8', 'replace'))
        assert child.returncode == 0, child.returncode


if __name__ == '__main__':
    main()
