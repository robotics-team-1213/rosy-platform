# Site Fleet durable task queue: local evidence

Date: 2026-09-26
Scope: Windows host + Docker Desktop Linux engine, synthetic unreachable CORE endpoint.

## Evidence

- `python -m pytest src/site/fleet/test/ -q`: 485 passed, 5 skipped.
- `ROSY_RUN_BROWSER_TESTS=1 python -m pytest test/test_fleet_console_browser.py -q`:
  13 passed.
- `docker version`: client/server 29.7.2, Linux amd64 engine; Compose 5.3.1.
- `docker compose -f deploy/site/compose.yaml config --quiet`: passed with the
  required config/secrets directory variables set to temporary paths.
- `docker compose -f deploy/site/compose.yaml build fleet`: passed. Final image ID:
  `sha256:0c207e85fa8269cf753a505be14eaf2041babb09999bfd0de29929f3e9625ffb`.
- Ran that image as a local container bound only to `127.0.0.1`, using a named
  Docker volume for `/var/lib/rosy`. Submitted a navigation intent through the
  HTTP API, read it as `QUEUED`, stopped and restarted the container with the
  same volume, and read task `f42f93fa-6bf6-4b6b-9446-b5524d83532e` and its
  `QUEUED` history with `queue_position: 1` afterward.
- Removed the smoke container and named volume after readback. The locally built
  image remains available as `rosy-site-fleet:local`.

## Limits

The CORE endpoint was synthetic and unreachable, so no robot received a command.
This did not start the full Compose stack, validate the Ubuntu host, TLS/secrets,
camera ingestion, GPU inference, or device/field behavior. Those gates remain
open. No queue-depth or worker-pressure measurements were collected; D-271 Gate A
does not justify RabbitMQ, so the deployment remains SQLite plus the single
Fleet dispatcher.
