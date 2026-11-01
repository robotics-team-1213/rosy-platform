# monitoring

**Parent:** [operations/AGENTS.md](../AGENTS.md)

`rosy.monitoring` owns D-876 observation models, scoped configuration, durable aggregation,
owner-source collection, the read API, a POSIX launcher and native deployment inputs.
The separate application owns the UI; web_assets builds its fixed canonical deployment files.
See [README.md](README.md) and [the API contract](../../docs/reference/rosy-monitoring-api.md).
Current acceptance gates live in [progress.md](progress.md); record changes and verification
in [logs.md](logs.md), then regenerate the harness index.

- Keep this wheel ROS-free and independent of the Fleet distribution. Fleet owns its passive
  `/api/fleet/monitoring` producer; CORE/host owners retain their diagnostics and repair logic.
- Keep the launcher on loopback with one worker and a private 0700 state directory. Only the D-936
  site container passes `--host` for its unpublished internal network; never publish its port. Reject platforms
  whose private state permissions it cannot enforce; never skip that check to make startup succeed.
- Preserve original sample identity, reported health and source age across forwarding and receiving restarts.
  The service must use its owned `MonitoringStore`; publish facts and advance peer cursors only after durable commit.
  Restore report paths as stale and subtract elapsed time from source budgets. Never recreate a corrupt/foreign DB.
  A successful reread may renew the report path's 15-second lifetime, never the source deadline.
  Existing host reports may use 900/2100-second source lifetimes.
- A node's `reported_health` is evidence, not command authority or a physical acceptance result.
  Never add repair commands or copy raw source bodies, URLs, credentials or exception text into graphs.
- Reader authorization belongs at the service boundary. Cache filtering enforces registered scopes,
  not the caller's principal. Keep reader and upstream credentials separate.
- Serialize cache reads and updates in one owner, the collector event loop. Preserve anchors when
  observations disappear or become unknown; reaching the retention budget rejects new identities.
- `pyproject.toml` owns only `rosy.monitoring*`; do not add `rosy/__init__.py`.

Run committed revisions through the repository remote pytest workflow with
`operations/monitoring/test`. The wheel test builds only in pytest's temporary directory.
