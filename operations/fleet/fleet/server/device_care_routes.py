"""Profile reads precede actions; writes record care without changing live safety state."""
import json
import sqlite3

from fastapi import Depends, Header, HTTPException, Request, Response

from .device_care import DeviceCareStore
from rosy.contracts.motion.characteristics import parse_json


def install_device_care_routes(app, path, *, console, observations, require_viewer, require_named_operator):
    store = DeviceCareStore(path)
    app.state.device_care = store

    def sources():
        rows = [{'source_kind': 'robot', 'source_id': key, 'label': key, 'owner_id': None}
                for key in console.robot_ids] if console is not None else []
        if observations is not None:
            rows.extend({'source_kind': 'arm', 'source_id': arm['source_id'], 'label': arm['label'],
                         'owner_id': arm['arm_id']}
                        for cell in observations.snapshot()['workcells'] for arm in cell['arms'])
        return rows

    def call(operation, *args, **kwargs):
        try:
            return operation(*args, **kwargs)
        except (ValueError, TypeError, RecursionError):
            raise HTTPException(422, detail={'code': 'INVALID_DEVICE_CARE'}) from None
        except sqlite3.Error:
            raise HTTPException(503, detail={'code': 'DEVICE_PROFILE_STORAGE_UNAVAILABLE'}) from None

    async def body(request, limit=1_000_000):
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > limit:
                raise HTTPException(413, detail={'code': 'DEVICE_CARE_TOO_LARGE'})
            data.extend(chunk)

        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise ValueError('duplicate field')
                result[key] = value
            return result

        def reject(value):
            raise ValueError('nonfinite number')

        return call(json.loads, data, object_pairs_hook=pairs, parse_constant=reject)

    @app.get('/api/fleet/device-profile-sources', tags=['fleet'])
    def catalog(_principal=Depends(require_viewer)):
        return {'sources': sources()}

    @app.get('/api/fleet/device-profile-sources/{kind}/{source_id}', tags=['fleet'])
    def source_profile(kind: str, source_id: str, response: Response, _principal=Depends(require_viewer)):
        response.headers['Cache-Control'] = 'no-store'
        return {'profile': call(store.by_source, kind, source_id)}

    @app.get('/api/fleet/device-profiles/{device_id}/care', tags=['fleet'])
    def get_care(device_id: str, response: Response, _principal=Depends(require_viewer)):
        response.headers['Cache-Control'] = 'no-store'
        return call(store.get, device_id)

    @app.put('/api/fleet/device-profiles/{device_id}/care', tags=['fleet'])
    async def put_care(device_id: str, request: Request, principal=Depends(require_named_operator)):
        data = await body(request)
        if not isinstance(data, dict):
            raise HTTPException(422, detail={'code': 'INVALID_DEVICE_CARE'})
        if data.get('source_id') is not None:
            source = next((row for row in sources() if (row['source_kind'], row['source_id']) == (
                data.get('source_kind'), data['source_id'])), None)
            if source is None:
                raise HTTPException(422, detail={'code': 'UNKNOWN_PROFILE_SOURCE'})
            document = data.get('characteristics')
            if isinstance(document, str):
                document = call(parse_json, document)
            if document is not None and (not isinstance(document, dict)
                                         or not isinstance(document.get('binding'), dict)
                                         or document['binding'].get('owner_id') != source['owner_id']):
                raise HTTPException(422, detail={'code': 'PROFILE_OWNER_MISMATCH'})
        return call(store.put, device_id, data, actor=principal.principal_id)

    @app.post('/api/fleet/device-profiles/{device_id}/events', tags=['fleet'])
    async def event(device_id: str, request: Request, principal=Depends(require_named_operator)):
        return call(store.add_event, device_id, await body(request, 16384), actor=principal.principal_id)

    @app.post('/api/fleet/device-profiles/{device_id}/load-reports/{source_id}', status_code=202, tags=['fleet'])
    async def report(device_id: str, source_id: str, request: Request,
                     token: str | None = Header(None, alias='X-Workcell-Observation-Token')):
        if observations is None:
            raise HTTPException(503, detail={'code': 'WORKCELL_OBSERVATIONS_UNAVAILABLE'})
        try:
            observations.authorize(source_id, token)
        except PermissionError:
            raise HTTPException(401, detail={'code': 'WORKCELL_OBSERVATION_UNAUTHORIZED'}) from None
        return call(store.ingest, device_id, source_id, await body(request, 65536))
