# Account

**Parent context:** [operations/AGENTS.md](../AGENTS.md)

Read [D-962](../../docs/adr/D-962-independent-account-and-authenticated-development.md) before changing authority or receiver ownership. Account owns human identities, credentials, grants, signing keys, sessions, profiles, administration and authentication audit. Fleet consumes signed grants through the foundation Account client; its compatibility imports point here.

- Keep `rosy_account` independently importable without Fleet or ROS. `COLCON_IGNORE` marks this standalone Python package outside colcon discovery.
- Startup requires an activated, validated Account database. Use `rosy_account.migration` for explicit extraction; preserve IDs, grants, revisions, session families and credential digests. Do not bootstrap an existing authority.
- Login, profile and administration assets remain owned by `applications/fleet/web`; the Account server serves its declared allowlist. Shared assets remain in `shared/web`.

For verification, follow the repository [test workflow](../../AGENTS.md). The package-owned [import-boundary check](test/test_boundaries.py) supplies only Account and foundation source paths to a fresh interpreter. Include the affected Fleet compatibility and receiver suites when changing authentication behavior; their tests remain in `operations/fleet/test`.

현재 검증 범위는 [progress.md](progress.md), 변경 근거는 [logs.md](logs.md), 문서·시험 탐색은 생성된 [index.md](index.md)에서 확인한다.
