"""Explicitly installed source-authenticated station fact routes; never movement routes."""
from fastapi import Depends, Header, HTTPException

from core_common.protocol.station_charging import Identifier, StationObservation, StationPoseRecord


def install_station_routes(app, *, service, require_viewer):
    @app.get('/api/fleet/stations', dependencies=[Depends(require_viewer)], tags=['charging'])
    def stations():
        return {'stations': [record.model_dump(mode='json') for record in service.installations()]}


def install_station_ingress_routes(app, *, ingress, require_viewer):
    install_station_routes(app, service=ingress.stations, require_viewer=require_viewer)

    async def submit(method, authorization, body):
        try:
            return await method(authorization, body)
        except PermissionError as exc:
            raise HTTPException(401, detail={'code': 'UNAUTHORIZED'}) from exc
        except ValueError as exc:
            raise HTTPException(409, detail={'code': 'STATION_EVIDENCE_REJECTED'}) from exc
        except Exception as exc:
            # The HTTP boundary never exposes transport replies, credentials or DB details.
            raise HTTPException(503, detail={'code': 'STATION_FORWARD_UNAVAILABLE'}) from exc

    @app.post('/api/fleet/station-observations', tags=['charging'])
    async def station_observations(body: StationObservation, authorization: str | None = Header(default=None)):
        return await submit(ingress.observation, authorization, body)

    @app.post('/api/fleet/station-poses', tags=['charging'])
    async def station_poses(body: StationPoseRecord, authorization: str | None = Header(default=None)):
        return await submit(ingress.pose, authorization, body)

    @app.get('/api/fleet/station-observation-scope/{robot_id}', tags=['charging'])
    async def station_scope(robot_id: Identifier, authorization: str | None = Header(default=None)):
        return await submit(ingress.observation_scope, authorization, robot_id)
