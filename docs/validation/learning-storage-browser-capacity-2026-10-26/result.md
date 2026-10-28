# Storage preflight browser capacity fixture

## Problem and scope

C1 landing candidate `700e0b82e7` stopped on two storage-browser failures. The official comparison reproduced both viewport failures on main commit `94d0988561`: a test expecting a ready estimate requiring3 GiB observed only2.802 GiB of actual host space. This was MAIN-RED, not a successful landing. The separate keyboard browser case passed isolation and remains a load-flaky candidate, not a new known-failure entry.

The synthetic storage browser fixture now supplies10 GiB through the existing `storage_inventory.free_space` observation boundary and checks that displayed capacity. Production storage checks are unchanged. The existing ready, remote-quota-unknown, insufficient-space, HTTP failure, revocation and narrow-screen checks remain. No operational labels, datasets or review state are used.

## Committed verification

- Test fix commit `d24d1abc64`; actual D-766 range check passes.
- Official remote execution after model-host disk preflight:55.142 GiB available,87.41% used. The child gateway selected only the model host.
- Actual opt-in command: `ROSY_RUN_BROWSER_TESTS=1 test/learning/perception/test_storage_inventory_http.py test/learning/perception/test_storage_inventory.py`.
- Result:10 PASS, no skips,7.15s; native runner exit0 and NEW0/known0/flaky0. Both1440px and320px browser cases executed.
- Raw logs: `%TEMP%/rosy-storage-browser-main-fix/green/{runner.txt,run-1.txt}`. Failed C1 and main-comparison logs remain in the C1 landing evidence directory.

This is fixture and host-side verification. No landing, model quality, device behavior or field acceptance is inferred. Official integration checks remain separate.

CE: 해당 없음 — the fixed observation and visible-value assertion explain the test decision; the existing lab-host storage policy already distinguishes agent disk checks from runner implementation. Operational low-space observations are kept in workspace records rather than described as a product fix.
