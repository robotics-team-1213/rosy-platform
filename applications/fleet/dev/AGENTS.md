# Fleet frontend development host

Read [../README.md](../README.md) for sample/connected commands and [progress.md](progress.md) and [logs.md](logs.md) for verification scope and history. Root repository instructions own worktrees, commits, remote testing and landing.

- `http_host.py` serves the shared asset registry and enforces the local origin. `connected.py` forwards only the configured verified HTTPS API origin; preserve session/lease separation.
- `sample/` owns process-local representative state. Keep IDs, revisions, approval rules and terminal reads consistent across providers. Unknown requests must remain visible errors.
- `web/` contains sample browser providers and controls. Operational native providers live in `../web`; sample controls must not enter Fleet packaging.
- Verify changes through `../test` on a committed remote revision. The module's functional entry test is `../test/test_sample_server.py`; browser and real backend integration evidence have separate scopes in the README.
