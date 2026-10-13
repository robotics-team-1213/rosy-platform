"""ROS-free publication cadence for D-531 route context."""


def publication(context, previous, last_at, *, now):
    """Return (wire message, active identity, publication time)."""
    if now < last_at:
        return ({"v": 1, "seq": None} if previous is not None else None), None, now
    if context is None:
        return ({"v": 1, "seq": None} if previous is not None else None), None, now
    key = (context.seq, context.kind, context.place_id, context.map_id)
    if key != previous or now - last_at >= 0.2:
        return context.message(), key, now
    return None, previous, last_at
