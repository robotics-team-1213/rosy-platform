# notifications

**Parent:** [operations/AGENTS.md](../AGENTS.md)

`rosy-notifications` is the D-997 delivery service: machine-scoped intake, duplicate and body-conflict checks,
a private delivery journal and the shared channel adapters. Contract: [D-998](../../docs/adr/D-998-notification-delivery-http-journal.md)
and API v1.377. Setup and operation: [README.md](README.md).

- Pre-cutover. The Fleet worker in `operations/fleet/fleet/incidents/notifications.py` remains the sending owner (D-661).
  Never enable this worker on a channel the Fleet worker also sends to; keep `--enable-worker` off outside fake-channel tests.
- Producers own the business outbox, need and recipient scope. Re-check the owner right before each send; when the owner
  cannot confirm or the deadline passed, do not send. A send with unknown outcome is UNKNOWN and is never resent blindly.
- Callers never supply URLs, recipients or redirects. Channel endpoints and tokens come from environment variables named
  in the protected config; keep machine and callback tokens distinct.
- Keep Fleet's D-661 numbers (60 s, 3 attempts, 10 min) for the Fleet producer; do not apply them to other producers without a reason.
- One process owns the SQLite journal. Do not hold the write lock across network calls.
- Keep the wheel ROS-free with `COLCON_IGNORE`; it targets Linux/POSIX.

Run committed revisions through `python tools/remote/remote_pytest.py -- operations/notifications/test` and compare each run log
with `test/known_failures.py`.
