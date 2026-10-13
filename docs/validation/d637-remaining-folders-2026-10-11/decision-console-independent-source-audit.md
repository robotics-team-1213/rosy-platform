# Decision / Console independent source closure audit

2026-10-11; read-only candidate during root packaging work, baseline ea6d4c0a2.

- No remaining executable fleet.ai import or dynamic module string in production/tools/deploy/tests/fixtures. The sole code-text match is the installed test asserting find_spec('fleet.ai') is None. Wire API `/api/fleet/ai`, `fleet.ai_first` config and historical records remain intentionally unchanged.
- Canonical rosy.decision root, source_packages mount, dependency component plus forbidden imports, exact component test expectation and harness module registration are present. D-430 safety modules/anchors contain no retired fleet.ai path or symbol; safety authority and public anchors remain unchanged.
- Docker COPY and dockerignore plus workflow trigger include operations/decision. Source-only Fleet bootstrap invokes the static canonical source root; installed namespace handling is covered by root's isolated wheel/sdist test in both import orders with World/execution/skills namespace coexistence.
- Initially G2 omitted the moved Decision files from SOURCE_PATHS/source_sha256 and module-origin readback. Root fixed both during this audit; final re-read confirms operations/decision/src and rosy.decision.model_tool_contract origin. No missing executable consumer remains in this bounded source audit.
- All 66 Console files match the baseline checkout bytes exactly, including AGENTS.md and package.json. Raw git blobs use LF while the checkout uses CRLF; comparison used git cat-file --filters with the original path to apply the repository checkout rules before SHA comparison. No actual content or line difference exists.
- Remaining physical old parent: operations/fleet/fleet/server/web contains only empty cell/ and shared/ child directories. Exact non-recursive cleanup sequence is cell, shared, web after confirming they remain empty. This audit did not remove them.

The JSON records all 66 original/target paths and baseline/raw/filtered SHA256 values plus the resolved G2 findings. No product files, tests or commits were changed. This is source evidence, not an installed-test or deployment result.
