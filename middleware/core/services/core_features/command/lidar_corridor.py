"""Read-only straight-travel observation at the native LiDAR scan plane."""
import math
import sys

from core_common.robot_body import SWEEP_PAD_M


def _finite(value):
    # Comparing before conversion also rejects integers outside the sensor float range.
    return type(value) in (int, float) and -sys.float_info.max <= value <= sys.float_info.max


def assess_straight_corridor(sample, config, tray, robot_id, direction, distance_m, now):
    """Inspect every native beam covering the leading body strip, including the tray.

    This is scan-plane evidence for a short straight translation. It does not
    identify peers, observe obstacles below the scanner or authorize motion.
    """
    sample = sample or {}
    frame, stamp, received = (sample.get(k) for k in ("frame_id", "source_stamp_ns", "received_at"))
    receipt = dict(kind="native_lidar_straight_corridor_v1", robot_id=robot_id, direction=direction,
                   distance_m=distance_m, frame_id=frame if isinstance(frame, str) else None,
                   source_stamp_ns=stamp if type(stamp) is int and stamp > 0 else None,
                   received_at=received if _finite(received) else None, checked_at=now,
                   required_beams=0, observed_beams=0)

    def result(reason, status="unknown"):
        return dict(receipt, status=status, reason=reason)

    if not sample:
        return result("scan_missing")
    if frame not in ("rplidar_link", f"{robot_id}/rplidar_link"):
        return result("frame_mismatch")
    source_now = sample.get("source_now_ns")
    if (not _finite(received) or type(stamp) is not int or stamp <= 0 or type(source_now) is not int
            or source_now < stamp or now < received or now - received + (source_now - stamp) * 1e-9 > .2):
        return result("scan_stale")
    if config is None or not config.body_stop_known or tray is None:
        return result("body_unknown")
    front, rear, width, radius, mount = (config.body_front_x_m, config.body_rear_x_m,
        config.body_half_width_m, config.body_rotation_radius_m, config.body_lidar_x_m)
    if (not all(_finite(v) for v in (front, rear, width, radius, mount, *tray, config.lidar_forward_deg))
            or not rear < mount < front or not rear < 0 < front or not 0 < width < radius or min(tray) <= 0):
        return result("body_unknown")
    if direction not in ("forward", "reverse") or not _finite(distance_m) or not 0 < distance_m <= .03:
        return result("scan_invalid")
    ranges = sample.get("ranges")
    low, high, start, end, step = (sample.get(k) for k in
        ("range_min", "range_max", "angle_min", "angle_max", "angle_increment"))
    if (not isinstance(ranges, (tuple, list)) or not 180 <= len(ranges) <= 16384
            or not all(_finite(v) for v in (low, high, start, end, step)) or not 0 < low < high
            or step == 0 or abs((end - start) - (len(ranges) - 1) * step) > .05 * abs(step)
            or not 2*math.pi - .05*abs(step) <= abs(step)*len(ranges) <= 2*math.pi + 1.05*abs(step)):
        return result("scan_invalid")

    sign = 1 if direction == "forward" else -1
    # The rounded body starts sweeping at its leading edge at each y. Use
    # the innermost such edge and the outermost tray extent to bound them all.
    edge = front if sign > 0 else -rear
    near = min(edge, math.sqrt(radius*radius-width*width)) - sign*mount
    half = max(width, tray[2]) + SWEEP_PAD_M
    far = max(edge, tray[0] if sign > 0 else tray[1]) - sign*mount + distance_m + SWEEP_PAD_M
    # A short minimum range is also fully covered when its entire disk is
    # inside the known chassis rectangle and rotation circle. At the rounded
    # rear corners the axial projection alone underestimates that distance.
    inscribed = min(front - mount, mount - rear, width, radius - abs(mount))
    if near <= 0 or low > max(near, inscribed):
        return result("blind_range")
    sector = math.atan2(half, near) + abs(step)
    reach = math.hypot(far, half)
    yaw = math.radians(config.lidar_forward_deg)
    # Configuration uses signed body-frame degrees. Validate the entire mask
    # before reading it so damaged geometry cannot silently remove an occluder.
    masks = config.lidar_self_mask
    if not isinstance(masks, (list, tuple)) or any(
            not isinstance(m, (tuple, list)) or len(m) != 3 or not all(_finite(x) for x in m)
            or not -180 <= m[0] <= m[1] <= 180 or m[2] < 0 for m in masks):
        return result("body_unknown")
    reasons = set()
    for index, value in enumerate(ranges):
        angle = math.remainder(start + index*step - yaw, 2*math.pi)
        bearing = math.remainder(angle - (0 if sign > 0 else math.pi), 2*math.pi)
        if abs(bearing) > sector:
            continue
        receipt["required_beams"] += 1
        if any(abs(math.remainder(math.degrees(angle) - (lo + hi)/2, 360.)) <= (hi - lo)/2 + abs(math.degrees(step))
               and mask_reach >= near for lo, hi, mask_reach in masks):
            reasons.add("masked_sector")
        elif not _finite(value) or not low <= value <= high:
            reasons.add("unobserved_sector")
        elif value <= reach:
            longitudinal, lateral = value*math.cos(bearing), value*math.sin(bearing)
            if (longitudinal <= max(edge, tray[0] if sign > 0 else tray[1]) - sign*mount
                    and abs(lateral) <= max(width, tray[2])):
                reasons.add("occluded_sector")
            elif near <= longitudinal <= far and abs(lateral) <= half:
                reasons.add("obstacle_in_corridor")
            else:
                reasons.add("occluded_sector")
        else:
            receipt["observed_beams"] += 1
    for reason in ("obstacle_in_corridor", "masked_sector", "unobserved_sector", "occluded_sector"):
        if reason in reasons:
            return result(reason, "blocked" if reason == "obstacle_in_corridor" else "unknown")
    if not receipt["required_beams"]:
        return result("unobserved_sector")
    return result("required_sector_observed", "observed_clear")
