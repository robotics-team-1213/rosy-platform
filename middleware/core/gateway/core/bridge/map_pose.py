"""Original dynamic map->base TF lifetime, not localization or map-adoption proof.

TF's latest-common timestamp is not the original AMCL measurement timestamp.
Project its age onto the existing SIM/monotonic line clock conservatively.
Repeated lookup and paused source clocks cannot create another lifetime.
"""
import math
import threading

from core.bridge.odometry import odom_owns_pose


class MapPoseLease:
    def __init__(self):
        self._lock = threading.RLock()
        self._token = None
        self._bad_clock = False
        self._line_high, self._ros_high = float('-inf'), -1
        self._stamp = self._floor = -1
        self._capture = None
        self._state_key = None

    def _clocks(self, bridge):
        try:
            before = bridge._line_clock()
            ros = bridge._node.get_clock().now().nanoseconds
            after = bridge._line_clock()
        except Exception:
            self._bad_clock = True
            raise
        if (not all(type(v) in (int, float) and math.isfinite(v) for v in (before, after))
                or type(ros) is not int or ros < 0 or before < self._line_high
                or after < before or ros < self._ros_high):
            self._bad_clock = True
            raise ValueError('map pose clock fault requires a new bridge scope')
        self._line_high, self._ros_high = after, ros
        if self._bad_clock:
            raise ValueError('map pose clock fault is latched')
        return before, after, ros

    def _reject(self, bridge):
        self._floor = max(self._floor, self._stamp)
        bridge._map_pose_ts = float('-inf')
        bridge._svc.state.expire_pose(frame='map')


def invalidate_map_pose(bridge):
    """Map/lifecycle delivery invalidates in-flight TF reads before processing."""
    lease = bridge._map_pose_lease
    if lease is None:  # An explicitly unbound TF reader has no lease to retire.
        return
    with lease._lock:
        lease._token = None
        lease._reject(bridge)
        try:
            _, _, ros = lease._clocks(bridge)
            lease._floor = max(lease._floor, ros)
        except Exception:
            lease._bad_clock = True


def _original(tf, frame, child):
    stamp = tf.header.stamp
    if (type(stamp.sec) is not int or stamp.sec < 0 or type(stamp.nanosec) is not int
            or not 0 <= stamp.nanosec < 1_000_000_000):
        raise ValueError('invalid original TF timestamp')
    ns = stamp.sec*1_000_000_000+stamp.nanosec
    if ns <= 0 or tf.header.frame_id != frame or tf.child_frame_id != child:
        raise ValueError('unresolved dynamic TF')
    p, q = tf.transform.translation, tf.transform.rotation
    values = p.x, p.y, p.z, q.x, q.y, q.z, q.w
    if (not all(type(v) in (int, float) and math.isfinite(v) for v in values)
            or abs(p.z) > 1e-6 or abs(q.x) > 1e-6 or abs(q.y) > 1e-6
            or abs(sum(v*v for v in values[3:])-1.) > .01):
        raise ValueError('invalid original planar TF')
    return ns, p.x, p.y, math.atan2(2*q.w*q.z, 1-2*q.z*q.z)


def receive_map_pose(bridge, lookup):
    """Bound the complete lookup/parse; only the latest read can commit or reject."""
    lease = bridge._map_pose_lease
    with lease._lock:
        token = lease._token = object()
        frame, child = bridge._map_frame, bridge._base_frame
        try:
            before, _, _ = lease._clocks(bridge)
        except Exception:
            lease._bad_clock = True
            lease._reject(bridge)
            return False
    try:
        tf = lookup()
    except Exception:
        # Missing TF retains only the original, unextended grace window.
        with lease._lock:
            if lease._token is not token:
                return False
            lease._token = None
            try:
                _, after, _ = lease._clocks(bridge)
                if odom_owns_pose(bridge._map_pose_ts, after):
                    lease._reject(bridge)
            except Exception:
                lease._bad_clock = True
                lease._reject(bridge)
        return False
    try:
        sample = _original(tf, frame, child)
    except Exception:
        sample = None
    with lease._lock:
        if lease._token is not token:
            return False
        lease._token = None
        try:
            _, after, ros = lease._clocks(bridge)
            if sample is None or (frame, child) != (bridge._map_frame, bridge._base_frame):
                raise ValueError('TF read no longer matches its original frames')
            stamp, x, y, yaw = sample
            if stamp > ros or stamp <= lease._floor or stamp < lease._stamp:
                raise ValueError('future, consumed or reversed TF')
            capture = math.nextafter(before-(ros-stamp)/1_000_000_000, -math.inf)
            if stamp == lease._stamp:
                capture = min(capture, lease._capture)
            else:
                lease._state_key = object()
            lease._stamp, lease._capture = stamp, capture
            if odom_owns_pose(capture, after):
                raise ValueError('original TF expired during lookup')
            def age_at_commit():
                nonlocal capture
                _, final, source_now = lease._clocks(bridge)
                capture = min(capture, math.nextafter(before-(source_now-stamp)/1_000_000_000, -math.inf))
                if odom_owns_pose(capture, final):
                    raise ValueError('original TF expired before state commit')
                return final-capture
            bridge._svc.state._record_map_pose(x, y, yaw, source_key=lease._state_key,
                                               age_at_commit=age_at_commit)
            lease._capture = capture
            bridge._map_pose_ts = capture
            return True
        except Exception:
            lease._reject(bridge)
            return False
