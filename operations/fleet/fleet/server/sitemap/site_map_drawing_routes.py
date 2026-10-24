"""Named-operator drawing writes; existing read guard for rendered projections."""
import asyncio
from pathlib import Path
import tempfile

from fastapi import Depends, HTTPException, Request
from fastapi.responses import FileResponse

from core_common.protocol.site_drawing import DrawingTransform
from fleet.server.site_map_assets import drawing_error
from fleet.server.site_map_projection import MAX_SOURCE_BYTES
from fleet.server.site_map_store import SiteMapError


def install_site_map_drawing_routes(app, *, assets, read_guard, require_named_operator):
    def available():
        if assets is None:
            raise drawing_error(503, 'UNAVAILABLE', 'persistent map assets are not configured')
        return assets

    async def converted(function, *args):
        task = asyncio.create_task(asyncio.to_thread(function, *args))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            assets.cancel_worker()
            try:
                await asyncio.shield(task)
            except SiteMapError:
                pass
            raise

    def fail(exc):
        return HTTPException(exc.status_code, detail={'code': exc.code, 'detail': {'message': str(exc)}})

    def take_slot():
        available()
        if not assets.slot.acquire(blocking=False):
            raise drawing_error(429, 'BUSY', 'another drawing upload or conversion is running')
        assets.cancelled.clear()

    @app.post('/api/fleet/site-map/drawings', tags=['site-map'])
    async def drawing_upload(request: Request, principal=Depends(require_named_operator)):
        acquired, temporary = False, None
        try:
            take_slot()
            acquired = True
            with tempfile.NamedTemporaryFile(dir=assets.root, suffix='.tmp', delete=False) as stream:
                temporary = Path(stream.name)
                size = 0
                async with asyncio.timeout(60):
                    async for chunk in request.stream():
                        size += len(chunk)
                        if size > MAX_SOURCE_BYTES:
                            raise drawing_error(413, 'LIMIT', 'STL source exceeds 16 MiB')
                        stream.write(chunk)
            result = await converted(assets.put_stl, temporary)
            app.state.site_maps.record_event('drawing_uploaded', principal.principal_id,
                                              {'asset_sha256': result['asset_sha256'], 'result': 'stored'})
            return result
        except TimeoutError as exc:
            raise fail(drawing_error(503, 'UNAVAILABLE', 'drawing upload timed out')) from exc
        except OSError as exc:
            raise fail(drawing_error(507, 'STORAGE', 'drawing could not be stored')) from exc
        except SiteMapError as exc:
            if assets is not None:
                app.state.site_maps.record_event('drawing_upload_failed', principal.principal_id,
                                                {'result': exc.code})
            raise fail(exc) from exc
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            if acquired:
                assets.slot.release()

    @app.post('/api/fleet/site-map/drawings/{asset_sha256}/projections', tags=['site-map'])
    async def drawing_project(asset_sha256: str, transform: DrawingTransform,
                              principal=Depends(require_named_operator)):
        acquired = False
        try:
            take_slot()
            acquired = True
            result = await converted(assets.project, asset_sha256, transform)
            app.state.site_maps.record_event('drawing_projected', principal.principal_id,
                {k: result[k] for k in ('asset_sha256', 'projection_sha256')})
            return result
        except SiteMapError as exc:
            raise fail(exc) from exc
        finally:
            if acquired:
                assets.slot.release()

    @app.get('/api/fleet/site-map/drawing-projections/{projection_sha256}', dependencies=read_guard,
             tags=['site-map'])
    def drawing_projection(projection_sha256: str):
        try:
            return available().projection(projection_sha256)
        except SiteMapError as exc:
            raise fail(exc) from exc

    @app.get('/api/fleet/site-map/drawings/{asset_sha256}/source', tags=['site-map'])
    def drawing_source(asset_sha256: str, principal=Depends(require_named_operator)):
        try:
            source = available().source(asset_sha256)
            return FileResponse(source, media_type='application/octet-stream', filename=asset_sha256 + '.stl',
                                headers={'X-Content-Type-Options': 'nosniff'})
        except SiteMapError as exc:
            raise fail(exc) from exc
