# Hourly Discord health subpackage split (2026-10-12)

## Scope and owner

The fixed hourly KST subscription has a distinct lifecycle from interactive channel intake. `fleet/server/channel/health/` owns the wall-clock slot, durable SQLite claim, cached fact formatting, bounded delivery retry state, and startup recovery. `channel/gateway.py` constructs it inside the existing Fleet lifespan only when `hourly_health_enabled` is explicitly true; its bare publisher uses the same authenticated `httpx.AsyncClient`, token, channel, and shutdown lifetime as interactive replies. Existing interactive request parsing, approval, outbox replies, and execution remain in their current owners. The worker has no endpoint, generic scheduler, model call, robot writer, or forced Fleet gather.

The report reads the already cached `fleet_gather._snapshot` and row monotonic timestamps, observer heartbeat, configured console robot identities, and read-only Task status counts. Every absent or stale value renders unknown. It labels observer heartbeat separately from model admission and sends a bare scheduled message through an explicit fixed-channel publisher; the interactive reply method still requires an original human message reference.

## Lifecycle and installed closure

A KST hour is the unique slot key. Under `BEGIN IMMEDIATE`, one worker claims that slot and nonce durably before HTTP; other workers see the existing claim. A process started after the due boundary records a skipped slot instead of replaying missed reports. Restarted in-flight claims become terminal unknown, preventing duplicate delivery after an ambiguous send. Only explicit 429 or connection-establishment failures retry, with a 120-second window and three-attempt cap. Route changes during send become unknown and cannot move that slot to a newly configured channel.

The three-file owner (`hourly.py`, `discord.py`, `__init__.py`) remains beneath the existing `fleet` Python package, so its `__init__.py` makes it an ordinary installed subpackage. The implementation change must prove importability through the Fleet installed wheel and sdist/source packaging checks; no package discovery rule or deployment image exclusion is added. The existing Compose config mount is reused, and omission of the new strict boolean keeps the subscription off.

## Simultaneous size measurements and preserved limits

Read-only `test_module_structure._over_budget()` scan on the registered worktree `feat/hourly-discord-health`, over its working tree on top of test-first HEAD `b0de509c433b0efe34b8c10f6b0ceb950f937e5a`, after moving the publisher out of the existing integration holder and before size-registry edits:

| Owner | Current counted lines | Proposed after registration |
| --- | ---: | ---: |
| Fleet residual package | 55,428 | 55,428 |
| Fleet server/channel aggregate | 1,682 | 1,453 residual |
| Fleet server/channel/health | 229 | 229 |
| Fleet server/channel/conversation | 300 | 300 |
| Fleet server/channel/execution | 588 | 588 |

Health's 229 lines are `hourly.py` 179 + `discord.py` 46 + `__init__.py` 4. Registering health moves those exact lines out of the channel aggregate, leaving channel residual 1,453. The Fleet residual remains below its 55,286+150 cap; the channel residual remains below its 1,379+150 cap. Preserve the accepted Fleet baseline 55,286, channel baseline 1,379, conversation 280, and execution 487, each existing +150 allowance, every file ceiling and hard-tier rule, historical filter, and previous extraction obligation. Do not inflate baselines or add scanner exclusions. The root-owned independent structural precheck returned CONDITIONAL PASS on 2026-10-12 and authorized registering the 193-line health owner; the current 229-line owner remains within its unchanged +150 allowance after late-confirmed receipt retention. Final committed-HEAD rescan, remote regression, and installed wheel/sdist/source closure remain required.
## Verification and status

Required checks include fixed-slot/rollover and startup skip, concurrent SQLite claims, restart and route-change ambiguity, stale/missing cache, observer heartbeat distinctions, bounded retry and terminal unknown, no gather/model/robot effects, Discord request payload/readback, and installed wheel/sdist/source closure. Remote pytest only; compare every log using `test/known_failures.py`. A source pass does not prove deployment or actual Discord delivery: the first real due-hour message and channel readback remain a separate pending acceptance check.

Current status: implementation in progress; no baseline relaxation or scanner exclusion. The conditional precheck is source-scope evidence only; deployment, first real due-hour Discord readback, and operator acceptance remain pending.
