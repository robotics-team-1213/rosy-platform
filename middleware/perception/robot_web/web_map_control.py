"""web_node SLAM operations: reset / pause / resume against slam_toolbox.

Needs rclpy and the slam_toolbox services, so it stays out of the ROS-free
web_state / web_http / web_render modules. The HTTP thread calls `execute`;
ROS futures complete on the spin thread.
"""
import threading
import time

import rclpy
from rcl_interfaces.msg import ParameterType
from rcl_interfaces.srv import GetParameters
from std_msgs.msg import String

from control.web_state import (
    K_ETA, K_GOAL, K_GSTATE, K_MAP, K_OPTIONS, K_PATH, K_POSE, K_PREV, K_ROUTE, K_TRAIL,
    LOCK, MAP_PNG, STATE)

try:
    from slam_toolbox.srv import Reset, Pause
except ImportError:
    Reset = Pause = None  # Viewing remains available without SLAM installed.


class MapControl:
    """Serialize HTTP SLAM operations while ROS futures run on the spin thread."""
    def __init__(self, node):
        self.node = node
        self.lock = threading.Lock()
        self.pending = None
        self.map_after_ns = 0
        self.reset = node.create_client(Reset, 'slam_toolbox/reset') if Reset else None
        self.pause = node.create_client(Pause, 'slam_toolbox/pause_new_measurements') if Pause else None
        self.params = node.create_client(GetParameters, 'slam_toolbox/get_parameters')
        self.update(available=False, paused=None, busy=False, error='', epoch=0)
        threading.Thread(target=self.poll, daemon=True).start()

    def update(self, **values):
        with LOCK:
            STATE.setdefault('map_control', {}).update(values)

    def snapshot(self):
        with LOCK:
            return dict(STATE['map_control'])

    def call(self, client, request):
        if self.pending is not None and not self.pending.done():
            raise RuntimeError('Previous SLAM request is still pending')
        if client is None or not client.service_is_ready():
            raise ConnectionError('SLAM service is unavailable')
        future = client.call_async(request)
        self.pending = future
        ready = threading.Event()
        future.add_done_callback(lambda _: ready.set())
        if not ready.wait(2.0):
            # Do not cancel: the server may still apply a timed-out toggle.
            # Retaining this future prevents a second mutation until it ends.
            raise TimeoutError('SLAM response timed out; outcome is unknown')
        return future.result()

    def read_paused(self):
        response = self.call(self.params, GetParameters.Request(
            names=['paused_new_measurements']))
        if len(response.values) != 1 or response.values[0].type != ParameterType.PARAMETER_BOOL:
            raise RuntimeError('SLAM paused state is unavailable')
        paused = response.values[0].bool_value
        self.update(paused=paused)
        return paused

    def poll(self):
        while rclpy.ok():
            if self.lock.acquire(blocking=False):
                try:
                    available = bool(self.reset and self.reset.service_is_ready())
                    self.update(available=available)
                    if available:
                        self.read_paused()
                        self.update(error='', busy=False)
                    else:
                        self.update(paused=None)
                except Exception as exc:
                    self.update(paused=None, error=str(exc))
                finally:
                    self.lock.release()
            time.sleep(2.0)

    def execute(self, action):
        if not self.lock.acquire(blocking=False):
            return 409, {'ok': False, 'message': 'Map control is busy',
                         'map_control': self.snapshot()}
        self.update(busy=True, error='')
        status, message = 200, ''
        try:
            if self.pending is not None and not self.pending.done():
                raise RuntimeError('Previous SLAM request is still pending')
            if action == 'reset':
                self.node.wander_pub.publish(String(data='stop'))
                self.node.estop_pub.publish(String(data='stop'))
                self.node.goal_pub.publish(String(data='stop'))
                response = self.call(self.reset, Reset.Request(pause_new_measurements=True)
                                     if Reset else None)
                if response.result != Reset.Response.RESULT_SUCCESS:
                    raise RuntimeError('SLAM rejected map reset')
                self.node.goal_pub.publish(String(data='reset'))
                self.node.calibration_pub.publish(String(data='sensor_check'))
                self.map_after_ns = self.node.get_clock().now().nanoseconds
                with LOCK:
                    for key in (K_MAP, K_GOAL, K_ROUTE, K_OPTIONS, K_TRAIL, K_PREV,
                                K_POSE, 'trail_odom', 'path_exact_m'):
                        STATE.pop(key, None)
                    STATE[K_PATH] = 0.0
                    STATE[K_ETA] = None
                    STATE[K_GSTATE] = 'map reset; mapping paused'
                    MAP_PNG['bytes'] = None
                    MAP_PNG['gen'] += 1
                    STATE['map_control']['epoch'] += 1
                    STATE['map_control']['paused'] = True
                message = 'Map reset; mapping paused and stop commands sent'
            elif action == 'pause':
                self.node.wander_pub.publish(String(data='stop'))
                self.node.goal_pub.publish(String(data='stop'))
                if not self.read_paused():
                    response = self.call(self.pause, Pause.Request() if Pause else None)
                    if not response.status:
                        raise RuntimeError('SLAM rejected mapping pause')
                    if not self.read_paused():
                        raise RuntimeError('SLAM still reports mapping active')
                message = 'Mapping paused; autonomous driving stopped; map retained'
            elif action == 'resume':
                if self.read_paused():
                    response = self.call(self.pause, Pause.Request() if Pause else None)
                    if not response.status:
                        raise RuntimeError('SLAM rejected mapping resume')
                    if self.read_paused():
                        raise RuntimeError('SLAM still reports mapping paused')
                message = 'Mapping active; robot motion remains unchanged'
            else:
                raise ValueError('Unknown map operation')
        except Exception as exc:
            status = 504 if isinstance(exc, TimeoutError) else 503 if isinstance(exc, ConnectionError) else 409
            message = str(exc)
            self.update(paused=None, error=message)
        finally:
            self.update(busy=bool(self.pending is not None and not self.pending.done()))
            self.lock.release()
        return status, {'ok': status == 200, 'message': message,
                        'map_control': self.snapshot()}
