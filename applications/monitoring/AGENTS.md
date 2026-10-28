# Monitoring application

**Parent:** [applications/AGENTS.md](../AGENTS.md)

Read [README.md](README.md), [SURFACE.md](SURFACE.md) and the owning
[service records](../../operations/monitoring/progress.md) before changes.
Record verification in [the module log](../../operations/monitoring/logs.md).

- Consume only the scoped Monitoring read API. Fleet/CORE/host owners retain commands,
  diagnostics and recovery; do not add another Fleet state poller or database reader.
- Keep reader keys in memory. Abort pending reads and invalidate response epochs on logout,
  key or site changes. Never place keys in URLs, persisted storage, DOM text or screenshots.
- Preserve source/report lifetimes in the browser. Expire cached evidence locally when reads stop;
  retain the last verdict as historical information. Render upstream labels with textContent.
- Reuse canonical shared web tokens, components, theme and evidence wording. Only deployment
  artifacts may copy the fixed shared asset list; source copies do not belong here.
- Verify against the actual backend, without intercepting its API. Use browser_harness.safe_listener
  for the test server. D-153 G1/G2/G3 and actual DEVICE/FIELD acceptance are separate evidence.
