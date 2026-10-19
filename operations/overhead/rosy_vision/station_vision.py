"""Installed station measurement lifespan; existing ingest and source-only clients."""
import asyncio
from contextlib import AsyncExitStack
import logging
import time

from .ingest import IngestServer
from .publish import SightingPublisher

logger = logging.getLogger('rosy_vision')


class StationVisionServer:
    def __init__(self, installation, *, host, port, ssl_context=None, clock=time.time,
                 publisher_factory=SightingPublisher):
        self.installation, self.host, self.port = installation, host, port
        self.ssl_context, self.clock = ssl_context, clock
        self.publisher_factory = publisher_factory
        sources = installation.sources
        self.ingest = IngestServer({s.profile.calibration.source_id: s.phone_token.get_secret_value() for s in sources},
            measurement_sources=frozenset(s.profile.calibration.source_id for s in sources),
            source_widths={s.profile.calibration.source_id: s.profile.lens.width for s in sources})
        self.server, self._stack, self._tasks = None, None, []

    async def __aenter__(self):
        stack = AsyncExitStack()
        self._stack = stack
        try:
            workers = []
            for source in self.installation.sources:
                publisher = await stack.enter_async_context(self.publisher_factory(
                    source.profile.fleet_base_url, source.token.get_secret_value()))
                workers.append(source.create_worker(ingest=self.ingest, publisher=publisher, clock=self.clock))
            self.server = await self.ingest.start(self.host, self.port, ssl_context=self.ssl_context)
            self._tasks = [asyncio.create_task(self._consume(worker)) for worker in workers]
            return self
        except BaseException:
            await self.__aexit__(None, None, None)
            raise

    async def _consume(self, worker):
        while True:
            try:
                await worker.process_latest()
            except Exception as exc:
                logger.error('station source failed error_type=%s', type(exc).__name__)
            await asyncio.sleep(.03)

    async def __aexit__(self, *_):
        tasks, self._tasks = self._tasks, []
        server, self.server = self.server, None
        stack, self._stack = self._stack, None
        async with AsyncExitStack() as cleanup:
            # Every closer runs even if demand-off or an earlier closer fails.
            if stack is not None:
                cleanup.push_async_callback(stack.aclose)
            cleanup.callback(self.ingest.close_map_worker)
            if server is not None:
                cleanup.push_async_callback(server.wait_closed)
                cleanup.callback(server.close)
                cleanup.push_async_callback(self.ingest.stop_measurements)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def wait(self):
        if not self._tasks:
            raise RuntimeError('STATION_MEASUREMENT_NOT_RUNNING')
        done, _ = await asyncio.wait(self._tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            if not task.cancelled():
                task.exception()  # Retrieve the error without logging input or credentials.
        raise RuntimeError('STATION_MEASUREMENT_WORKER_STOPPED')


async def run_station_vision(args):
    from .cli import _server_ssl_context
    from .station_installation import load_station_installation
    installation = load_station_installation(args.config)
    async with StationVisionServer(installation, host=args.host, port=args.port,
            ssl_context=_server_ssl_context(args.tls_cert, args.tls_key)) as server:
        logger.info('station measurement pipeline started sources=%d', len(installation.sources))
        await server.wait()
