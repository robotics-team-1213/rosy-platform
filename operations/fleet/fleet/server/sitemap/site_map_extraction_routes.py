"""Named-operator extraction shares the bounded drawing worker slot, not map writers."""
import asyncio

from fastapi import Depends, Request
from pydantic import ValidationError

from core_common.protocol.site_drawing import DrawingExtractionRequest
from fleet.server.site_map_store import SiteMapError
from fleet.server.site_map_assets import drawing_error


def install_extraction_routes(app, *, assets, read_guard, require_named_operator, converted, take_slot, fail):
    path = '/api/fleet/site-map/drawing-projections/{projection_sha256}/extractions'

    @app.post(path, tags=['site-map'])
    async def extract(projection_sha256: str, request: Request,
                      principal=Depends(require_named_operator)):
        acquired = False
        try:
            take_slot()
            acquired = True
            from fleet.server.site_map_routes import _bounded_body
            async with asyncio.timeout(10):
                spec = DrawingExtractionRequest.model_validate_json(await _bounded_body(request))
            result = await converted(assets.extract, projection_sha256, spec)
            app.state.site_maps.record_event('drawing_extracted', principal.principal_id,
                {key: result[key] for key in ('asset_sha256', 'projection_sha256', 'extraction_sha256')})
            return result
        except SiteMapError as exc:
            raise fail(exc) from exc
        except ValidationError as exc:
            raise fail(drawing_error(422, 'INVALID', 'invalid extraction request')) from exc
        except TimeoutError as exc:
            raise fail(drawing_error(503, 'UNAVAILABLE', 'extraction request timed out')) from exc
        finally:
            if acquired:
                assets.slot.release()

    @app.get('/api/fleet/site-map/drawing-extractions/{extraction_sha256}', dependencies=read_guard,
             tags=['site-map'])
    def read_extraction(extraction_sha256: str):
        try:
            if assets is None:
                raise drawing_error(503, 'UNAVAILABLE', 'persistent map assets are not configured')
            return assets.extraction(extraction_sha256)
        except SiteMapError as exc:
            raise fail(exc) from exc

    @app.post('/api/fleet/site-map/drawing-extractions/{extraction_sha256}/validate', tags=['site-map'])
    async def validate_candidate(extraction_sha256: str, request: Request,
                                 principal=Depends(require_named_operator)):
        from fleet.server.site_map_routes import DraftRequest, _bounded_body
        try:
            if assets is None:
                raise drawing_error(503, 'UNAVAILABLE', 'persistent map assets are not configured')
            result = assets.extraction(extraction_sha256)
            async with asyncio.timeout(10):
                candidate = DraftRequest.model_validate_json(await _bounded_body(request)).map
            if (candidate.drawing is None or candidate.drawing.projection_sha256 != result['projection_sha256']
                    or candidate.drawing.asset_sha256 != result['asset_sha256']):
                raise drawing_error(422, 'INVALID', 'candidate and extraction drawing must match')
            assets.validate_reference(candidate.drawing, candidate.survey.revision if candidate.survey else None)
            return {'map': candidate.body()}
        except SiteMapError as exc:
            raise fail(exc) from exc
        except ValidationError as exc:
            raise fail(drawing_error(422, 'INVALID', 'candidate geometry or references are invalid')) from exc
        except TimeoutError as exc:
            raise fail(drawing_error(503, 'UNAVAILABLE', 'candidate validation timed out')) from exc
