"""Bound station images become relative observations; only Fleet supplies session scope."""
import asyncio
import inspect
import math

from pydantic import TypeAdapter
from core_common.protocol.station_charging import Identifier, StationObservation
from .station_observation import StationCameraCalibration, observe_jpeg


def create_station_worker(*, calibration, robot_id, ingest, rectify, publisher, clock, max_age_s):
    """Explicit station-local composition; the installed camera needs no global map projection."""
    from .worker import VisionWorker

    robot_id = TypeAdapter(Identifier).validate_python(robot_id)
    processor = StationFrameProcessor(calibration=calibration,
        scope=lambda: publisher.station_scope(robot_id), rectify=rectify, publisher=publisher,
        clock=clock, max_age_s=max_age_s)
    return VisionWorker(source_id=processor.source_id, ingest=ingest, camera=None,
        publisher=publisher, clock=clock, max_age_s=max_age_s, station=processor)


class StationFrameProcessor:
    def __init__(self, *, calibration, scope, rectify, publisher, clock, max_age_s):
        if (isinstance(max_age_s, bool) or not isinstance(max_age_s, (int, float))
                or not math.isfinite(max_age_s) or max_age_s <= 0 or not callable(rectify)
                or not isinstance(calibration, StationCameraCalibration) or not callable(scope)):
            raise ValueError('STATION_MEASURED_FRAME_PROFILE_REQUIRED')
        self.calibration, self.scope, self.rectify = calibration, scope, rectify
        self.publisher, self.clock, self.max_age_s = publisher, clock, max_age_s

    @property
    def source_id(self):
        return self.calibration.source_id

    async def _current_scope(self, timeout_s):
        if timeout_s <= 0:
            return None
        scope = self.scope()
        if inspect.isawaitable(scope):
            scope = await asyncio.wait_for(scope, timeout=timeout_s)
        if scope is None:
            return None
        try:
            scope = StationObservation.model_validate(scope.model_dump(), context={'now': self.clock()})
            if ((scope.station_id, scope.source_id, scope.source_epoch, scope.calibration_revision)
                    != (self.calibration.station_id, self.calibration.source_id,
                        self.calibration.source_epoch, self.calibration.revision)):
                return None
            return scope
        except (ValueError, TypeError, AttributeError):
            return None

    async def process(self, frame, *, source_id):
        if source_id != self.source_id:
            raise ValueError('STATION_FRAME_SOURCE_MISMATCH')
        scope = await self._current_scope(1.5)
        if scope is None:
            return False
        try:
            body = StationObservation.model_validate(scope.model_dump() | dict(
                captured_at=frame.captured_at, valid_until=min(scope.valid_until, frame.captured_at+self.max_age_s),
                sequence=frame.header.seq, pose=None, visible=False), context={'now': self.clock()})
        except (ValueError, TypeError):
            return False

        def measure():
            try:
                jpeg = self.rectify(frame.jpeg)  # Installed measurement transform, never viewer settings.
            except Exception:
                return body  # Known scope but unavailable image explicitly revokes visibility.
            return observe_jpeg(jpeg, calibration=self.calibration, template=body)

        remaining = body.valid_until-self.clock()
        if remaining <= 0:
            return False
        try:
            measured = await asyncio.wait_for(asyncio.to_thread(measure), timeout=remaining)
            measured = StationObservation.model_validate(measured.model_dump(), context={'now': self.clock()})
        except (ValueError, TypeError, asyncio.TimeoutError):
            return False
        current = await self._current_scope(measured.valid_until-self.clock())
        if current is None or any(getattr(current, field) != getattr(measured, field) for field in (
                'robot_id', 'station_id', 'session_id', 'boot_id', 'odom_epoch', 'map_id', 'map_revision',
                'pose_revision', 'source_id', 'source_epoch', 'calibration_revision')):
            return False
        measured = measured.model_copy(update={'valid_until': min(measured.valid_until, current.valid_until)})
        now = self.clock()
        remaining = measured.valid_until-now
        if not measured.captured_at <= now < measured.valid_until:
            return False
        result = await asyncio.wait_for(self.publisher.publish_station_observation(measured), timeout=remaining)
        return isinstance(result, dict) and result.get('accepted') is True
