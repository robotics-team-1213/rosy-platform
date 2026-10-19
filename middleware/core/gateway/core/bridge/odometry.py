"""Odometry-derived geometry the bridge used to compute inline. ROS-free.

Undocking measures how far it has come with this and nothing else — no sensor
confirms it — so a wrong answer drives the robot into the dock or leaves it
short of clearance, and neither shows up in a boot smoke test.
"""

from __future__ import annotations

import math
from typing import Optional
from core.bridge.translate import yaw_from_quat

Point = Optional[tuple[float, float]]


def travelled_m(mark: Point, current: Point) -> float:
    """Straight-line distance from the mark, or 0.0 when there is no baseline.

    Zero is the safe answer for a missing mark: the caller reads this as "not
    far enough yet" and keeps waiting, where a large number would read as
    "clear" and stop a reverse early. Straight-line is deliberate — undocking
    reverses along one axis, so path length would only add drift.
    """
    if mark is None or current is None:
        return 0.0
    return math.hypot(current[0] - mark[0], current[1] - mark[1])


#: map→base TF 를 이 시간 안에 읽었으면 map 프레임 pose 가 살아 있다고 본다. state 틱은
#: 기본 10 Hz 라 여유 있게 잡는다 - 한두 틱 놓쳤다고 화면이 odom 으로 튀면 안 된다.
MAP_POSE_TTL_S = 2.0


def odom_owns_pose(map_pose_ts: float, now: float,
                   ttl_s: float = MAP_POSE_TTL_S) -> bool:
    """odom 이 보고 pose 를 써도 되는가.

    브리지에는 pose 를 쓰는 곳이 둘이다 - odom 콜백(약 30 Hz)과 map→base TF 를 읽는 state
    틱(10 Hz). 둘 다 같은 필드에 쓰면 주기가 높은 odom 이 대부분 이겨서, 보고 위치가
    조용히 odom 프레임으로 바뀐다. 미로 주행 뒤 AMCL 은 정답과 4 cm 안에 있었는데 API 는
    3.3 m 떨어진 odom 값을 돌려줬다 - 관제 화면도 미션 판정도 그 값을 읽는다.

    그래서 map 프레임이 권위다. odom 은 그것이 없을 때만 - 맵도 SLAM 도 없는 teleop
    구성에서는 화면에 무엇이라도 띄워야 하므로 - 폴백으로 쓴다.
    """
    values = map_pose_ts, now, ttl_s
    return (not all(type(v) in (int, float) and math.isfinite(v) for v in values)
            or ttl_s <= 0 or now < map_pose_ts or (now-map_pose_ts) >= ttl_s)


def observe_bounded_trial(bridge, msg, sample, *, now=None):
    """Optional private trial input; original ROS clock/frame, never fake seq."""
    guard=bridge._bounded_trial_guard
    if guard is None:return
    try:
        from core_features.command.bounded_trial import BoundedTrial
        if type(guard) is not BoundedTrial:raise ValueError('exact trial guard required')
        stamp=msg.header.stamp
        if type(stamp.sec) is not int or type(stamp.nanosec) is not int or not 0<=stamp.nanosec<1000000000:
            raise ValueError('invalid original odom timestamp')
        guard.observe(x=sample['x'],y=sample['y'],stamp_ns=stamp.sec*1000000000+stamp.nanosec,
                      source_now_ns=bridge._node.get_clock().now().nanoseconds,
                      frame_id=msg.header.frame_id,now=now)
    except Exception:
        try:guard.stop('odom_adapter_failed')
        except Exception:pass


