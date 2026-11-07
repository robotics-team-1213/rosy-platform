"""Explicit loopback launcher; no deployment or producer cutover is installed."""

import argparse
import asyncio
from pathlib import Path

import httpx
import uvicorn

from .api import create_app
from .config import load
from .journal import Journal
from .service import DeliveryService


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--journal', required=True, type=Path)
    parser.add_argument('--port', type=int, default=8794)
    parser.add_argument('--enable-worker', action='store_true')
    args = parser.parse_args()
    channels, producers = load(args.config)
    journal = Journal(args.journal)
    async def serve():
        async with httpx.AsyncClient(trust_env=False) as http:
            app = create_app(DeliveryService(journal, channels, producers, http),
                             worker_enabled=args.enable_worker)
            await uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=args.port)).serve()

    try:
        asyncio.run(serve())
    finally:
        journal.close()


if __name__ == '__main__':
    main()
