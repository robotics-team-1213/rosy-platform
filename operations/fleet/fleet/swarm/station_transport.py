"""Station and pack HTTP calls composed into the existing robot client."""
from core_common.protocol.station_charging import (
    StationTargetStatus, StationPoseAck, StationTargetBinding, StationDeparturePermit,
    StationDepartureReceipt, StationMotionCommand,
)
from core_common.protocol.native_operation import NativeOperation
from uuid import UUID


class StationTransport:
    async def station_navigation_state(self):
        return await self._get('/api/v1/navigation/state')

    async def docking_status(self, run_id=None):
        query = '' if run_id is None else '?run_id='+str(UUID(str(run_id)))
        return await self._get('/api/v1/docking/status'+query)

    async def station_dock(self, command):
        body = await self._post('/api/v1/docking/station-dock', command.model_dump(mode='json'))
        return NativeOperation.model_validate(body['operation'])

    async def station_stop(self, command):
        return await self._post('/api/v1/docking/station-stop', command.model_dump(mode='json'))

    async def station_undock(self, permit):
        permit = StationDeparturePermit.model_validate(permit.model_dump())
        body = await self._post('/api/v1/docking/station-undock', permit.model_dump(mode='json'))
        return NativeOperation.model_validate(body['operation'])

    async def station_departure(self, permit):
        permit = StationDeparturePermit.model_validate(permit.model_dump())
        body = await self._mutate('/api/v1/docking/station-departure', permit.model_dump(mode='json'), method='PUT')
        if body.get('accepted') is not True:
            raise ValueError('STATION_DEPARTURE_PERMISSION_UNACKNOWLEDGED')
        return body

    async def station_departure_finish(self, command):
        command = StationMotionCommand.model_validate(command.model_dump())
        body = await self._post('/api/v1/docking/station-departure/finish', command.model_dump(mode='json'))
        return StationDepartureReceipt.model_validate(body)

    async def station_bind(self, binding):
        binding = StationTargetBinding.model_validate(binding)
        body = await self._mutate('/api/v1/docking/station-target', binding.model_dump(mode='json'), method='PUT')
        return StationPoseAck.model_validate(body)

    async def station_return(self, permit):
        body = await self._mutate('/api/v1/docking/station-return', permit.model_dump(mode='json'), method='PUT')
        return StationTargetStatus.model_validate(body)

    async def station_return_finish(self, command):
        return StationPoseAck.model_validate(await self._post('/api/v1/docking/station-return/finish',
                                                            command.model_dump(mode='json')))

    async def power_health(self) -> dict:
        return await self._get('/api/v1/power/health')

    async def motor_health(self) -> dict:
        return await self._get('/api/v1/motors/health')

    async def station_target(self):
        return StationTargetStatus.model_validate(await self._get('/api/v1/docking/station-target'))

    async def station_observation(self, observation):
        return await self._post('/api/v1/docking/station-observation', observation.model_dump(mode='json'))
