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


async def goal_evidence_expiry_loop(service, logger) -> None:
    """Apply registered grace deadlines without enabling Action dispatch."""
    while True:
        try:
            service.hold_expired_without_evidence()
        except (OSError, ValueError):
            logger.exception("goal evidence grace reconciliation failed")
        await asyncio.sleep(1.0)
