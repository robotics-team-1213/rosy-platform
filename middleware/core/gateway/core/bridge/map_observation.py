"""Original occupancy callback and lifecycle handover; render is a separate read path."""
from core.bridge import map_pose, translate
from core_features.maps import occupancy_map_id
from core_features.navigation.map_evidence import GridContent, MAX_CELLS


def _stamp(stamp):
    if (type(stamp.sec) is not int or stamp.sec < 0 or type(stamp.nanosec) is not int
            or not 0 <= stamp.nanosec < 1_000_000_000):
        raise ValueError('invalid original map timestamp')
    return stamp.sec*1_000_000_000+stamp.nanosec


def _original(msg):
    info = msg.info
    if (type(info.width) is not int or type(info.height) is not int
            or min(info.width, info.height) <= 0 or info.width*info.height > MAX_CELLS):
        raise ValueError('original map exceeds supported grid bounds')
    if len(msg.data) != info.width*info.height:
        raise ValueError('original map data length mismatch')
    p, q = info.origin.position, info.origin.orientation
    return GridContent(msg.header.frame_id, info.width, info.height, info.resolution,
        (p.x, p.y, p.z, q.x, q.y, q.z, q.w), tuple(msg.data),
        _stamp(msg.header.stamp), _stamp(info.map_load_time))


def receive_map(bridge, msg, *, warn):
    svc = bridge._svc
    source = svc.nav._map_evidence
    fence = svc.command._execution_fence
    parent = None if fence is None else fence._ledger._current
    if source is not None and parent is not None:
        fence.request_stop(parent)
    token = None
    if source is not None:
        # Conservative policy: EVERY map delivery stops the exact captured
        # parent before parsing/hash, even a subsequently identical static map.
        try:
            stamp, load = _stamp(msg.header.stamp), _stamp(msg.info.map_load_time)
        except Exception:
            stamp = load = None
        token = source.begin(stamp, load)
    map_pose.invalidate_map_pose(bridge)
    try:
        if source is not None and not source.complete(token, _original(msg)):
            return False
        grid = translate.grid_from_occupancy(msg)
        current = svc.state.map_id
        map_id = occupancy_map_id(grid) if current is None or str(current).startswith('occupancy:') else current
        svc.maps.set_map(grid, map_id=map_id)
        if map_id != current:
            svc.state.set_map_id(map_id)
        return True
    except Exception as exc:
        if source is not None:
            source.abort(token)
        warn(f'ignored occupancy map: {exc}')
        return False


def lifecycle(bridge, active):
    svc = bridge._svc
    source = svc.nav._map_evidence
    fence = svc.command._execution_fence
    parent = None if fence is None else fence._ledger._current
    if source is not None and parent is not None:
        fence.request_stop(parent)
    if source is not None:
        source.lifecycle(active)
    map_pose.invalidate_map_pose(bridge)
