"""Current station evidence view; callers hold the station owner's lock."""
import math

from core_common.protocol.station_charging import StationTargetStatus
from .parking import robot_in_dock_frame


def station_readback(owner):
    read_started = now = owner.source_clock()
    if owner.session is not None and owner.sensors is not None:
        owner.sensors.tick(owner)  # Immutable cache snapshots, never HTTP.
    valid, ack = False, None
    expiry = now+owner.profile.max_age_s
    if owner.session is not None:
        try:
            ack = owner.ack()
            expiry = min(expiry, owner.target.valid_until, ack.valid_until)
            if owner.motion_feed is not None:
                motion = owner.motion_feed.snapshot()
                if motion is None:
                    raise ValueError('STATION_MOTION_EXPIRED')
                expiry = min(expiry, motion['valid_until'])
            now = owner.source_clock()
            if expiry <= now:
                raise ValueError('STATION_EVIDENCE_EXPIRED')
            valid = True
        except ValueError:
            ack = None
    snapshot = owner.feed.relative_snapshot() if valid else None
    camera = snapshot[0] if snapshot is not None else None
    position_valid = False
    if camera is not None:
        x, y, heading = robot_in_dock_frame(camera.x, camera.y, camera.yaw, owner.profile.marker_offset_m)
        position_valid = (math.hypot(x, y) <= owner.profile.position_tolerance_m
                          and abs(heading) <= owner.profile.heading_tolerance_rad)
    if owner.session is not None and not position_valid and owner._seated_until is not None:
        owner.clear_charge_evidence('STATION_POSITION_NOT_VERIFIED')
    seated = (valid and owner._seated_until is not None and now < owner._seated_until
              and position_valid)
    charge = seated and owner._charge_until is not None and now < owner._charge_until
    if seated:
        expiry = min(expiry, owner._seated_until, snapshot[1])
    if charge:
        expiry = min(expiry, owner._charge_until)
    return_ready = bool(valid and owner.state == 'RETURNING' and owner._return_valid())
    return_permit = owner.return_authority.permit if return_ready else None
    if return_ready:
        expiry = min(expiry, return_permit.valid_until, owner.return_authority.lease_until,
            owner.source_clock()+owner.return_authority.deadline-owner.clock())
    departure, departure_expiry = owner.departure.status_fields() if owner.departure else ({}, None)
    expiry = expiry if valid else now+owner.profile.max_age_s
    expiry = min(expiry, departure_expiry) if departure_expiry is not None else expiry
    now = owner.source_clock()
    if (now < read_started or expiry <= now or ack is not None and ack.captured_at > now):
        if departure.get('departure_receipt') is not None:
            owner.departure.receipt_lost = True
        if departure.get('departure_permit') is not None:
            owner.departure.lost = True
        valid, ack, seated, charge, return_ready, return_permit = False, None, False, False, False, None
        departure, expiry = {}, now+owner.profile.max_age_s
    return StationTargetStatus(
        state=owner.state, reason=owner.reason,
        session_id=owner.session.session_id if owner.session else None,
        boot_id=owner.session.boot_id if owner.session else None,
        battery_id=owner.session.battery_id if owner.session else None,
        target=owner.target if valid else None, ack=ack,
        operation_id=str(owner._operation_id) if owner._operation_id else None,
        correlation_id=owner._correlation_id, binding_valid=valid, seating_verified=bool(seated),
        charging_verified=bool(charge and owner.state == 'CHARGING' and owner.charging.confirmed),
        completion_verified=bool(charge and owner.state == 'CHARGED_HOLD'),
        return_ready=return_ready, return_permit=return_permit,
        captured_at=now, valid_until=expiry, **departure)
