## D-887 Signed site service sets and identity-bound retirement

**Date:** 2026-10-26
**Status:** Accepted (2026-10-26)

## Context

Existing signed site candidates contain Fleet, Vision and Proxy. Current builds add PostgreSQL. Requiring four services everywhere prevents verification and rollback of authentic three-service candidates. Compose restart alone also leaves a PostgreSQL container when rolling back from four services to three.

## Decision

The authenticated manifest selects exactly the known three-service or four-service set. Builders continue producing four services. The verifier reports `verified_images` in both signature-only and loaded-image modes; runtime authority additionally requires fresh loaded-image identities. Missing or malformed proof never authorizes a legacy fallback.

Current, staged and rollback candidates each use their own verified service set, Compose files, allowed overlays, environment and image tag. Staged validation does not change the active link or environment. Canonical overlay names are allowlisted before rebasing them to the verified candidate directory.

Normal rollback authenticates both the prior candidate and the outgoing canonical candidate afresh. Four-to-three rollback may retire only PostgreSQL, identified by its immutable container ID, signed image reference and image ID, project/service labels and exact outgoing Compose configuration hash. Enumeration includes stopped containers; hashless manual containers are excluded from retirement. Ambiguity or failed inspection refuses mutation. Stop/remove targets only that ID, without force or volume deletion, and absence is checked before restoring the prior environment or link. Full incoming runtime health remains necessary before clearing the journal.

The one-time physical-directory relocation journal is distinct: `migration=true` requires identical current/target commits and verification of the original physical or recorded previous path. It retires no service. A flag alone cannot bypass outgoing authentication for a normal switch.

## Consequences and verification

Cold recovery needs the signed candidate files and loaded image references for both normal-switch candidates, even if outgoing containers never started or are unhealthy. If image proof disappears, recovery stays pending; cached identities cannot restore availability. Journals and environment backups remain until verified recovery completes. PostgreSQL volumes and manual containers survive.

Tests use real signatures for accepted manifest sets and an independent persistent container inventory for ordering, identity conflicts, cold recovery and failure injection. Local/remote source tests do not establish deployment, installed-helper parity or field acceptance. The external updater and all helpers must be installed from the same reviewed revision before a separately authorized operational migration.
