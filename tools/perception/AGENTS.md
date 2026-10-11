# Perception operator tools

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-12

This holder contains `rosy_ml.py`, the cross-owner learning CLI, and `operator_ssh.py`, the pinned operator SSH options. D-637 preserves their bare module identities. Curation code lives in `learning/curation/perception`, the shared artifact/provenance store and model lifecycle in `learning/registry/perception`, trainer jobs in `learning/training/perception`, and replay evaluation in `learning/evaluation/perception`.

CORE owns final commands. Learning remains advisory until separately admitted. Preserve READY markers, content and source signatures, fixed revisions, operator key/known-hosts options, intake gates, and shadow-only delivery. Never bypass a failed intake or activate a delivered model as part of folder maintenance. Store datasets, evalsets, models and inbox inputs retain their existing shared lineage.

Read the repository [AGENTS.md](../../AGENTS.md) and D-637 before changing imports or consumers. Standalone scripts initialize only their exact source holders; signed release bootstrap explicitly includes each required holder. Tests are the shared suite in `test/learning/perception`; run only committed HEAD through `tools/remote/remote_pytest.py`, followed by `test/known_failures.py`.

See [progress.md](progress.md), [logs.md](logs.md), and [index.md](index.md). These owner records remain HOLD until their actual gates are proven. Host tests do not prove device or field acceptance.
