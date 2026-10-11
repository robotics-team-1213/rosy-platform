# Decision source owner

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-12

D-637 moves the existing implementation to `src/rosy/decision`; D-429 requires the `rosy.decision` namespace without an old-name shim. Fleet installs it in its existing distribution and retains the shared proposal transaction. Model output remains untrusted and advisory; CORE and the Arm execution owner retain their final writers.

Read the implementation guidance in `src/rosy/decision/AGENTS.md` and the existing Fleet tests. Owner records: [progress.md](progress.md), [logs.md](logs.md), [index.md](index.md).
