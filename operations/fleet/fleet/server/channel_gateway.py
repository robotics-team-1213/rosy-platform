"""Existing Fleet lifespan owns the optional Discord transport worker."""
import asyncio
import logging
import sqlite3
from contextlib import asynccontextmanager, suppress

from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool
from rosy_discord.gateway import DiscordGateway


def install_gateway(app, journal, token):
    async def consume(envelope):
        try:
            await run_in_threadpool(journal.receive, envelope)
        except HTTPException as error:
            if error.status_code >= 500:
                raise OSError("Discord reception journal unavailable") from None
            logging.getLogger(__name__).info("Discord request refused by Fleet reception contract")
        except sqlite3.Error:
            raise OSError("Discord reception journal unavailable") from None

    config = journal.config
    worker = DiscordGateway(token=token, guild_id=config.guild_id, channel_id=config.channel_id,
                            bot_id=config.bot_id, consume=consume)
    previous = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        async with previous(application) as state:
            task = asyncio.create_task(worker.run())
            try:
                yield state
            finally:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    app.router.lifespan_context = lifespan
