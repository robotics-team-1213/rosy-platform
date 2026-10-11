"""Existing Fleet lifespan owns the optional Discord transport worker."""
import asyncio
import logging
import sqlite3
from contextlib import AsyncExitStack, asynccontextmanager

import httpx
from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool
from rosy_discord.gateway import DiscordGateway
from rosy_discord.replies import DiscordReplies

from .channel_replies import ChannelReplyOutbox, ChannelReplyWorker


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
    if config.replies_enabled:
        journal.reply_outbox = ChannelReplyOutbox(journal)
    worker = DiscordGateway(token=token, guild_id=config.guild_id, channel_id=config.channel_id,
                            bot_id=config.bot_id, consume=consume)
    previous = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        async with previous(application) as state, AsyncExitStack() as stack:
            tasks = [asyncio.create_task(worker.run())]
            if config.replies_enabled:
                http = await stack.enter_async_context(httpx.AsyncClient())
                sender = DiscordReplies(channel_id=config.channel_id, bot_id=config.bot_id, token=token, http=http)
                tasks.append(asyncio.create_task(ChannelReplyWorker(journal.reply_outbox, sender).run()))
            try:
                yield state
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

    app.router.lifespan_context = lifespan
