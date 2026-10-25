# Neutral ARM forward-port source review

2026-10-26. Independent reviewer: `neutral_forward_port_contract_review` (read-only ROSY contract reviewer), separate from the implementing `neutral_arm_forward_port` agent and committing root.

Reviewed base: `de00f06ded5921d98197be271cee8c55b71d6afa`. Reviewed source tree: `5ac92534cd2ed0c9ffc0ecd93b612ff344a4c891`. This record was added after that source review; it changes no runtime behavior.

No supported material contract finding remained in the inspected forward port. The review traced producer/consumer authority, shared journal and legacy provenance, two-person approval, claims, durable first-send, exact managed OMX admission, ordered phase receipt and independent observation closure. Installed ARM participants remain in HTTP, intent/rearm and typed control-unit stop coverage. The current main integrated-control and monitoring ownership is retained.

With no ARM installation, routes remain unavailable and no physical worker is created. Configured installation and dispatcher remain simulation-only. This merge does not establish a production installation contract or device activation. API header, app descriptions and test pin agree on v1.320 while reserved feature history is preserved.

Static checks on the reviewed tree: 108 Python files parsed, 11 JSON files parsed, six JavaScript syntax checks; harness lint zero errors (33 freshness warnings); static size guard no problems. The OMX root remains under the unit cap after using its existing contracts holder with compatibility imports.

This is scoped independent **source review** under D-430 §5. Exact committed-revision remote affected/FULL/browser gates remain required before landing. Older validation records do not verify this merged tree. No tests were run by the reviewer, and neither this record nor its Safety-Review reference certifies device behavior or field safety.

Runtime journal migration v8 can affect rollback even when physical activation is closed. Deployment still requires matched backup, restore/compatibility evidence and the supported production installation/provisioning work. No production account, service, device or deployment was changed during this review.

## Canonical import follow-up

The exact c0efaeb41e remote affected run exposed three NEW collection errors from the pre-main flat PickPlaceTransaction import. The explicit browser invocation passed25 tests with zero skips, but it did not discharge those failures or the FULL gate.

The same independent reviewer inspected c0efaeb41e → staged source tree550ae7a55c9096bf78d752b721d35713dbda43e4: five import replacements in four files, resolving PickPlaceRunner/PickPlaceTransaction to main's existing `omx_adapter.pick_place` classes. No signatures, admission checks, fences, execution logic or assertions changed. No supported source finding remained. The reported static destination audit is implementer evidence, not a test executed by the reviewer. Corrected-commit remote verification remains required.

## Machine service bootstrap and signed packaging transition

The same independent reviewer inspected base a0ac3b1102 → source tree `d17b5c06ce396b429f9dc5e2eddfe84a110a6b40`, containing exactly `deploy/site/site_users.py`, `build_candidate.py`, `verify_candidate.py` and `README.md`. No supported material finding remained. These paths have no matching safety-module or anchor tag; this scoped change does not itself require a D-430 trailer.

The new stdin-only command fixes authority to the existing service role, preserves human-role restrictions, and reuses validated atomic registry publication and ownership. Its outcome exposes no token or digest. The builder signs the required-tool marker and file hash. The verifier accepts historical omission, rejects every present non-literal-true marker, and verifies every listed tool's path and hash after signature verification. The unchanged updater uses its trusted sibling verifier for both current-candidate and rollback checks. The documented administrator refresh precedes new inventory acceptance.

The reviewer inspected tests for Fleet loader compatibility, secret-free output, refusals, dry-run, ownership failure, marker types, legacy candidates, tool hashes and real-signature tampering. Earlier RED snapshots are not implementation acceptance. Exact implementation-commit remote GREEN, updater/rollback regressions and normal landing gates remain required. No host provisioning, operating account, deployment or device action was performed by this review.
