"""Explicit station-session composition; measured device activation remains closed."""
import time

from core_common.protocol.native.receipts import BOOT_ID
from core_features.docking.station_owner import StationControlProfile, StationDockingOwner
from core_features.docking.station_sensors import StationSensorReader
from core_features.docking.station_motion import StationMotionFeed
from core_features.docking.station_departure import StationDepartureProfile, StationDepartureFeed, StationDepartureController


def build_station_owner(docking, *, config, runtime_mode, state, modes, safety, battery):
    if not isinstance(config, dict) or config.get('enabled') is not True:
        return None
    if runtime_mode != 'simulation':
        raise ValueError('STATION_DEVICE_ACCEPTANCE_REQUIRED')
    if not isinstance(config.get('profile'), dict):
        raise ValueError('STATION_CONTROL_PROFILE_REQUIRED')
    profile = StationControlProfile.model_validate(config['profile'])
    map_revision = config.get('map_revision')
    if not isinstance(map_revision, str) or not map_revision:
        raise ValueError('STATION_MAP_SCOPE_REQUIRED')
    motion_feed = StationMotionFeed(clock=docking.now, source_clock=time.time, max_age_s=profile.sample_max_age_s)

    def local_scope(*, wait=False):
        current = state.station_scope(max_age_s=profile.sample_max_age_s, wait=wait)
        if current is None:
            return None
        motion = motion_feed.snapshot()
        current['odom_fresh'] = (current['odom_fresh'] is True and motion is not None
                                 and motion['odom_epoch'] == current['odom_epoch'])
        return current | dict(boot_id=str(BOOT_ID), battery_id=profile.battery_id,
                              map_revision=map_revision, mode=modes.mode.value, safety_latched=safety.estop)

    owner = StationDockingOwner(
        docking, profile=profile, local_scope=lambda: local_scope(wait=True),
        local_scope_nowait=local_scope, clock=docking.now, source_clock=time.time, battery=battery)
    owner.sensors = StationSensorReader(
        motion_sample=motion_feed.snapshot,
        battery_health=battery.health, clock=docking.now, source_clock=time.time)
    owner.motion_feed = motion_feed
    if 'departure_profile' in config:
        departure_profile = StationDepartureProfile.model_validate(config['departure_profile'])
        if (departure_profile.station_id != profile.station_id or departure_profile.battery_id != profile.battery_id):
            raise ValueError('STATION_DEPARTURE_PROFILE_SCOPE_MISMATCH')
        owner.departure = StationDepartureController(owner, feed=StationDepartureFeed(
            profile=departure_profile, clock=docking.now, source_clock=time.time))
    return owner
