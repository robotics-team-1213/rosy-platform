# Transfer metadata review package — 2026-10-29

Scope: offline review preparation for the existing Fleet transfer outcome export v2. No robot, model training, label approval, upload or dispatch is performed. The implementation is `learning/curation/omx/transfer_review.py`; commands and limits are in that holder's README.

## Revision-bound verification

| Committed source | Check | Observed result |
|---|---|---|
| commit 85ea7b2575 | New root-overlap case before implementation | Remote RED: fixture reports missing transfer review implementation |
| commit b935447787 | Initial focused review package suite | Remote exit 0, 20 progress passes; classifier exit 0, NEW 0 |
| commit 744f0e7b50 | Cross-root aliases, including a missing child claimed by two roots | Both remote RED: expected rejection did not occur |
| commit 1acf28a38f | Exponent overflow isolated to the physical-cause metadata field | Remote RED: expected rejection did not occur; null lineage fields were left intact |
| commit ccc8712eceb04505da05222bfc06b84dd4e9d4da | Entire `learning/curation/omx/test` suite after fixes | Remote runner exit 0; 328 pass symbols and 10 skip symbols in completed pytest progress (338 total), classifier exit 0, NEW 0 |

The test invocation used `python tools/remote/remote_pytest.py --log-dir <external-log-dir> -- learning/curation/omx/test -q`. The suite's repeated quiet setting suppresses its usual summary line; the counts above are explicitly derived from its completed progress lines, not from an invented summary or a cumulative sum of overlapping runs. Skips are unverified checks. The new feature's 23 cases are included in the suite, not added to its total.

The independent read-only review identified the two actual integrity gaps. The final fix binds every declared root and child member to exactly one root, even without a corresponding export; it also rejects nonfinite results from `parse_float`, in addition to NaN/Infinity constants. Final review of commit ccc8712ece found no remaining material findings. The reviewer did not execute tests; the remote evidence above supplies that separate check.

## Source artifacts

Remote logs remain outside the source checkout in system TEMP. They may contain private transport details and are not copied into this repository.

| TEMP log directory (`run-1.txt`) | SHA-256 |
|---|---|
| `rosy-transfer-review-red-single` | `a6dde5407f9db60e09f8e58138d77ee04ff877a9ed78e39c315c25cb0d968430` |
| `rosy-transfer-review-alias-red` | `fca9c126a94cd7a4947b5e42d03d03e051e67b45825411132ae5a5479fe3396b` |
| `rosy-transfer-review-nonfinite-red` | `de604ad277deef13cdab262ca56969ddf9ce716b059370de886893c97b90aafc` |
| `rosy-transfer-review-final` | `2fb7702e42e6014f6ae2cc37e510ec0ab401aa55f0b7877abfc21170f1040557` |

## Interpretation and remaining acceptance

- Exact source bytes are copied; hashes and declared mission/root/partition identities are checked on reload. Package hashes do not authenticate a source DB or an adversary's jointly rewritten source and manifest.
- Partial recovery groups stay reviewable. Missing exports, physical failure causes, human labels and independence between sessions or environments are not inferred. Train/eval are proposed metadata-review partitions, not behavior-training admission.
- Existing `unreviewed_metadata_only`, `raw_camera_bytes_available=false` and `behavior_training_eligible=false` flags stay in place. Actual outcome/decision labels require separate human review; behavior training additionally requires real source frames, applied actions, clocks and intervention evidence.
- Local-main landing and temporary-slot return follow the official gateway after this frozen source verification. Their eventual status belongs in the workspace integration record, not a rewrite of these observations.
- CE: not applicable. The root/member invariant, partial-group handling and strict JSON reason are recoverable from the final code, regressions and this result; no separate durable lesson is warranted.
