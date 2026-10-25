"""Independent, bounded collection loop and scoped, cache-only read API."""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import time

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

from .cache import ObservationCache, ObservationRejected
from .sources import SourceReader
from .store import StoreUnavailable


def _error(status, code):
    return JSONResponse({'error': {'code': code}}, status_code=status)


class Collector:
    def __init__(self, config, credentials, store):
        self.config, self.credentials, self.store = config, credentials, store
        self.cache = ObservationCache(config, store=store)
        self.reader = SourceReader(self.cache, credentials)
        self.storage_failures = set()
        self.task = None

    @property
    def unavailable(self):
        return bool(self.storage_failures) or self.task is not None and self.task.done()

    async def poll_once(self):
        semaphore = asyncio.Semaphore(8)
        async def poll(source):
            async with semaphore:
                try:
                    await self.reader.poll(source)
                    self.storage_failures.discard(source.id)
                    self.cache.collection_failure(source.id)
                except StoreUnavailable:
                    self.storage_failures.add(source.id)
                except ObservationRejected as error:
                    self.cache.collection_failure(source.id, error.reason_code)
                except ValueError:
                    self.cache.collection_failure(source.id, 'MONITORING_PROTOCOL')
        await asyncio.gather(*(poll(source) for source in self.config.sources))
        try:
            self.cache.checkpoint()
            self.storage_failures.discard('checkpoint')
        except StoreUnavailable:
            self.storage_failures.add('checkpoint')

    async def run(self):
        while True:
            started = time.monotonic()
            await self.poll_once()
            await asyncio.sleep(max(0.1, 5.0 - (time.monotonic() - started)))


def create_app(collector: Collector, *, web_root: Path | None = None):
    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(collector.run())
        collector.task = task
        try:
            yield
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            collector.store.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware('http')
    async def private_responses(request, call_next):
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; frame-ancestors 'none'"
        return response

    def principal(request):
        values = request.headers.getlist('authorization')
        if len(values) != 1 or not values[0].startswith('Bearer '):
            return None
        return collector.credentials.authorize(values[0][7:])

    @app.get('/health')
    async def health():
        return JSONResponse({'status': 'unavailable' if collector.unavailable else 'ready'},
                            status_code=503 if collector.unavailable else 200)

    @app.get('/api/monitoring/v1/snapshot')
    async def snapshot(request: Request):
        reader = principal(request)
        if reader is None:
            return _error(401, 'MONITORING_AUTH')
        if set(request.query_params) - {'site_id'}:
            return _error(400, 'MONITORING_QUERY')
        sites = frozenset(request.query_params.getlist('site_id')) or reader.sites
        if not sites <= reader.sites:
            return _error(403, 'MONITORING_SCOPE')
        if collector.storage_failures:
            return _error(503, 'MONITORING_STORAGE')
        if collector.unavailable:
            return _error(503, 'MONITORING_UNAVAILABLE')
        try:
            value = collector.cache.snapshot(sites)
        except (ObservationRejected, ValueError):
            return _error(503, 'MONITORING_UNAVAILABLE')
        return JSONResponse(value.model_dump(mode='json'))

    @app.get('/api/monitoring/v1/sites/{site_id}/events')
    async def events(site_id: str, request: Request):
        reader = principal(request)
        if reader is None:
            return _error(401, 'MONITORING_AUTH')
        if site_id not in reader.sites:
            return _error(403, 'MONITORING_SCOPE')
        if set(request.query_params) - {'after', 'limit'} or any(
                len(request.query_params.getlist(key)) != 1 for key in request.query_params):
            return _error(400, 'MONITORING_QUERY')
        try:
            after = request.query_params.get('after', '0')
            limit = request.query_params.get('limit', '100')
            if (len(after) > 19 or len(limit) > 3 or not after.isascii() or not after.isdecimal()
                    or not limit.isascii() or not limit.isdecimal()):
                raise ValueError()
            after, limit = int(after), int(limit)
            if after > 2**63 - 1 or not 1 <= limit <= 200:
                raise ValueError()
        except ValueError:
            return _error(400, 'MONITORING_QUERY')
        try:
            rows = collector.store.events(site_id, after=after, limit=limit)
        except StoreUnavailable:
            return _error(503, 'MONITORING_STORAGE')
        return {'events': rows, 'next_after': rows[-1]['sequence'] if rows else after}

    if web_root is not None:
        root = Path(web_root).resolve(strict=True)
        assets = {'/': 'index.html', '/monitoring.js': 'monitoring.js', '/monitoring.css': 'monitoring.css',
                  **{f'/common/{name}': f'common/{name}' for name in (
                      'tokens.css', 'components.css', 'app-shell.css', 'theme.js', 'core_ui_logic.js')}}
        for route, name in assets.items():
            path = (root / name).resolve(strict=True)
            if not path.is_relative_to(root) or not path.is_file():
                raise ValueError('monitoring web assets unavailable')
            def asset_handler(asset_path):
                async def asset():
                    return FileResponse(asset_path)
                return asset
            app.add_api_route(route, asset_handler(path), methods=['GET'])
    return app