def receive_odom(bridge, msg, *, station=None):
    """Capture the exact private parent BEFORE reading clocks or translating ROS input.

    Ledger's monotonic domain bounds the whole read. No parent at entry means no
    execution observation, even if another thread admits one during the read.
    Station motion retains its own original read bounds and the captured feed.
    """
    from core.bridge import translate
    fence = bridge._svc.command._execution_fence
    parent = None if fence is None else fence._ledger._current
    source = None if fence is None else fence._odometry
    source_stamp = None
    if source is not None:
        try:
            stamp = msg.header.stamp
            if (type(stamp.sec) is int and stamp.sec >= 0 and type(stamp.nanosec) is int
                    and 0 <= stamp.nanosec < 1_000_000_000):
                source_stamp = stamp.sec*1_000_000_000+stamp.nanosec
        except AttributeError:
            pass
    source_token, before = (None, None) if source is None else source.begin(source_stamp)
    feed = None if station is None else station.motion_feed
    read = None
    source_read = None
    motion_read = None if station is None else (feed, None, None, None)
    if parent is not None or feed is not None or source is not None:
        try:
            if source is None and parent is not None:
                before = fence._ledger._clock()
            local_at, source_at = (None, None) if feed is None else feed._read_start()
            source_now = bridge._node.get_clock().now().nanoseconds
            if parent is not None:
                read = fence, parent, before, source_now
            if source is not None:
                source_read = source, source_token, before, source_now
            if feed is not None:
                motion_read = feed, local_at, source_at, source_now
        except Exception:
            if source is not None:
                source.abort(source_token)
            if parent is not None:
                fence.request_stop(parent)
            if feed is not None:
                feed.clear()
    try:
        sample = translate.odom_sample(msg)
        observe_odom(bridge, msg, sample, station=station, _execution=read,
                     _motion_read=motion_read, _source_read=source_read)
        return sample
    except Exception:
        if source is not None:
            source.abort(source_token)
        if parent is not None:
            fence.request_stop(parent)
        if feed is not None:
            feed.clear()
        raise


def _original_odom(bridge, msg, sample, receipt):
    """One accepted state write, resolved planar frames and matching raw geometry."""
    stamp, frame, child = msg.header.stamp, msg.header.frame_id, msg.child_frame_id
    if (receipt is None or type(stamp.sec) is not int or stamp.sec < 0
            or type(stamp.nanosec) is not int or not 0 <= stamp.nanosec < 1_000_000_000
            or type(frame) is not str or frame.removeprefix(bridge._frame_prefix) != 'odom'
            or type(child) is not str or child.removeprefix(bridge._frame_prefix)
                not in ('base_link', 'base_footprint')):
        raise ValueError('unresolved original odometry')
    q, p = msg.pose.pose.orientation, msg.pose.pose.position
    values = (q.x, q.y, q.z, q.w, p.x, p.y, p.z)
    if (not all(type(v) in (int, float) and math.isfinite(v) for v in values)
            or abs(sum(v*v for v in values[:4])-1.) > .01 or abs(q.x) > 1e-6 or abs(q.y) > 1e-6):
        raise ValueError('invalid original planar odometry')
    yaw = math.atan2(2*(q.w*q.z+q.x*q.y), 1-2*(q.y*q.y+q.z*q.z))
    if (sample['x'] != p.x or sample['y'] != p.y
            or abs(math.atan2(math.sin(sample['yaw']-yaw), math.cos(sample['yaw']-yaw))) > 1e-6):
        raise ValueError('translated pose differs from original')
    return stamp.sec*1_000_000_000+stamp.nanosec, frame, child


def _observe_execution(bridge, msg, sample, read, receipt):
    """Adapt original planar odometry, never a state cache or receipt-age refresh."""
    from core_features.command._execution_budget import Pose
    fence, parent, before, source_now = read
    try:
        stamp_ns, frame, _ = _original_odom(bridge, msg, sample, receipt)
        _original_twist(msg, sample)
        pose = Pose(stamp_ns, source_now, frame, receipt[1], sample['x'], sample['y'])
        if not fence.observe(parent, pose, before_mono=before, after_mono=fence._ledger._clock()):
            fence.request_stop(parent)
    except Exception:
        fence.request_stop(parent)


def _original_twist(msg, sample):
    linear, angular = msg.twist.twist.linear, msg.twist.twist.angular
    values = (linear.x, linear.y, linear.z, angular.x, angular.y, angular.z)
    if (not all(type(v) in (int, float) and math.isfinite(v) for v in values)
            or any(abs(v) > 1e-6 for v in values[1:5])
            or sample['linear_x'] != linear.x or sample['angular_z'] != angular.z):
        raise ValueError('invalid original planar body velocity')
    return linear.x, angular.z


def _observe_source(bridge, msg, sample, read, receipt):
    source, token, before, source_now = read
    try:
        stamp, frame, child = _original_odom(bridge, msg, sample, receipt)
        linear, angular = _original_twist(msg, sample)
        return source.complete(token, receipt=receipt, stamp_ns=stamp, source_now_ns=source_now,
            frame=frame, child_frame=child, x=sample['x'], y=sample['y'], yaw=sample['yaw'],
            linear=linear, angular=angular, before_mono=before, after_mono=source._ledger._clock())
    except Exception:
        source.abort(token)
        return False


