"""Real loopback HTTP/peer-credential UDS, with no process app and a stdlib-only client."""
import os
from pathlib import Path
import subprocess
import sys


def _probe(root):
    import hashlib
    import json
    import socket
    import tempfile
    import threading
    import time
    from types import SimpleNamespace

    import uvicorn
    from fleet.server.app import create_app
    from fleet.server.console import FleetConsole
    from fleet.server.task_service import FleetTaskService
    from fleet.server.task_store import FleetTaskStore
    from omx_adapter.action_api import ActionApi, UnixActionServer
    from omx_adapter.command_owner import ArmCommandOwner, JointStateSnapshot
    from omx_adapter.kinematics import ARM_JOINTS, OmxKinematics, TopDownPose
    from omx_adapter.transfer_motion import ArmPlanningProfile, GraspGeometry
    from omx_adapter.transfer_preflight import ArmTransferCatalog, TransferPose
    from omx_adapter.transfer_preflight_owner import build_transfer_preflight_api

    profile = ArmPlanningProfile.load(Path(__file__).resolve().parents[3] / "deploy/robot/omx/sim/cell_profile.yaml")
    kin = OmxKinematics.load()
    clock = lambda: 100.01
    home = TopDownPose(0.12, 0, 0.12, 0)
    catalog = ArmTransferCatalog("arm-cell", "arm-a", profile.revision, kin.revision, "sim-cal", "sim-tf",
        kin.planning_scene_revision, home, 0.11,
        {"p1": TransferPose(TopDownPose(0.18, -0.12, 0.02, 0.3), 0.06),
         "p2": TransferPose(TopDownPose(0.17, 0.13, 0.045, -0.5), 0.085)},
        {"g1": GraspGeometry(0.03, 0.01, 0.03, True)})

    class NoMotionPort:
        def __getattr__(self, name):
            raise AssertionError("read-only preflight touched an actuator port: " + name)

    owner = ArmCommandOwner(profile.arm_command_config(workcell_id="arm-cell", instance_id="arm-a",
        calibration_revision="sim-cal", allowed_owners=("rule_based",)), NoMotionPort(), monotonic=clock)
    joints = dict(zip(ARM_JOINTS, kin.solve_top_down(home, profile.ik_limits()).joints))
    joints[profile.gripper_joint] = profile.gripper_open
    assert owner.observe_joint_state(JointStateSnapshot(joints, 7, 100.0, "sim-cal"))
    runtime = SimpleNamespace(owner=owner, monotonic=clock)
    read_api = build_transfer_preflight_api(runtime, catalog=catalog, profile=profile, kinematics=kin,
        transform_revision="sim-tf", journal_id="temporary-owner-journal", allowed_peer_uids={os.getuid()})

    with tempfile.TemporaryDirectory(prefix="arm-pf-") as short_root:
        socket_root = Path(short_root)
        (socket_root / "arm-a").mkdir()
        uds = UnixActionServer(ActionApi(object(), transfer_preflight_api=read_api),
                               socket_root / "arm-a/control.sock")
        uds_thread = threading.Thread(target=uds.serve_forever, daemon=True)
        uds_thread.start()
        server = http_thread = listener = None
        try:
            deadline = time.monotonic() + 10
            while not uds.is_serving and time.monotonic() < deadline:
                time.sleep(0.01)
            assert uds.is_serving
            users = {hashlib.sha256(role.encode()).hexdigest(): {"principal_id": role, "role": role}
                     for role in ("operator", "viewer")}
            app = create_app(FleetConsole([], []), deployment_profile="simulation",
                task_service=FleetTaskService(FleetTaskStore(root / "fleet.db"), robot_ids=()), site_users=users,
                omx_instances={"arm-cell": "arm-a"}, omx_socket_root=socket_root)
            listener = socket.socket()
            listener.bind(("127.0.0.1", 0))
            listener.listen(8)
            url = f"http://127.0.0.1:{listener.getsockname()[1]}/api/fleet/arm-transfers/preflight"
            server = uvicorn.Server(uvicorn.Config(app, log_level="critical", lifespan="on"))
            http_thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
            http_thread.start()
            deadline = time.monotonic() + 10
            while not server.started and http_thread.is_alive() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert server.started
            body = dict(workcell_id="arm-cell", instance_id="arm-a", catalog_digest=catalog.digest,
                        source="p1", target="p2", geometry="g1")
            client = subprocess.run([sys.executable, "-I", "-S", "-c", CLIENT, url, json.dumps(body)],
                                    capture_output=True, text=True, timeout=20, cwd=root)
            assert client.returncode == 0, client.stderr
            assert client.stdout.strip() == "ARM_HTTP_OK"
            assert owner.state == "ready"
        finally:
            if server is not None:
                server.should_exit = True
            if http_thread is not None:
                http_thread.join(timeout=5)
                assert not http_thread.is_alive()
            if listener is not None:
                listener.close()
            uds.stop()
            uds_thread.join(timeout=2)
            assert not uds_thread.is_alive()


CLIENT = r'''
import importlib.util, json, sys, urllib.error, urllib.request
assert importlib.util.find_spec('core_common') is None
assert importlib.util.find_spec('fleet') is None
assert importlib.util.find_spec('omx_adapter') is None
url, body = sys.argv[1], json.loads(sys.argv[2])
def call(data, role='operator'):
    req = urllib.request.Request(url, json.dumps(data).encode(),
        headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + role})
    try:
        with urllib.request.urlopen(req, timeout=5) as reply:
            return reply.status, json.load(reply)
    except urllib.error.HTTPError as reply:
        return reply.code, json.load(reply)
status, reply = call(body)
assert status == 200, (status, reply)
check = reply['check']
assert check['request'] == body and check['source_state_sequence'] == 7
assert check['simulation'] is True and check['collision_checked'] is False
assert 0 <= check['state_age_s'] < .5
assert not {'phases', 'permit', 'action_id', 'cargo_arrived'} & set(check)
status, reply = call({**body, 'target': 'not-installed'})
assert status == 404 and reply['detail']['code'] == 'ARM_REFERENCE_UNAVAILABLE', (status, reply)
status, reply = call({**body, 'catalog_digest': '0' * 64})
assert status == 409 and reply['detail']['code'] == 'ARM_CATALOG_CHANGED', (status, reply)
assert call(body, 'viewer')[0] == 403
print('ARM_HTTP_OK')
'''


def test_neutral_arm_preflight_crosses_http_and_uds_without_process_packages(tmp_path):
    script = r'''
import builtins, pathlib, sys
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name.startswith(('rosy.processes', 'rosy_cell', 'rosy_agent', 'rclpy')) or name == 'fleet.server.cell_compiler':
        raise ImportError('process/ROS package is unavailable to neutral preflight')
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
from test_arm_transfer_preflight_http import _probe
_probe(pathlib.Path(sys.argv[1]))
'''
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path)], capture_output=True, text=True,
                            timeout=45, env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)})
    assert result.returncode == 0, result.stderr
