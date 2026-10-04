"""App-owned periodic maintenance, separated from the HTTP app factory."""

import asyncio
import sqlite3


async def proposal_expiry_loop(proposal_store, logger) -> None:
    while True:
        try:
            proposal_store.purge_expired()
        except (OSError, sqlite3.Error):
            logger.exception("expired Fleet proposal cleanup failed")
        await asyncio.sleep(3600)