def observe_odom(bridge, msg, sample, *, station=None, _execution=None, _motion_read=None, _source_read=None):
    """RosBridge._on_odom's odom hand-over (D-758 0): the state snapshot stamps the pose (epoch from the
    message frame and header time) and the line-follow log keys the same sample on that stamp."""
    stamp = msg.header.stamp
    state = bridge._svc.state
    args = (sample['x'], sample['y'], sample['yaw'])
    kwargs = dict(frame=msg.header.frame_id, source_stamp_ns=stamp.sec*1_000_000_000+stamp.nanosec)
    receipt = None
    if _source_read is None and _execution is None and (_motion_read is None or _motion_read[0] is None):
        wall = state.set_odom_pose(*args, **kwargs)
    else:
        receipt = state._record_odom_pose(*args, **kwargs)
        wall = None if receipt is None else receipt[0]
        if _execution is not None:
            _observe_execution(bridge, msg, sample, _execution, receipt)
        if _source_read is not None:
            accepted = _observe_source(bridge, msg, sample, _source_read, receipt)
            if not accepted and _execution is not None:
                _execution[0].request_stop(_execution[1])
    if station is not None:
        observe_station_motion(bridge, msg, sample, station, _receipt=receipt, _read=_motion_read)
    observe_bounded_trial(bridge, msg, sample)
    observe_lane_return(bridge, msg, sample, wall=wall)


def observe_station_motion(bridge, msg, sample, station, *, _receipt=None, _read=None):
    """Only the same message's epoch/read bounds can become leased motion proof."""
    feed = station.motion_feed if _read is None else _read[0]
    if feed is None:
        return
    try:
        if _read is None or _receipt is None:
            raise ValueError('original station motion read required')
        stamp_ns, frame, child = _original_odom(bridge, msg, sample, _receipt)
        linear, angular = _original_twist(msg, sample)
        feed.observe(stamp_ns=stamp_ns, source_now_ns=_read[3],
            frame_id=frame.removeprefix(bridge._frame_prefix),
            child_frame_id=child.removeprefix(bridge._frame_prefix), odom_epoch=_receipt[1],
            measured_linear_m_s=linear, measured_angular_rad_s=angular,
            received_at=_read[1], source_received_at=_read[2])
    except Exception:
        feed.clear()


def observe_lane_return(bridge, msg, sample, *, now=None, wall=None):
    """Preserve the real odom source clock; never derive travel from issued twists. ``wall``: the
    stamp the state snapshot published for this sample (D-758 0: the odom log is found by it)."""
    line = bridge._svc.line_follow
    try:
        stamp = msg.header.stamp
        if (type(stamp.sec) is not int or stamp.sec < 0 or type(stamp.nanosec) is not int
                or not 0 <= stamp.nanosec < 1_000_000_000):
            raise ValueError("invalid original odometry timestamp")
        # Accepted body frames share the planar origin; other transforms need resolution.
        # Device bringup prefixes frames as robot.frame_prefix does (rosy_26/base_footprint).
        child = msg.child_frame_id.removeprefix(bridge._frame_prefix)
        if child not in ("base_link", "base_footprint"):
            raise ValueError("unresolved odometry body frame")
        q = msg.pose.pose.orientation
        values = (q.x, q.y, q.z, q.w)
        if (not all(type(v) in (int, float) and math.isfinite(v) for v in values)
                or abs(sum(v*v for v in values)-1.) > .01):
            raise ValueError("invalid original odometry rotation")
        yaw = yaw_from_quat(q)
        if abs(math.atan2(math.sin(yaw-sample["yaw"]), math.cos(yaw-sample["yaw"]))) > 1e-6:
            raise ValueError("translated yaw does not match original rotation")
        line.observe_return_pose(stamp_ns=stamp.sec*1_000_000_000+stamp.nanosec,
            source_now_ns=bridge._node.get_clock().now().nanoseconds,
            frame=msg.header.frame_id, x=sample["x"], y=sample["y"], yaw=sample["yaw"],
            received_at=bridge._line_clock() if now is None else now, wall=wall)
    except (AttributeError, KeyError, TypeError, ValueError):
        line.invalidate_return_pose()
