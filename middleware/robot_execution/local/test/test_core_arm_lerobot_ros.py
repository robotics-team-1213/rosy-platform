"""Real LeRobot process -> loopback CORE HTTP -> isolated native ROS action.

Synthetic policy, pixels, authority and ROS server; no Gazebo or physical motion.
"""
import json
import os
from pathlib import Path
import select
import socket
import subprocess
import threading
import time

import pytest

pytest.importorskip('rclpy')
import uvicorn
from test_policy_runtime_ros import ROOT, test_native_session_goal_facts_and_revocation as run_native

PYTHON = Path(os.environ.get('ROSY_OMX_LEROBOT_PYTHON',
    str(Path.home() / 'rosy-test/venvs/omx-lerobot-0.4.4/bin/python')))

CLIENT = r'''
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1])/'integrations/robots/omx/src'))
from lerobot_robot_rosy_omx import RosyOmx, RosyOmxConfig
def emit(value):
    print('ROSY_WIRE=' + json.dumps(value), flush=True)
emit({'ready': True, 'ros_imported': 'rclpy' in sys.modules})
settings = json.loads(sys.stdin.readline())
robot = RosyOmx(RosyOmxConfig(url=settings['url'], token_file=settings['token_file'],
    policy_revision=settings['revision'], joint_names=['joint_1','joint_2'],
    camera_height=2, camera_width=2))
robot.connect()
obs = robot.get_observation()
sent = robot.send_action({'joint_1.pos': .101, 'joint_2.pos': .001})
emit({'sent': sent, 'positions': [obs['joint_1.pos'], obs['joint_2.pos']],
      'rgb': obs['front'].reshape(-1).tolist(), 'ros_imported': 'rclpy' in sys.modules})
assert sys.stdin.readline().strip() == 'stop'
robot.disconnect()
emit({'disconnected': not robot.is_connected})
'''


def read_message(child):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if not select.select([child.stdout], [], [], max(0, deadline-time.monotonic()))[0]:
            break
        line = child.stdout.readline()
        if not line:
            raise AssertionError('LeRobot process exited before its response')
        if line.startswith('ROSY_WIRE='):
            return json.loads(line.removeprefix('ROSY_WIRE='))
    raise AssertionError('LeRobot process response timeout')


@pytest.mark.skipif(not PYTHON.is_file(), reason='isolated LeRobot 0.4.4 environment required')
def test_real_plugin_socket_to_native_ros_and_stop(tmp_path):
    requests, commands = [], []
    with (tmp_path/'sdk-stderr.txt').open('w') as errors:
        child = subprocess.Popen([str(PYTHON), '-u', '-c', CLIENT, str(ROOT)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors, text=True)
        try:
            assert read_message(child) == {'ready': True, 'ros_imported': False}

            def exchange(app, session):
                async def trace(scope, receive, send):
                    if scope['type'] == 'http':
                        requests.append((scope['method'], scope['path']))
                    async def traced_send(message):
                        if (scope.get('path') == '/api/v1/arm/actions'
                                and message['type'] == 'http.response.body' and message.get('body')):
                            body = json.loads(message['body'])
                            if body.get('accepted') is True:
                                commands.append(body['command_id'])
                        await send(message)
                    await app(scope, receive, traced_send)

                with socket.socket() as listener:
                    listener.bind(('127.0.0.1', 0))
                    listener.listen()
                    server = uvicorn.Server(uvicorn.Config(trace, log_level='warning', lifespan='off'))
                    worker = threading.Thread(target=server.run, kwargs={'sockets': [listener]})
                    worker.start()
                    try:
                        deadline = time.monotonic() + 3
                        while not server.started:
                            assert worker.is_alive() and time.monotonic() < deadline
                            time.sleep(.005)
                        token = tmp_path/'fixture-token'
                        token.write_text('synthetic-wire-token')
                        child.stdin.write(json.dumps(dict(url=f'http://127.0.0.1:{listener.getsockname()[1]}',
                            token_file=str(token), revision=session.lease.policy_revision))+'\n')
                        child.stdin.flush()
                        response = read_message(child)
                        assert response['ros_imported'] is False
                        assert response['positions'] == [.1, 0.]
                        assert response['rgb'] == list(range(12))
                        assert response['sent'] == {'joint_1.pos': .101, 'joint_2.pos': .001}
                        assert len(commands) == 1
                        deadline = time.monotonic() + 3
                        while True:
                            record = session._execution_journal.read(commands[0])
                            if record['events'] and record['events'][-1]['kind'] == 'TERMINAL_RESULT':
                                break
                            assert time.monotonic() < deadline
                            time.sleep(.005)
                        assert record['events'][-1]['status'] == 4
                        child.stdin.write('stop\n')
                        child.stdin.flush()
                        assert read_message(child) == {'disconnected': True}
                        assert child.wait(timeout=10) == 0
                        assert session.hold_reason
                        assert requests == [('GET', '/api/v1/arm/policy'),
                            ('POST', '/api/v1/arm/observations'), ('POST', '/api/v1/arm/actions'),
                            ('POST', '/api/v1/arm/stop')]
                        (tmp_path/'socket-receipt.json').write_text(json.dumps(dict(
                            requests=requests, sdk=response, command_id=commands[0],
                            terminal_status=record['events'][-1]['status'], hold=session.hold_reason,
                            auth_scope='synthetic principal override; no Fleet/device authority',
                            physical_motion_verified=False), indent=2))
                        print((tmp_path/'socket-receipt.json').read_text(), flush=True)
                        print('CORE_LEROBOT_NATIVE_SOCKET_PASS', flush=True)
                        return commands[0]
                    finally:
                        server.should_exit = True
                        worker.join(5)
                        assert not worker.is_alive(), 'own HTTP server did not stop'

            run_native(tmp_path, False, False, with_core=True, core_client=exchange)
        finally:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)
            child.stdin.close()
            child.stdout.close()
