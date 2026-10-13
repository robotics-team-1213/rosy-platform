## D-733 - Hourly KST Discord Fleet health subscription

**Status:** Accepted (2026-10-12, source contract; configuration, deployment, and runtime readback pending)

## Context

Operators need a concise Fleet status summary in the configured Discord channel each hour. Interactive replies require an actual source message, so a scheduled notice must not fabricate a human request or message reference. `SharedGather.__call__` reads every robot and performs traffic, handoff, and swarm logic, so the scheduled report cannot force it.

## Decision

The new `hourly_health_enabled` strict boolean defaults to false. When enabled, a health worker runs within the existing gateway lifespan and shares its authenticated, certifi-verified HTTP client, token, and fixed Discord channel. It reads only the cached Fleet snapshot, per-row observation age, actual AI observer heartbeat, configured robot identities, and read-only Task status counts. Missing or stale facts render as unknown; an observer heartbeat does not prove model admission. The report does not invoke a model, create a message reference, mention users, expose task details, add an endpoint, or issue robot commands.

A KST hour is durably claimed in SQLite under `BEGIN IMMEDIATE` before HTTP. Its stable nonce and unique slot prevent two workers from sending the same report. Startup skips missed slots. A claimed send recovered after restart becomes terminal UNKNOWN so an ambiguous delivery is never replayed. Only HTTP 429 and connection-establishment failures retry, within 120 seconds and at most three attempts. Responses are bounded and checked for the bot, configured channel, nonce, and provider message ID; ambiguous outcomes are not retried.

## Consequences

The source default stays disabled. Configuration, deployment, the first due-hour Discord readback, and operator acceptance remain separate gates. A source or remote-test pass does not establish that the channel received the report.
