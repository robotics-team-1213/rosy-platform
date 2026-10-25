# monitoring

**Parent:** [operations/AGENTS.md](../AGENTS.md)

`rosy.monitoring` owns the independent D-876 observation models, scoped read configuration,
and monotonic aggregation cache. The current wheel is a Python foundation; its collector,
HTTP API, UI and deployment are not implemented yet. See [README.md](README.md).

- Keep this wheel ROS-free and independent of the Fleet distribution. Fleet owns its passive
  `/api/fleet/monitoring` producer; CORE/host owners retain their diagnostics and repair logic.
- Preserve original sample identity, reported health and source age across forwarding and restarts.
  A successful reread may renew the report path's 15-second lifetime, never the source deadline.
  Existing host reports may use 900/2100-second source lifetimes.
- A node's `reported_health` is evidence, not command authority or a physical acceptance result.
  Never add repair commands or copy raw source bodies, URLs, credentials or exception text into graphs.
- Reader authorization belongs at the service boundary. Cache filtering enforces registered scopes,
  not the caller's principal. Keep reader and upstream credentials separate.
- `pyproject.toml` owns only `rosy.monitoring*`; do not add `rosy/__init__.py`.

Run committed revisions through the repository remote pytest workflow with
`operations/monitoring/test`. The wheel test builds only in pytest's temporary directory.
